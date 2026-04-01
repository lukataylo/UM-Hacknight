"""Perplexity Sonar API integration for company intelligence enrichment."""
import json
import re
import logging
import time
import httpx
from backend.config import PERPLEXITY_API_KEY

logger = logging.getLogger(__name__)

API_URL = "https://api.perplexity.ai/chat/completions"
MODEL = "sonar"


def _query(prompt: str, system: str = "") -> str | None:
    """Send a query to Perplexity Sonar and return the text response."""
    if not PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = httpx.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


SYSTEM_PROMPT = """You are a CRE (commercial real estate) sales intelligence analyst.
Return ONLY valid JSON with no markdown, no backticks, no explanation.
If you don't know a value, use null. All monetary values in USD."""

QUERY_TEMPLATE = """Research the company "{name}" (website: {domain}) headquartered in London, UK.

Return this exact JSON structure:
{{
  "summary": "One paragraph (2-3 sentences) intelligence summary covering what the company does, its market position, and current trajectory. Write for a commercial real estate sales team looking to lease office space.",
  "valuation_usd": null or number (latest known valuation in USD),
  "revenue_estimate_usd": null or number (latest annual revenue estimate in USD),
  "revenue_range": null or string like "$10M-$50M",
  "latest_funding_round": null or string like "Series C",
  "latest_funding_amount_usd": null or number,
  "latest_funding_date": null or string "YYYY-MM-DD",
  "total_funding_usd": null or number,
  "ceo_name": null or string,
  "ceo_email_guess": null or string (first.last@{domain} format),
  "cro_or_head_of_re": null or string (name of CRO, Head of Real Estate, VP Workplace, or similar),
  "cro_email_guess": null or string,
  "glassdoor_rating": null or number (1.0-5.0),
  "estimated_headcount": null or number,
  "office_locations": null or string (London office address or area if known),
  "estimated_sqft": null or number (estimated London office size in square feet),
  "recent_news": [
    {{"date": "YYYY-MM-DD", "event": "string", "description": "string"}}
  ],
  "hiring_signals": null or string ("aggressive hiring", "steady growth", "layoffs", "stable"),
  "signal_tags": ["tag1", "tag2"]
}}"""


def enrich_company(name: str, domain: str, industry: str = "", employee_count: int = 0) -> dict | None:
    """Query Perplexity for comprehensive company intelligence. Returns parsed dict or None."""
    prompt = QUERY_TEMPLATE.format(name=name, domain=domain or "unknown")

    try:
        raw = _query(prompt, system=SYSTEM_PROMPT)
        if not raw:
            return None

        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Perplexity response for {name}: {e}")
        logger.debug(f"Raw response: {raw[:500]}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"Perplexity API error for {name}: {e.response.status_code} {e.response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Perplexity error for {name}: {e}")
        return None


def apply_enrichment(company_row: dict, perplexity_data: dict) -> dict:
    """Merge Perplexity data into a company update dict for upsert."""
    p = perplexity_data
    update = {"name": company_row["name"], "domain": company_row.get("domain")}

    # Summary
    if p.get("summary"):
        update["ai_summary"] = p["summary"][:300]
        update["ai_description"] = p["summary"]

    # Funding (only update if Perplexity has newer/better data)
    if p.get("latest_funding_round"):
        update["latest_funding_round"] = p["latest_funding_round"]
    if p.get("latest_funding_amount_usd"):
        update["latest_funding_amount"] = p["latest_funding_amount_usd"]
    if p.get("latest_funding_date"):
        update["latest_funding_date"] = p["latest_funding_date"]
    if p.get("total_funding_usd"):
        update["funding_total_usd"] = p["total_funding_usd"]

    # Revenue
    if p.get("revenue_range"):
        update["revenue_range"] = p["revenue_range"]

    # Glassdoor
    if p.get("glassdoor_rating") and isinstance(p["glassdoor_rating"], (int, float)):
        if 1.0 <= p["glassdoor_rating"] <= 5.0:
            update["glassdoor_rating"] = round(p["glassdoor_rating"], 1)

    # Office size estimate
    if p.get("estimated_sqft") and isinstance(p["estimated_sqft"], (int, float)):
        update["estimated_sqft"] = int(p["estimated_sqft"])

    # Contacts — prefer CRO/Head of Real Estate, fall back to CEO
    contact_name = p.get("cro_or_head_of_re") or p.get("ceo_name")
    contact_email = p.get("cro_email_guess") or p.get("ceo_email_guess")
    if contact_name:
        update["contact_name"] = contact_name
        title = "Head of Workplace" if p.get("cro_or_head_of_re") else "CEO"
        update["contact_title"] = title
    if contact_email:
        update["contact_email"] = contact_email

    # Recent news → evidence
    news = p.get("recent_news")
    if news and isinstance(news, list):
        evidence = []
        for n in news[:5]:
            if isinstance(n, dict) and n.get("description"):
                evidence.append({
                    "date": n.get("date", ""),
                    "event": n.get("event", "News"),
                    "description": n["description"][:150],
                })
        if evidence:
            update["evidence"] = json.dumps(evidence)

    # Signal tags
    tags = p.get("signal_tags")
    if tags and isinstance(tags, list):
        update["signal_tags"] = json.dumps(tags[:5])

    # Hiring signals → job_count_90d estimate
    hiring = (p.get("hiring_signals") or "").lower()
    if "aggressive" in hiring or "surge" in hiring:
        update["job_count_90d"] = max(company_row.get("job_count_90d", 0), 30)
    elif "steady" in hiring or "growth" in hiring:
        update["job_count_90d"] = max(company_row.get("job_count_90d", 0), 15)
    elif "layoff" in hiring or "cutting" in hiring:
        update["job_count_90d"] = 0

    return update
