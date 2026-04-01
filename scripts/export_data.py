"""Export SQLite data to static JSON files for GitHub Pages deployment."""
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_db, get_db


def export_companies(output_path: str):
    """Export all companies as a JSON array."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM companies ORDER BY score DESC").fetchall()
    conn.close()

    companies = []
    for r in rows:
        c = dict(r)
        # Pre-parse JSON string fields
        for field in ("signal_tags", "hiring_trend", "evidence"):
            if isinstance(c.get(field), str):
                try:
                    c[field] = json.loads(c[field])
                except (json.JSONDecodeError, TypeError):
                    c[field] = []
        if isinstance(c.get("score_breakdown"), str):
            try:
                c["score_breakdown"] = json.loads(c["score_breakdown"])
            except (json.JSONDecodeError, TypeError):
                c["score_breakdown"] = {}
        companies.append(c)

    with open(output_path, "w") as f:
        json.dump(companies, f)

    return len(companies)


def export_meta(output_path: str, company_count: int):
    """Export metadata JSON."""
    conn = get_db()
    job_count = conn.execute("SELECT COUNT(*) FROM job_listings").fetchone()[0]
    conn.close()

    meta = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "company_count": company_count,
        "job_count": job_count,
    }

    with open(output_path, "w") as f:
        json.dump(meta, f)


if __name__ == "__main__":
    init_db()

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)

    count = export_companies(os.path.join(data_dir, "companies.json"))
    print(f"Exported {count} companies to data/companies.json")

    export_meta(os.path.join(data_dir, "meta.json"), count)
    print("Exported data/meta.json")
