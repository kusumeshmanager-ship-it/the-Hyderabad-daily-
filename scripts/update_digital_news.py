import os
import json
import re
import time
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests


# ============================================================
# THE HYDERABAD DAILY
# AIRA DIGITAL NEWS AUTOMATION
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

CONTENT_FILE = os.path.join(
    DATA_DIR,
    "digital-news-content.json"
)

REGISTRY_FILE = os.path.join(
    DATA_DIR,
    "digital-news-registry.json"
)

EPAPER_FILE = os.path.join(
    DATA_DIR,
    "epaper-registry.json"
)

OPENAI_API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    ""
).strip()

MODEL = os.environ.get(
    "OPENAI_MODEL",
    "gpt-5.6-luna"
)

# SAFER RATE-LIMIT SETTINGS
MAX_NEW_STORIES = 2
MAX_AGE_HOURS = 36
MAX_DESCRIPTION_CHARS = 900
TIMEOUT = 30


# ============================================================
# NEWS FEEDS
# ============================================================

FEEDS = {
    "Hyderabad": "Hyderabad Telangana latest news",
    "Telangana": "Telangana latest news",
    "India": "India latest news",
    "World": "world latest news",
    "Business": "India business markets latest news",
    "Technology": "technology AI gadgets latest news",
    "Entertainment": "India entertainment OTT movies music latest news",
    "Sports": "India sports latest news"
}


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


# ============================================================
# JSON
# ============================================================

def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(path, data):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize(text):

    text = str(text or "").lower()

    text = re.sub(
        r"https?://\S+",
        " ",
        text
    )

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    stopwords = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "at",
        "is",
        "are"
    }

    return " ".join(
        word
        for word in text.split()
        if word not in stopwords
    )


def words(text):

    return set(
        normalize(text).split()
    )


def similarity(a, b):

    wa = words(a)
    wb = words(b)

    if not wa or not wb:
        return 0

    return len(
        wa & wb
    ) / max(
        len(wa | wb),
        1
    )


# ============================================================
# STORY ID
# ============================================================

def story_id(url, title):

    value = (
        (url or "")
        + "|"
        + normalize(title)
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# DATE
# ============================================================

def parse_date(value):

    if not value:
        return None

    try:

        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# GOOGLE NEWS RSS
# ============================================================

def fetch_feed(category, query):

    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(query)}"
        "&hl=en-IN"
        "&gl=IN"
        "&ceid=IN:en"
    )

    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent":
                "The Hyderabad Daily AIRA/1.0"
        }
    )

    response.raise_for_status()

    root = ET.fromstring(
        response.text
    )

    results = []

    for item in root.findall(
        ".//item"
    ):

        title = item.findtext(
            "title",
            ""
        ).strip()

        link = item.findtext(
            "link",
            ""
        ).strip()

        description = item.findtext(
            "description",
            ""
        ).strip()

        pub_date = item.findtext(
            "pubDate",
            ""
        ).strip()

        if not title or not link:
            continue

        dt = parse_date(
            pub_date
        )

        if dt:

            age = (
                now_utc() - dt
            )

            if age > timedelta(
                hours=MAX_AGE_HOURS
            ):

                continue

        # Remove HTML
        description = re.sub(
            r"<[^>]+>",
            " ",
            description
        ).strip()

        # Limit description size
        description = description[
            :MAX_DESCRIPTION_CHARS
        ]

        results.append({

            "category": category,

            "title": title,

            "link": link,

            "canonicalUrl": link,

            "description": description,

            "pubDate": pub_date

        })

    return results


# ============================================================
# DUPLICATE CHECK
# ============================================================

def already_published(
    article,
    registry,
    content
):

    url = (
        article.get("canonicalUrl")
        or article.get("link")
    )

    title = article.get(
        "title",
        ""
    )

    normalized_url = normalize(
        url
    )

    normalized_title = normalize(
        title
    )

    # Digital News history
    for story in registry.get(
        "publishedStories",
        []
    ):

        old_url = normalize(
            story.get(
                "canonicalUrl"
            )
            or story.get("url")
        )

        old_title = normalize(
            story.get(
                "normalizedTitle"
            )
            or story.get("title")
        )

        if (
            normalized_url
            and old_url
            and normalized_url == old_url
        ):

            return True

        if (
            normalized_title
            and old_title
            and similarity(
                normalized_title,
                old_title
            ) >= 0.84
        ):

            return True

    # Content history
    for story in content.get(
        "stories",
        []
    ):

        old_url = normalize(
            story.get(
                "canonicalUrl"
            )
            or story.get("url")
        )

        old_title = normalize(
            story.get(
                "normalizedTitle"
            )
            or story.get("title")
        )

        if (
            normalized_url
            and old_url
            and normalized_url == old_url
        ):

            return True

        if (
            normalized_title
            and old_title
            and similarity(
                normalized_title,
                old_title
            ) >= 0.84
        ):

            return True

    return False


# ============================================================
# E-PAPER EXCLUSION
# ============================================================

def in_epaper(article, epaper):

    title = normalize(
        article.get(
            "title",
            ""
        )
    )

    url = normalize(
        article.get(
            "canonicalUrl"
        )
        or article.get(
            "link"
        )
    )

    for story in epaper.get(
        "stories",
        []
    ):

        old_url = normalize(
            story.get(
                "canonicalUrl"
            )
            or story.get("url")
        )

        old_title = normalize(
            story.get(
                "normalizedTitle"
            )
            or story.get("title")
        )

        if (
            url
            and old_url
            and url == old_url
        ):

            return True

        if (
            title
            and old_title
            and similarity(
                title,
                old_title
            ) >= 0.82
        ):

            return True

    return False


# ============================================================
# CROSS-FEED DUPLICATE
# ============================================================

def cross_feed_duplicate(
    article,
    selected
):

    title = article.get(
        "title",
        ""
    )

    for other in selected:

        if similarity(
            title,
            other.get(
                "title",
                ""
            )
        ) >= 0.82:

            return True

    return False


# ============================================================
# AIRA EDITORIAL PROMPT
# ============================================================

def editorial_prompt(article):

    return f"""
You are The Hyderabad Daily Digital News
editorial desk.

Prepare a short ORIGINAL editorial presentation
for the news item below.

Rules:

- Do not copy source wording.
- Do not invent facts.
- Use verified facts.
- Write natural newspaper language.
- Digital News must be different from the e-paper.
- For political stories, remain neutral and factual.
- Do not endorse parties, candidates or policies.
- Do not make election predictions.
- Do not speculate about people.
- Do not mention AI generation.
- Return ONLY JSON.

JSON format:

{{
  "editorialSummary": "2-3 sentence original summary.",
  "brief": [
    "One concise factual paragraph.",
    "One concise factual paragraph."
  ],
  "keyPoints": [
    "Important factual point.",
    "Important factual point."
  ]
}}

Category:
{article.get("category", "")}

Headline:
{article.get("title", "")}

Date:
{article.get("pubDate", "")}

Original URL:
{article.get("link", "")}

Available information:
{article.get("description", "")}
""".strip()


# ============================================================
# OPENAI
# ============================================================

def call_openai(article):

    if not OPENAI_API_KEY:

        raise RuntimeError(
            "OPENAI_API_KEY is not configured."
        )

    # IMPORTANT:
    # Web Search and JSON response-format mode
    # cannot be combined in this request.
    #
    # JSON is requested through the prompt and
    # parsed locally.

    payload = {

        "model": MODEL,

        "tools": [
            {
                "type": "web_search"
            }
        ],

        "input": editorial_prompt(
            article
        )
    }

    response = requests.post(

        "https://api.openai.com/v1/responses",

        headers={

            "Authorization":
                f"Bearer {OPENAI_API_KEY}",

            "Content-Type":
                "application/json"

        },

        json=payload,

        timeout=120
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"OpenAI API error "
            f"{response.status_code}: "
            f"{response.text[:1200]}"
        )

    data = response.json()

    output_text = ""

    for item in data.get(
        "output",
        []
    ):

        if item.get(
            "type"
        ) == "message":

            for content in item.get(
                "content",
                []
            ):

                if content.get(
                    "type"
                ) == "output_text":

                    output_text += (
                        content.get(
                            "text",
                            ""
                        )
                    )

    if not output_text:

        raise RuntimeError(
            "OpenAI returned no editorial text."
        )

    output_text = (
        output_text.strip()
    )

    # Direct JSON
    try:

        return json.loads(
            output_text
        )

    except json.JSONDecodeError:

        pass

    # Extract JSON object
    match = re.search(
        r"\{.*\}",
        output_text,
        re.DOTALL
    )

    if not match:

        raise RuntimeError(
            "OpenAI response was not valid JSON."
        )

    try:

        return json.loads(
            match.group(0)
        )

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            "OpenAI returned invalid JSON: "
            f"{exc}"
        )


# ============================================================
# VALIDATE EDITORIAL
# ============================================================

def valid_editorial(data):

    if not isinstance(
        data,
        dict
    ):

        return False

    summary = str(
        data.get(
            "editorialSummary",
            ""
        )
    ).strip()

    brief = data.get(
        "brief",
        []
    )

    points = data.get(
        "keyPoints",
        []
    )

    if not summary:
        return False

    if not isinstance(
        brief,
        list
    ):

        return False

    if not isinstance(
        points,
        list
    ):

        return False

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "AIRA Digital News update started."
    )

    if not OPENAI_API_KEY:

        raise SystemExit(
            "OPENAI_API_KEY is missing."
        )

    # Load Digital News content

    content = load_json(

        CONTENT_FILE,

        {
            "version": 1,
            "lastUpdated": "",
            "stories": []
        }
    )

    # Load Digital News registry

    registry = load_json(

        REGISTRY_FILE,

        {
            "version": 1,
            "lastUpdated": "",
            "publishedStories": []
        }
    )

    # Load e-paper registry

    epaper = load_json(

        EPAPER_FILE,

        {
            "version": 1,
            "stories": []
        }
    )

    candidates = []

    # --------------------------------------------------------
    # FETCH NEWS
    # --------------------------------------------------------

    for category, query in FEEDS.items():

        try:

            print(
                f"Fetching {category}..."
            )

            items = fetch_feed(
                category,
                query
            )

            for item in items:

                # Already published
                if already_published(
                    item,
                    registry,
                    content
                ):

                    continue

                # Already in e-paper
                if in_epaper(
                    item,
                    epaper
                ):

                    print(
                        "Excluded e-paper story:",
                        item["title"]
                    )

                    continue

                candidates.append(
                    item
                )

        except Exception as exc:

            print(
                f"Feed error for "
                f"{category}: {exc}"
            )

    # --------------------------------------------------------
    # SORT NEWEST FIRST
    # --------------------------------------------------------

    candidates.sort(

        key=lambda x:
            parse_date(
                x.get(
                    "pubDate",
                    ""
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),

        reverse=True
    )

    # --------------------------------------------------------
    # SELECT ONLY TWO
    # --------------------------------------------------------

    selected = []

    for article in candidates:

        if len(selected) >= MAX_NEW_STORIES:

            break

        if cross_feed_duplicate(
            article,
            selected
        ):

            continue

        selected.append(
            article
        )

    print(
        f"Selected "
        f"{len(selected)} new stories."
    )

    # --------------------------------------------------------
    # EDITORIAL PROCESSING
    # --------------------------------------------------------

    added = 0

    for index, article in enumerate(
        selected
    ):

        try:

            print(
                "Preparing editorial:",
                article["title"]
            )

            editorial = call_openai(
                article
            )

            if not valid_editorial(
                editorial
            ):

                print(
                    "Rejected: "
                    "incomplete editorial."
                )

                continue

            editorial_date = (
                now_utc()
                .date()
                .isoformat()
            )

            record = {

                "id":
                    story_id(
                        article.get(
                            "link"
                        ),
                        article.get(
                            "title"
                        )
                    ),

                "approved":
                    True,

                "category":
                    article.get(
                        "category",
                        "Latest"
                    ),

                "title":
                    article.get(
                        "title",
                        ""
                    ),

                "normalizedTitle":
                    normalize(
                        article.get(
                            "title",
                            ""
                        )
                    ),

                "canonicalUrl":
                    article.get(
                        "canonicalUrl"
                    )
                    or article.get(
                        "link",
                        ""
                    ),

                "editorialSummary":
                    str(
                        editorial.get(
                            "editorialSummary",
                            ""
                        )
                    ).strip(),

                "brief": [

                    str(x).strip()

                    for x in editorial.get(
                        "brief",
                        []
                    )

                    if str(x).strip()

                ],

                "keyPoints": [

                    str(x).strip()

                    for x in editorial.get(
                        "keyPoints",
                        []
                    )

                    if str(x).strip()

                ],

                "editorialDate":
                    editorial_date,

                "editorialByline":
                    "The Hyderabad Daily "
                    "Digital Desk"
            }

            # Add to content

            content.setdefault(
                "stories",
                []
            ).insert(
                0,
                record
            )

            # Add to registry

            registry.setdefault(
                "publishedStories",
                []
            ).append({

                "id":
                    record["id"],

                "canonicalUrl":
                    record[
                        "canonicalUrl"
                    ],

                "normalizedTitle":
                    record[
                        "normalizedTitle"
                    ],

                "eventKey":
                    record["id"],

                "publishedAt":
                    datetime.now(
                        timezone.utc
                    ).isoformat()

            })

            added += 1

            # Small pause between requests

            if index < len(selected) - 1:

                time.sleep(8)

        except Exception as exc:

            print(
                "Editorial error:",
                exc
            )

    # --------------------------------------------------------
    # TIMESTAMP
    # --------------------------------------------------------

    timestamp = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    content[
        "lastUpdated"
    ] = timestamp

    registry[
        "lastUpdated"
    ] = timestamp

    # --------------------------------------------------------
    # PUBLICATION POLICY
    # --------------------------------------------------------

    content[
        "publicationPolicy"
    ] = {

        "requireEditorialContent":
            True,

        "requireApproval":
            True,

        "displayOnlyApprovedStories":
            True,

        "fallbackText":
            False,

        "fieldsRequired": [

            "editorialSummary",

            "brief",

            "keyPoints",

            "editorialDate",

            "editorialByline"

        ]
    }

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_json(
        CONTENT_FILE,
        content
    )

    save_json(
        REGISTRY_FILE,
        registry
    )

    print(
        "AIRA Digital News update "
        "complete. "
        f"Added {added} stories."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
