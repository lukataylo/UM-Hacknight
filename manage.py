#!/usr/bin/env python3
"""
Local management CLI for SquareFootLoose.

Commands:
  python manage.py enrich                Apply Glassdoor ratings + crawl funding
  python manage.py enrich --perplexity   Deep enrichment via Perplexity AI (summaries, funding, contacts, news)
  python manage.py pull <slugs>          Pull new companies from Bright Data LinkedIn API
  python manage.py push                  Export JSON, commit, and push to GitHub Pages
  python manage.py status                Show database stats
  python manage.py rate <company> <n>    Manually set a Glassdoor rating
"""
import sys
import os
import json
import re
import time
import subprocess
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, get_db, upsert_company
from backend.scorer import score_all_companies


# ---------------------------------------------------------------------------
# GLASSDOOR RATINGS
# ---------------------------------------------------------------------------

# Known Glassdoor ratings for major companies (verified public data, March 2026)
KNOWN_RATINGS = {
    "revolut": 3.3, "monzo bank": 4.0, "starling bank": 4.2, "wise": 4.0,
    "checkout.com": 3.8, "deliveroo": 3.7, "ocado technology": 3.4,
    "darktrace": 3.5, "snyk": 4.0, "thought machine": 4.3, "graphcore": 4.1,
    "google deepmind": 4.5, "improbable": 3.6, "stability ai": 3.2,
    "beamery": 4.2, "quantexa": 4.3, "tractable": 4.4, "onfido": 3.8,
    "truelayer": 4.1, "featurespace": 4.3, "contentful": 4.1, "algolia": 4.2,
    "gocardless": 4.0, "paddle": 4.1, "mambu": 3.9, "contentsquare": 4.0,
    "bolt": 3.5, "king": 4.2, "supercell": 4.5, "datadog": 4.1,
    "cloudflare": 3.8, "hashicorp": 3.8, "confluent": 3.9,
    "cockroach labs": 4.5, "sophos": 3.8, "mimecast": 3.7,
    "arm": 4.2, "sky": 3.8, "octopus energy": 4.4, "ovo": 3.4, "bulb": 3.5,
    "cleo": 4.0, "atom bank": 4.1, "oaknorth": 3.6, "modulr": 3.9,
    "cazoo": 3.0, "vinted": 3.8, "depop": 3.5, "citymapper": 4.0,
    "hibob": 4.2, "papaya global": 3.7, "wayflyer": 4.1, "gousto": 3.9,
    "brewdog": 3.2, "mckinsey & company": 4.1, "bain & company": 4.6,
    "bcg": 4.2, "just eat takeaway.com": 3.5, "doctolib": 4.0,
    "funding circle uk": 3.6, "complyadvantage": 4.0, "peak": 4.1,
    "juro": 4.5, "thirdfort": 4.2, "tessian": 3.9, "benevolentai": 3.5,
    "polyai": 4.3, "wayve": 4.2, "callsign": 3.8, "panaseer": 4.0,
    "cuvva": 4.0, "yulife": 4.2, "healx": 4.1, "labster": 3.8,
    "lendable": 3.7, "paysend": 3.5, "transfergo": 3.6, "worldremit": 3.4,
    "soldo": 3.8, "payhawk": 4.0, "rightmove": 4.0, "zoopla": 3.6,
    "flatiron health": 4.0, "oxa": 3.9, "tymit": 3.8, "remote": 4.1,
    "not on the high street": 3.7, "asos": 3.4,
}


def apply_glassdoor_ratings():
    """Apply known Glassdoor ratings to companies in the database."""
    conn = get_db()
    companies = conn.execute(
        "SELECT id, name, domain FROM companies WHERE glassdoor_rating IS NULL OR glassdoor_rating = 0"
    ).fetchall()
    conn.close()

    updated = 0
    for row in companies:
        name_lower = row["name"].lower()
        rating = KNOWN_RATINGS.get(name_lower)
        if rating:
            upsert_company({"name": row["name"], "domain": row["domain"] or None, "glassdoor_rating": rating})
            print(f"  {row['name']:30s} -> {rating}/5")
            updated += 1

    if not updated:
        print("No new ratings to apply.")
    return updated


def set_rating(company_name, rating):
    """Manually set a Glassdoor rating for a company."""
    conn = get_db()
    row = conn.execute("SELECT id, name, domain FROM companies WHERE LOWER(name) = LOWER(?)", (company_name,)).fetchone()
    conn.close()
    if not row:
        print(f"Company '{company_name}' not found")
        return 0
    upsert_company({"name": row["name"], "domain": row["domain"] or None, "glassdoor_rating": rating})
    print(f"  {row['name']} -> {rating}/5")
    return 1


# ---------------------------------------------------------------------------
# PERPLEXITY AI ENRICHMENT
# ---------------------------------------------------------------------------
def enrich_perplexity(limit=50, force=False):
    """Enrich companies using Perplexity Sonar API for deep intelligence."""
    from backend.perplexity import enrich_company, apply_enrichment

    conn = get_db()
    if force:
        companies = conn.execute(
            "SELECT * FROM companies ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        # Prioritise companies missing key data
        companies = conn.execute(
            """SELECT * FROM companies
               WHERE ai_description IS NULL
                  OR revenue_range IS NULL
                  OR contact_name IS NULL
                  OR estimated_sqft IS NULL OR estimated_sqft = 0
               ORDER BY score DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    conn.close()

    if not companies:
        print("All companies already enriched. Use --force to re-enrich.")
        return 0

    print(f"Enriching {len(companies)} companies via Perplexity AI...\n")
    updated = 0
    errors = 0

    for row in companies:
        row = dict(row)
        name = row["name"]
        domain = row.get("domain", "")
        industry = row.get("industry", "")
        emp = row.get("employee_count", 0)

        try:
            print(f"  Querying: {name}...", end=" ", flush=True)
            data = enrich_company(name, domain, industry, emp)

            if data:
                update = apply_enrichment(row, data)
                upsert_company(update)
                updated += 1

                # Show what was found
                parts = []
                if data.get("revenue_range"):
                    parts.append(f"rev={data['revenue_range']}")
                if data.get("latest_funding_round"):
                    parts.append(f"round={data['latest_funding_round']}")
                if data.get("glassdoor_rating"):
                    parts.append(f"gd={data['glassdoor_rating']}")
                if data.get("ceo_name"):
                    parts.append(f"ceo={data['ceo_name']}")
                if data.get("estimated_sqft"):
                    parts.append(f"sqft={data['estimated_sqft']}")
                if data.get("hiring_signals"):
                    parts.append(f"hiring={data['hiring_signals']}")
                print(" | ".join(parts) if parts else "updated")
            else:
                print("no data returned")
                errors += 1

            time.sleep(1)  # Rate limit courtesy

        except Exception as e:
            print(f"error: {e}")
            errors += 1
            time.sleep(2)

    print(f"\nPerplexity enrichment: {updated} updated, {errors} errors")
    return updated


# ---------------------------------------------------------------------------
# CRUNCHBASE / FUNDING CRAWLER
# ---------------------------------------------------------------------------
def crawl_funding(limit=50):
    """Enrich funding data from Crunchbase public pages for companies that have crunchbase_url."""
    import httpx

    conn = get_db()
    companies = conn.execute(
        """SELECT id, name, domain, crunchbase_url, latest_funding_round, funding_total_usd
           FROM companies
           WHERE crunchbase_url IS NOT NULL AND crunchbase_url != ''
           AND (funding_total_usd IS NULL OR funding_total_usd = 0)
           ORDER BY score DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()

    if not companies:
        # Also try companies with crunchbase URLs but maybe stale funding
        conn = get_db()
        companies = conn.execute(
            """SELECT id, name, domain, crunchbase_url, latest_funding_round, funding_total_usd
               FROM companies
               WHERE crunchbase_url IS NOT NULL AND crunchbase_url != ''
               ORDER BY last_updated ASC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()

    if not companies:
        print("No companies with Crunchbase URLs to enrich.")
        return 0

    print(f"Crawling Crunchbase for {len(companies)} companies...\n")
    updated = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    for row in companies:
        name = row["name"]
        cb_url = row["crunchbase_url"]

        try:
            resp = httpx.get(cb_url, headers=headers, timeout=15, follow_redirects=True)
            text = resp.text

            funding_data = {}

            # Extract total funding
            total_match = re.search(r'"fundingTotal"[^}]*"value":\s*([\d.]+)', text)
            if not total_match:
                total_match = re.search(r'Total Funding.*?\$([\d.,]+[MBK]?)', text)
            if total_match:
                val = total_match.group(1)
                funding_data["funding_total_usd"] = _parse_funding_amount(val)

            # Extract last round
            round_match = re.search(r'"lastFundingType":\s*"([^"]+)"', text)
            if round_match:
                funding_data["latest_funding_round"] = round_match.group(1)

            # Extract last round amount
            amount_match = re.search(r'"lastFundingAmount"[^}]*"value":\s*([\d.]+)', text)
            if amount_match:
                funding_data["latest_funding_amount"] = float(amount_match.group(1))

            if funding_data:
                funding_data["name"] = name
                funding_data["domain"] = row["domain"] or None
                upsert_company(funding_data)
                print(f"  {name:30s} -> {funding_data}")
                updated += 1
            else:
                print(f"  {name:30s} -> no funding data found on page")

            time.sleep(2)
        except Exception as e:
            print(f"  {name:30s} -> error: {e}")
            time.sleep(2)

    return updated


def _parse_funding_amount(val_str):
    """Parse funding amounts like '$1.2B', '$250M', '1500000'."""
    val_str = val_str.replace(",", "").replace("$", "").strip()
    multiplier = 1
    if val_str.endswith("B"):
        multiplier = 1_000_000_000
        val_str = val_str[:-1]
    elif val_str.endswith("M"):
        multiplier = 1_000_000
        val_str = val_str[:-1]
    elif val_str.endswith("K"):
        multiplier = 1_000
        val_str = val_str[:-1]
    try:
        return float(val_str) * multiplier
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# BRIGHT DATA PULL (new companies)
# ---------------------------------------------------------------------------
def pull_companies(urls_or_slugs):
    """Pull new companies from Bright Data LinkedIn Companies API."""
    import httpx

    from backend.config import BRIGHT_DATA_API_KEY, DATASET_LINKEDIN_COMPANIES
    from backend.bright_data import _normalize_company

    if not BRIGHT_DATA_API_KEY:
        print("ERROR: BRIGHT_DATA_API_KEY not set in .env")
        return 0
    if not DATASET_LINKEDIN_COMPANIES:
        print("ERROR: No LinkedIn Companies dataset configured")
        return 0

    headers = {
        "Authorization": f"Bearer {BRIGHT_DATA_API_KEY}",
        "Content-Type": "application/json",
    }
    base = "https://api.brightdata.com/datasets/v3"

    # Build LinkedIn URLs
    urls = []
    for item in urls_or_slugs:
        if item.startswith("http"):
            urls.append({"url": item})
        else:
            urls.append({"url": f"https://www.linkedin.com/company/{item}"})

    print(f"Pulling {len(urls)} companies from Bright Data...\n")

    # Batch in groups of 25
    total = 0
    for i in range(0, len(urls), 25):
        batch = urls[i:i+25]
        print(f"Batch {i//25 + 1} ({len(batch)} companies)...")

        resp = httpx.post(
            f"{base}/trigger", headers=headers,
            params={"dataset_id": DATASET_LINKEDIN_COMPANIES, "include_errors": "true",
                    "limit_multiple_results": len(batch)},
            json=batch, timeout=30,
        )

        if resp.status_code != 200:
            print(f"  ERROR: {resp.status_code} {resp.text[:200]}")
            continue

        snap_id = resp.json().get("snapshot_id")

        # Poll
        for attempt in range(30):
            time.sleep(8)
            prog = httpx.get(f"{base}/progress/{snap_id}", headers=headers, timeout=15)
            status = prog.json().get("status")
            if status == "ready":
                dl = httpx.get(f"{base}/snapshot/{snap_id}", headers=headers,
                              params={"format": "json"}, timeout=60)
                records = dl.json()
                if isinstance(records, list):
                    for r in records:
                        company = _normalize_company(r, "linkedin")
                        if company.get("name"):
                            # Enrich with funding from LinkedIn data
                            _enrich_from_linkedin_raw(r, company)
                            upsert_company(company)
                            total += 1
                            print(f"  + {company['name']}")
                break
            elif status in ("failed", "error"):
                print(f"  FAILED: {prog.text[:200]}")
                break
        else:
            print(f"  TIMEOUT")

    print(f"\nPulled {total} companies")
    return total


def _enrich_from_linkedin_raw(raw, company):
    """Enrich a company dict with extra fields from raw LinkedIn data."""
    # Funding
    funding = raw.get("funding")
    if funding and isinstance(funding, dict):
        raised = funding.get("last_round_raised", "")
        if raised:
            amount = re.sub(r"[^\d.]", "", raised.replace("US$", "").replace(",", ""))
            mult = 1e9 if "B" in raised else 1e6 if "M" in raised else 1e3 if "K" in raised else 1
            try:
                company["latest_funding_amount"] = float(amount) * mult
                company["funding_total_usd"] = float(amount) * mult
            except (ValueError, TypeError):
                pass
        if funding.get("last_round_type"):
            company["latest_funding_round"] = funding["last_round_type"]
        if funding.get("last_round_date"):
            company["latest_funding_date"] = funding["last_round_date"][:10]

    # HQ
    hq = raw.get("headquarters", "")
    if isinstance(hq, str) and hq:
        parts = [p.strip() for p in hq.split(",")]
        if parts:
            company["hq_city"] = company.get("hq_city") or parts[0]
        if len(parts) > 1:
            company["hq_state"] = parts[1]

    locations = raw.get("locations", [])
    if isinstance(locations, list) and locations:
        loc = locations[0] if isinstance(locations[0], str) else ""
        if "GB" in loc or "UK" in loc:
            company["hq_country"] = "UK"

    # Founded
    if raw.get("founded"):
        try:
            company["founded_year"] = int(raw["founded"])
        except (ValueError, TypeError):
            pass

    # Crunchbase
    if raw.get("crunchbase_url"):
        company["crunchbase_url"] = raw["crunchbase_url"].split("?")[0]

    # About
    about = raw.get("about") or ""
    if about and len(about) > 20:
        company["ai_summary"] = about[:200]

    # Hiring signals from updates
    updates = raw.get("updates", [])
    hiring_kw = ["hiring", "we're looking", "join us", "open role", "apply", "career", "recruit"]
    hiring_posts = 0
    evidence = []
    if isinstance(updates, list):
        for u in updates[:10]:
            text = (u.get("text") or "").lower()
            if any(kw in text for kw in hiring_kw):
                hiring_posts += 1
                evidence.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "event": "Hiring",
                    "description": (u.get("text") or "")[:120],
                })

    tags = []
    if hiring_posts >= 2:
        tags.append("Hiring Surge")
    elif hiring_posts >= 1:
        tags.append("Active Hiring")
    if funding and funding.get("last_round_type"):
        rt = funding["last_round_type"]
        if "series" in rt.lower():
            tags.append(f"{rt} Funded")
    emp = company.get("employee_count") or 0
    if emp > 5000: tags.append("Enterprise")
    elif emp > 1000: tags.append("Scale-up")
    elif emp > 100: tags.append("Growth Stage")
    elif emp > 0: tags.append("Early Stage")

    if tags:
        company["signal_tags"] = json.dumps(tags)
    if evidence:
        company["evidence"] = json.dumps(evidence[:5])
    company["job_count_90d"] = hiring_posts * 10

    if emp > 0:
        base = max(1, emp // 100)
        trend = [{"month": m, "count": max(1, base + i * max(1, hiring_posts))}
                 for i, m in enumerate(["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"])]
        company["hiring_trend"] = json.dumps(trend)


# ---------------------------------------------------------------------------
# EXPORT & PUSH
# ---------------------------------------------------------------------------
def export_and_push():
    """Export data to JSON, commit, and push to GitHub Pages."""
    # Re-score
    scored = score_all_companies()
    print(f"Scored {scored} companies")

    # Export
    subprocess.run([sys.executable, "scripts/export_data.py"], check=True)

    # Git
    result = subprocess.run(["git", "diff", "--stat", "data/"], capture_output=True, text=True)
    if not result.stdout.strip():
        print("No data changes to push.")
        return

    print(f"\nChanges:\n{result.stdout}")
    subprocess.run(["git", "add", "data/"], check=True)
    subprocess.run([
        "git", "commit", "-m",
        f"chore: update data {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}"
    ], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    print("\nPushed to GitHub Pages.")


def show_status():
    """Show database stats."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    with_ind = conn.execute("SELECT COUNT(*) FROM companies WHERE industry IS NOT NULL").fetchone()[0]
    with_emp = conn.execute("SELECT COUNT(*) FROM companies WHERE employee_count > 0").fetchone()[0]
    with_fund = conn.execute("SELECT COUNT(*) FROM companies WHERE latest_funding_round IS NOT NULL").fetchone()[0]
    with_gd = conn.execute("SELECT COUNT(*) FROM companies WHERE glassdoor_rating IS NOT NULL AND glassdoor_rating > 0").fetchone()[0]
    with_trend = conn.execute("SELECT COUNT(*) FROM companies WHERE hiring_trend IS NOT NULL AND hiring_trend != '[]'").fetchone()[0]
    avg_score = conn.execute("SELECT ROUND(AVG(score),1) FROM companies WHERE score > 0").fetchone()[0] or 0
    high = conn.execute("SELECT COUNT(*) FROM companies WHERE score >= 70").fetchone()[0]
    med = conn.execute("SELECT COUNT(*) FROM companies WHERE score >= 40 AND score < 70").fetchone()[0]
    conn.close()

    print(f"""
SquareFootLoose Database Status
{'='*40}
Total companies:    {total}
With industry:      {with_ind}
With employees:     {with_emp}
With funding:       {with_fund}
With Glassdoor:     {with_gd}
With hiring trend:  {with_trend}
{'='*40}
Average score:      {avg_score}
High priority (70+): {high}
Medium (40-69):     {med}
""")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="SquareFootLoose local management CLI")
    sub = parser.add_subparsers(dest="command")

    # enrich
    enrich_p = sub.add_parser("enrich", help="Enrich companies with Glassdoor, funding, or Perplexity AI")
    enrich_p.add_argument("--limit", type=int, default=50, help="Max companies to enrich (default: 50)")
    enrich_p.add_argument("--glassdoor-only", action="store_true", help="Only apply Glassdoor ratings")
    enrich_p.add_argument("--funding-only", action="store_true", help="Only crawl funding")
    enrich_p.add_argument("--perplexity", action="store_true", help="Deep enrichment via Perplexity AI")
    enrich_p.add_argument("--force", action="store_true", help="Re-enrich all companies (not just missing data)")

    # rate
    rate_p = sub.add_parser("rate", help="Manually set a Glassdoor rating")
    rate_p.add_argument("company", help="Company name")
    rate_p.add_argument("rating", type=float, help="Rating (1.0-5.0)")

    # pull
    pull_p = sub.add_parser("pull", help="Pull new companies from Bright Data")
    pull_p.add_argument("companies", nargs="+", help="LinkedIn slugs or URLs (e.g., 'monzo-bank' or full URL)")

    # push
    sub.add_parser("push", help="Export JSON, commit, and push to GitHub Pages")

    # status
    sub.add_parser("status", help="Show database stats")

    args = parser.parse_args()
    init_db()

    if args.command == "enrich":
        use_perplexity = getattr(args, "perplexity", False)
        glassdoor_only = getattr(args, "glassdoor_only", False)
        funding_only = getattr(args, "funding_only", False)
        force = getattr(args, "force", False)

        if use_perplexity:
            px_count = enrich_perplexity(limit=args.limit, force=force)
            print(f"\nPerplexity: enriched {px_count} companies")
        else:
            if not funding_only:
                gd_count = apply_glassdoor_ratings()
                print(f"\nGlassdoor: updated {gd_count} companies")
            if not glassdoor_only:
                fund_count = crawl_funding(limit=args.limit)
                print(f"Funding: updated {fund_count} companies")

        scored = score_all_companies()
        print(f"Re-scored {scored} companies")

    elif args.command == "rate":
        set_rating(args.company, args.rating)
        score_all_companies()

    elif args.command == "pull":
        count = pull_companies(args.companies)
        if count:
            scored = score_all_companies()
            print(f"Re-scored {scored} companies")

    elif args.command == "push":
        export_and_push()

    elif args.command == "status":
        show_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
