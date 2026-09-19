const SYSTEM = `
You are AIRA (Artificial Intelligence Response Agent),
the editorial operations assistant for The Hyderabad Daily.

Help manage the newspaper workflow.

Rules:

- Be factual and transparent about uncertainty.
- Never invent news, quotations, sources, dates, images or publication status.
- Do not publish or modify newspaper content unless the user explicitly asks.
- Prevent duplicate or substantially repeated stories.
- Respect the established Page 1-10 editorial structure.
- Keep article summaries original and concise.
- Do not copy source articles.
- Keep masthead, date/day, navigation, mobile presentation and branding consistent.
- Treat GitHub main as the newspaper source of truth.
- For political news, provide neutral factual descriptions and do not recommend political choices.
`;

export default async function handler(req, res) {

  if (req.method !== "POST") {
    return res.status(405).json({
      error: "Method not allowed"
    });
  }

  const key = process.env.AI_GATEWAY_API_KEY;

  if (!key) {
    return res.status(503).json({
      error:
        "AIRA AI is not connected yet. Add AI_GATEWAY_API_KEY in Vercel Project Settings → Environment Variables."
    });
  }

  try {

    const body =
      typeof req.body === "string"
        ? JSON.parse(req.body)
        : (req.body || {});

    const message =
      String(body.message || "").trim();

    if (!message) {
      return res.status(400).json({
        error: "Message is required."
      });
    }

    const response = await fetch(
      "https://ai-gateway.vercel.sh/v1/chat/completions",
      {
        method: "POST",

        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${key}`
        },

        body: JSON.stringify({

          model: "openai/gpt-5.6-luna",

          messages: [
            {
              role: "system",
              content: SYSTEM
            },
            {
              role: "user",
              content: message
            }
          ],

          max_tokens: 1200

        })
      }
    );

    const data = await response.json();

    if (!response.ok) {

      return res.status(response.status).json({
        error:
          data?.error?.message ||
          "AI Gateway request failed."
      });

    }

    return res.status(200).json({

      reply:
        data?.choices?.[0]?.message?.content ||
        "No response returned."

    });

  } catch (error) {

    return res.status(500).json({
      error: "AIRA backend error."
    });

  }

}
