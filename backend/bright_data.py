import httpx
import asyncio
import json
import logging
import random
from datetime import datetime
from backend.config import (
    BRIGHT_DATA_API_KEY, TARGET_MARKETS,
    DATASET_LINKEDIN_JOBS, DATASET_INDEED_JOBS,
    DATASET_CRUNCHBASE, DATASET_LINKEDIN_COMPANIES,
    DATASET_ZOOMINFO, DATASET_GLASSDOOR,
)
from backend import database as db

logger = logging.getLogger(__name__)

BASE_URL = "https://api.brightdata.com/datasets/v3"
HEADERS = {
    "Authorization": f"Bearer {BRIGHT_DATA_API_KEY}",
    "Content-Type": "application/json",
}

POLL_INTERVAL = 15
POLL_TIMEOUT = 600


async def trigger_snapshot(dataset_id: str, records_limit: int = 100, filters: list = None) -> str:
    """Trigger a dataset collection and return the snapshot_id."""
    url = f"{BASE_URL}/trigger"
    params = {"dataset_id": dataset_id, "include_errors": "true"}
    if records_limit:
        params["limit_multiple_results"] = records_limit

    body = filters if filters else []

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=HEADERS, params=params, json=body)
        resp.raise_for_status()
        data = resp.json()
        snapshot_id = data.get("snapshot_id")
        if not snapshot_id:
            raise ValueError(f"No snapshot_id in response: {data}")
        logger.info(f"Triggered snapshot {snapshot_id} for dataset {dataset_id}")
        return snapshot_id


async def poll_snapshot(snapshot_id: str) -> dict:
    """Check the status of a snapshot."""
    url = f"{BASE_URL}/progress/{snapshot_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()


async def wait_for_snapshot(snapshot_id: str) -> str:
    """Poll until snapshot is ready or failed. Returns final status."""
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        status_data = await poll_snapshot(snapshot_id)
        status = status_data.get("status")
        logger.info(f"Snapshot {snapshot_id}: {status}")

        if status == "ready":
            return "ready"
        if status in ("failed", "error"):
            raise RuntimeError(f"Snapshot {snapshot_id} failed: {status_data}")

        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Snapshot {snapshot_id} timed out after {POLL_TIMEOUT}s")


async def download_snapshot(snapshot_id: str) -> list:
    """Download completed snapshot data as JSON."""
    url = f"{BASE_URL}/snapshot/{snapshot_id}"
    params = {"format": "json"}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return [data]


async def collect_dataset(dataset_id: str, records_limit: int = 100, filters: list = None) -> list:
    """Full pipeline: trigger -> wait -> download."""
    snapshot_id = await trigger_snapshot(dataset_id, records_limit, filters)
    await wait_for_snapshot(snapshot_id)
    records = await download_snapshot(snapshot_id)
    logger.info(f"Downloaded {len(records)} records from dataset {dataset_id}")
    return records


def _is_hybrid_or_office(job: dict) -> tuple:
    """Determine if a job is hybrid or office-based from the raw data."""
    text = json.dumps(job).lower()
    hybrid_keywords = ["hybrid", "in-office", "on-site", "onsite", "3 days in office", "2 days remote"]
    office_keywords = ["office", "in-person", "on site", "headquarters"]

    is_hybrid = any(kw in text for kw in hybrid_keywords)
    is_office = any(kw in text for kw in office_keywords)
    return is_hybrid, is_office


def _extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ["https://", "http://", "www."]:
        url = url.removeprefix(prefix)
    return url.split("/")[0].split("?")[0]


DISCOVERY_KEYWORDS = [
    "startup", "hiring", "hybrid office", "series A", "series B", "series C",
    "funded", "fintech", "AI", "machine learning", "SaaS", "cybersecurity",
    "healthtech", "proptech", "edtech", "cleantech", "devops", "cloud",
    "data engineer", "software engineer", "product manager", "expansion",
    "new office", "growing team", "scale-up", "opening office",
    "head of", "VP", "country manager", "EMEA", "engineering manager",
    "regtech", "insurtech", "legaltech", "deeptech", "robotics",
    "infrastructure", "payments", "blockchain", "biotech", "medtech",
]


def _name_to_linkedin_url(name: str) -> str:
    """Convert a company name to a best-guess LinkedIn company URL."""
    slug = name.lower().strip().replace(" ", "-").replace(".", "").replace(",", "")
    slug = slug.replace("&", "and").replace("'", "")
    return f"https://www.linkedin.com/company/{slug}"


async def collect_job_listings(records_limit: int = 200) -> int:
    """Collect job listings from Indeed (the active job dataset)."""
    total_inserted = 0

    if not DATASET_INDEED_JOBS:
        logger.warning("No job listing dataset configured")
        return 0

    # Vary keywords each run to discover new companies
    keywords = random.sample(DISCOVERY_KEYWORDS, min(4, len(DISCOVERY_KEYWORDS)))
    markets = random.sample(TARGET_MARKETS, min(3, len(TARGET_MARKETS)))

    try:
        filters = [{"url": f"https://www.indeed.com/jobs?q={kw}&l={market}"}
                    for kw in keywords for market in markets]
        records = await collect_dataset(DATASET_INDEED_JOBS, records_limit=records_limit, filters=filters[:10])

        normalized = []
        for r in records:
            is_hybrid, is_office = _is_hybrid_or_office(r)
            normalized.append({
                "company_name": r.get("company_name") or r.get("company") or r.get("employer") or "",
                "company_domain": _extract_domain(r.get("company_url") or r.get("company_link") or ""),
                "title": r.get("title") or r.get("job_title") or "",
                "location": r.get("location") or r.get("job_location") or "",
                "job_type": r.get("job_type") or r.get("employment_type") or "",
                "date_posted": r.get("date_posted") or r.get("post_date") or datetime.now().isoformat(),
                "source": "indeed",
                "is_hybrid": 1 if is_hybrid else 0,
                "is_office": 1 if is_office else 0,
                "raw_data": json.dumps(r),
            })

        inserted = db.bulk_insert_jobs(normalized)
        total_inserted += inserted

        # Create company rows for new companies
        seen = set()
        for job in normalized:
            name = job.get("company_name", "")
            if name and name not in seen:
                seen.add(name)
                db.upsert_company({"name": name, "domain": job.get("company_domain") or None})

        logger.info(f"Collected {len(normalized)} indeed listings, {inserted} new")
    except Exception as e:
        logger.error(f"Error collecting indeed jobs: {e}")

    return total_inserted


async def collect_company_intelligence(records_limit: int = 100) -> int:
    """Enrich companies via LinkedIn Companies dataset (requires LinkedIn URLs)."""
    if not DATASET_LINKEDIN_COMPANIES:
        logger.warning("No LinkedIn Companies dataset configured")
        return 0

    total_upserted = 0

    # Find companies missing data (no industry or employee count)
    conn = db.get_db()
    sparse = conn.execute(
        "SELECT name, linkedin_url FROM companies WHERE industry IS NULL OR employee_count IS NULL ORDER BY last_updated ASC LIMIT 30"
    ).fetchall()
    conn.close()

    # Build LinkedIn URLs — use stored URL if available, otherwise guess from name
    urls = []
    for row in sparse:
        url = row["linkedin_url"] if row["linkedin_url"] else _name_to_linkedin_url(row["name"])
        urls.append({"url": url})

    if not urls:
        logger.info("All companies already enriched")
        return 0

    try:
        records = await collect_dataset(DATASET_LINKEDIN_COMPANIES, records_limit=len(urls), filters=urls)

        for r in records:
            company_data = _normalize_company(r, "linkedin")
            if company_data.get("name"):
                db.upsert_company(company_data)
                total_upserted += 1

        logger.info(f"Enriched {total_upserted} companies from LinkedIn")
    except Exception as e:
        logger.error(f"Error enriching from LinkedIn: {e}")

    return total_upserted


def _normalize_company(record: dict, source: str) -> dict:
    """Normalize company data from different sources into a common schema."""
    data = {}

    if source == "crunchbase":
        data = {
            "name": record.get("name") or record.get("company_name") or "",
            "domain": _extract_domain(record.get("website") or record.get("homepage_url") or ""),
            "industry": record.get("industry") or record.get("category") or record.get("industries") or "",
            "hq_city": record.get("city") or record.get("hq_city") or "",
            "hq_state": record.get("state") or record.get("hq_state") or record.get("region") or "",
            "hq_country": record.get("country") or record.get("hq_country") or "US",
            "employee_count": _parse_int(record.get("number_of_employees") or record.get("employee_count")),
            "founded_year": _parse_int(record.get("founded_year") or record.get("founded")),
            "funding_total_usd": _parse_float(record.get("total_funding") or record.get("funding_total_usd")),
            "latest_funding_round": record.get("last_funding_type") or record.get("latest_funding_round") or "",
            "latest_funding_date": record.get("last_funding_date") or record.get("latest_funding_date") or "",
            "latest_funding_amount": _parse_float(record.get("last_funding_amount")),
            "crunchbase_url": record.get("url") or record.get("crunchbase_url") or "",
            "website": record.get("website") or record.get("homepage_url") or "",
            "description": record.get("description") or record.get("short_description") or "",
        }
    elif source == "linkedin":
        industries = record.get("industries") or record.get("industry") or ""
        if isinstance(industries, list):
            industries = ", ".join(industries[:3])
        locations = record.get("locations") or []
        hq_city = ""
        hq_state = ""
        if isinstance(locations, list) and locations:
            loc = locations[0] if isinstance(locations[0], str) else ""
            parts = [p.strip() for p in loc.split(",")]
            if len(parts) >= 2:
                hq_city = parts[-3] if len(parts) >= 3 else parts[0]
                hq_state = parts[-2] if len(parts) >= 3 else parts[-1]
        data = {
            "name": record.get("name") or record.get("company_name") or "",
            "domain": _extract_domain(record.get("website") or ""),
            "industry": industries,
            "hq_city": record.get("city") or hq_city,
            "hq_state": record.get("state") or hq_state,
            "employee_count": _parse_int(record.get("employees_in_linkedin") or record.get("company_size") or record.get("employee_count")),
            "linkedin_url": f"https://www.linkedin.com/company/{record.get('id', '')}" if record.get("id") else record.get("url", ""),
            "website": record.get("website") or "",
            "description": record.get("about") or record.get("description") or "",
        }
    elif source == "zoominfo":
        data = {
            "name": record.get("company_name") or record.get("name") or "",
            "domain": _extract_domain(record.get("website") or ""),
            "employee_count": _parse_int(record.get("employee_count") or record.get("employees")),
            "revenue_range": record.get("revenue") or record.get("revenue_range") or "",
            "contact_name": record.get("contact_name") or "",
            "contact_title": record.get("contact_title") or "",
            "contact_email": record.get("contact_email") or record.get("email") or "",
            "contact_phone": record.get("contact_phone") or record.get("phone") or "",
        }
    elif source == "glassdoor":
        data = {
            "name": record.get("company_name") or record.get("name") or "",
            "glassdoor_rating": _parse_float(record.get("overall_rating") or record.get("rating")),
        }

    if isinstance(data.get("industry"), list):
        data["industry"] = ", ".join(data["industry"][:3])

    return {k: v for k, v in data.items() if v is not None and v != ""}


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace("+", "").strip()
            if "-" in val:
                parts = val.split("-")
                return int(parts[-1])
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = val.replace(",", "").replace("$", "").replace("M", "000000").replace("B", "000000000").strip()
        return float(val)
    except (ValueError, TypeError):
        return None


async def run_full_pipeline(run_id: int):
    """Execute the complete data collection pipeline."""
    try:
        logger.info(f"Pipeline run {run_id} started")
        db.update_pipeline_run(run_id, status="collecting_jobs")

        # Step 1: Collect job listings
        jobs_count = await collect_job_listings(records_limit=200)
        logger.info(f"Collected {jobs_count} job listings")

        # Step 2: Collect company intelligence
        db.update_pipeline_run(run_id, status="collecting_companies")
        companies_count = await collect_company_intelligence(records_limit=100)
        logger.info(f"Processed {companies_count} companies")

        # Step 3: Update job counts
        db.update_pipeline_run(run_id, status="scoring")
        conn = db.get_db()
        all_companies = conn.execute("SELECT id, name FROM companies").fetchall()
        conn.close()
        for company in all_companies:
            job_count = db.get_job_count_for_company(company["name"])
            conn = db.get_db()
            conn.execute("UPDATE companies SET job_count_90d = ? WHERE id = ?", (job_count, company["id"]))
            conn.commit()
            conn.close()

        # Step 4: Score all companies
        from backend.scorer import score_all_companies
        scored = score_all_companies()

        db.update_pipeline_run(
            run_id,
            status="completed",
            completed_at=datetime.now().isoformat(),
            records_collected=jobs_count + companies_count,
            companies_scored=scored,
        )
        logger.info(f"Pipeline run {run_id} completed. Scored {scored} companies.")

    except Exception as e:
        logger.error(f"Pipeline run {run_id} failed: {e}")
        db.update_pipeline_run(
            run_id,
            status="failed",
            completed_at=datetime.now().isoformat(),
            error=str(e),
        )
