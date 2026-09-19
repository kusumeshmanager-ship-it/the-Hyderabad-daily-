import os
import json
import re
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

# ============================================================
# THE HYDERABAD DAILY — AIRA DIGITAL NEWS
# LOW-TOKEN / FREE-MODE VERSION
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

CONTENT_FILE = os.path.join(DATA_DIR, "digital-news-content.json")
REGISTRY_FILE = os.path.join(DATA_DIR, "digital-news-registry.json")
EPAPER_FILE = os.path.join(DATA_DIR, "epaper-registry.json")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

# Keep API usage deliberately small.
MAX_NEW_STORIES = 1
MAX_AGE_HOURS = 36
MAX_DESCRIPTION_CHARS = 700
MAX_OUTPUT_TOKENS = 700
TIMEOUT = 20

FEEDS = {
    "Hyderabad": "Hyderabad Telangana latest news",
    "Telangana": "Telangana latest news",
    "India": "India latest news",
    "World": "world latest news",
    "Business": "India business markets latest news",
    "Technology": "technology AI gadgets latest news",
    "Entertainment": "India entertainment OTT movies music latest news",
    "Sports": "India sports latest news",
}


def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize(text):
    text = str(text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on",
        "for", "with", "from", "by", "at", "is", "are"
    }
    return " ".join(w for w in text.split() if w not in stopwords)


def words(text):
    return set(normalize(text).split())


def similarity(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0
    return len(wa & wb) / max(len(wa | wb), 1)


def story_id(url, title):
    value = (url or "") + "|" + normalize(title)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def parse_date(value):
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fetch_feed(category, query):
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    )
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={"User-Agent": "The Hyderabad Daily AIRA/1.0"},
    )
    response.raise_for_status()

    root = ET.fromstring(response.text)
    results = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()
        pub_date = item.findtext("pubDate", "").strip()

        if not title or not link:
            continue

        dt = parse_date(pub_date)
        if dt and now_utc() - dt > timedelta(hours=MAX_AGE_HOURS):
            continue

        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()
        description = description[:MAX_DESCRIPTION_CHARS]

        results.append({
            "category": category,
            "title": title,
            "link": link,
            "canonicalUrl": link,
            "description": description,
            "pubDate": pub_date,
        })

    return results


def already_published(article, registry, content):
    url = normalize(article.get("canonicalUrl") or article.get("link"))
    title = normalize(article.get("title", ""))

    for collection in (
        registry.get("publishedStories", []),
        content.get("stories", []),
    ):
        for story in collection:
            old_url = normalize(
                story.get("canonicalUrl") or story.get("url")
            )
            old_title = normalize(
                story.get("normalizedTitle") or story.get("title")
            )

            if url and old_url and url == old_url:
                return True

            if title and old_title and similarity(title, old_title) >= 0.84:
                return True

    return False


def in_epaper(article, epaper):
    title = normalize(article.get("title", ""))
    url = normalize(article.get("canonicalUrl") or article.get("link"))

    for story in epaper.get("stories", []):
        old_url = normalize(
            story.get("canonicalUrl") or story.get("url")
        )
        old_title = normalize(
            story.get("normalizedTitle") or story.get("title")
        )

        if url and old_url and url == old_url:
            return True

        if title and old_title and similarity(title, old_title) >= 0.82:
            return True

    return False


def editorial_prompt(article):
    return f"""
You are The Hyderabad Daily Digital News editorial desk.

Create a SHORT, ORIGINAL news presentation using ONLY the supplied feed
information below.

Rules:
- Do not browse.
- Do not invent facts.
- Do not copy source wording.
- If information is insufficient, keep it minimal and factual.
- For political stories, remain neutral and factual.
- Do not endorse parties, candidates or policies.
- Do not make election predictions.
- Do not speculate about people.
- Return ONLY valid JSON.

JSON:
{{
  "editorialSummary": "2 short factual sentences",
  "brief": ["1 short factual paragraph", "1 short factual paragraph"],
  "keyPoints": ["fact", "fact"]
}}

Category: {article.get("category", "")}
Headline: {article.get("title", "")}
Date: {article.get("pubDate", "")}
Feed information: {article.get("description", "")}
""".strip()


def call_openai(article):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    # LOW-TOKEN MODE:
    # No web_search tool. The RSS information is the supplied input.
    payload = {
        "model": MODEL,
        "input": editorial_prompt(article),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )

    if response.status_code >= 400:
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            suffix = f" Retry-After: {retry_after}" if retry_after else ""
            raise RuntimeError(
                "OpenAI rate limit 429. No automatic retry is attempted."
                + suffix
            )
        raise RuntimeError(
            f"OpenAI API error {response.status_code}: "
            f"{response.text[:1200]}"
        )

    data = response.json()
    output_text = ""

    for item in data.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    output_text += part.get("text", "")

    output_text = output_text.strip()

    if not output_text:
        raise RuntimeError("OpenAI returned no editorial text.")

    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", output_text, re.DOTALL)
    if not match:
        raise RuntimeError("OpenAI response was not valid JSON.")

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned invalid JSON: {exc}")


def valid_editorial(data):
    if not isinstance(data, dict):
        return False

    summary = str(data.get("editorialSummary", "")).strip()
    brief = data.get("brief", [])
    points = data.get("keyPoints", [])

    return (
        bool(summary)
        and isinstance(brief, list)
        and isinstance(points, list)
    )


def main():
    print("AIRA Digital News low-token update started.")

    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is missing.")

    content = load_json(
        CONTENT_FILE,
        {"version": 1, "lastUpdated": "", "stories": []},
    )

    registry = load_json(
        REGISTRY_FILE,
        {"version": 1, "lastUpdated": "", "publishedStories": []},
    )

    epaper = load_json(
        EPAPER_FILE,
        {"version": 1, "stories": []},
    )

    candidates = []

    for category, query in FEEDS.items():
        try:
            print(f"Fetching {category}...")
            for item in fetch_feed(category, query):
                if already_published(item, registry, content):
                    continue

                if in_epaper(item, epaper):
                    print("Excluded e-paper story:", item["title"])
                    continue

                candidates.append(item)

        except Exception as exc:
            print(f"Feed error for {category}: {exc}")

    candidates.sort(
        key=lambda x: parse_date(x.get("pubDate", ""))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    # Only ONE story is selected per run.
    selected = []
    for article in candidates:
        if len(selected) >= MAX_NEW_STORIES:
            break
        selected.append(article)

    print(f"Selected {len(selected)} new stories.")

    added = 0

    for article in selected:
        try:
            print("Preparing editorial:", article["title"])

            editorial = call_openai(article)

            if not valid_editorial(editorial):
                print("Rejected: incomplete editorial.")
                continue

            editorial_date = now_utc().date().isoformat()

            record = {
                "id": story_id(article.get("link"), article.get("title")),
                "approved": True,
                "category": article.get("category", "Latest"),
                "title": article.get("title", ""),
                "normalizedTitle": normalize(article.get("title", "")),
                "canonicalUrl": (
                    article.get("canonicalUrl")
                    or article.get("link", "")
                ),
                "editorialSummary": str(
                    editorial.get("editorialSummary", "")
                ).strip(),
                "brief": [
                    str(x).strip()
                    for x in editorial.get("brief", [])
                    if str(x).strip()
                ][:2],
                "keyPoints": [
                    str(x).strip()
                    for x in editorial.get("keyPoints", [])
                    if str(x).strip()
                ][:3],
                "editorialDate": editorial_date,
                "editorialByline": "The Hyderabad Daily Digital Desk",
            }

            content.setdefault("stories", []).insert(0, record)

            registry.setdefault("publishedStories", []).append({
                "id": record["id"],
                "canonicalUrl": record["canonicalUrl"],
                "normalizedTitle": record["normalizedTitle"],
                "eventKey": record["id"],
                "publishedAt": now_utc().isoformat(),
            })

            added += 1

        except Exception as exc:
            print("Editorial error:", exc)

    timestamp = now_utc().isoformat()
    content["lastUpdated"] = timestamp
    registry["lastUpdated"] = timestamp

    content["publicationPolicy"] = {
        "requireEditorialContent": True,
        "requireApproval": True,
        "displayOnlyApprovedStories": True,
        "fallbackText": False,
        "fieldsRequired": [
            "editorialSummary",
            "brief",
            "keyPoints",
            "editorialDate",
            "editorialByline",
        ],
    }

    save_json(CONTENT_FILE, content)
    save_json(REGISTRY_FILE, registry)

    print(f"AIRA Digital News update complete. Added {added} stories.")


if __name__ == "__main__":
    main()
