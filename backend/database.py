import sqlite3
import json
from datetime import datetime
from backend.config import DATABASE_PATH


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            domain TEXT,
            industry TEXT,
            hq_city TEXT,
            hq_state TEXT,
            hq_country TEXT DEFAULT 'US',
            employee_count INTEGER,
            founded_year INTEGER,
            funding_total_usd REAL,
            latest_funding_round TEXT,
            latest_funding_date TEXT,
            latest_funding_amount REAL,
            revenue_range TEXT,
            glassdoor_rating REAL,
            linkedin_url TEXT,
            crunchbase_url TEXT,
            website TEXT,
            description TEXT,
            contact_name TEXT,
            contact_title TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            submarket TEXT,
            hybrid_percentage INTEGER DEFAULT 0,
            signal_tags TEXT DEFAULT '[]',
            ai_summary TEXT,
            ai_description TEXT,
            hiring_trend TEXT DEFAULT '[]',
            evidence TEXT DEFAULT '[]',
            score REAL DEFAULT 0,
            score_breakdown TEXT DEFAULT '{}',
            job_count_90d INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, domain)
        );

        CREATE TABLE IF NOT EXISTS job_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT,
            company_domain TEXT,
            title TEXT,
            location TEXT,
            job_type TEXT,
            date_posted TEXT,
            source TEXT,
            is_hybrid INTEGER DEFAULT 0,
            is_office INTEGER DEFAULT 0,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT,
            city TEXT,
            state TEXT,
            property_type TEXT,
            sqft INTEGER,
            price REAL,
            listing_url TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'running',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            records_collected INTEGER DEFAULT 0,
            companies_scored INTEGER DEFAULT 0,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(score DESC);
        CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(hq_city);
        CREATE INDEX IF NOT EXISTS idx_jobs_company ON job_listings(company_name);
        CREATE INDEX IF NOT EXISTS idx_jobs_posted ON job_listings(date_posted);
    """)
    conn.commit()
    conn.close()


def upsert_company(data: dict):
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM companies WHERE domain = ? OR (name = ? AND domain IS NULL)",
        (data.get("domain"), data.get("name"))
    ).fetchone()

    if existing:
        updates = []
        values = []
        for key, val in data.items():
            if key == "id":
                continue
            if val is not None and (existing[key] is None or key in ("score", "score_breakdown", "job_count_90d", "last_updated")):
                updates.append(f"{key} = ?")
                values.append(val)
        if updates:
            values.append(existing["id"])
            conn.execute(
                f"UPDATE companies SET {', '.join(updates)}, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )
            conn.commit()
        conn.close()
        return existing["id"]
    else:
        cols = [k for k in data.keys() if k != "id"]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [data[k] for k in cols]
        cursor = conn.execute(
            f"INSERT INTO companies ({', '.join(cols)}) VALUES ({placeholders})",
            vals
        )
        conn.commit()
        company_id = cursor.lastrowid
        conn.close()
        return company_id


def bulk_insert_jobs(records: list):
    if not records:
        return
    conn = get_db()
    conn.executemany(
        """INSERT INTO job_listings (company_name, company_domain, title, location, job_type, date_posted, source, is_hybrid, is_office, raw_data)
           VALUES (:company_name, :company_domain, :title, :location, :job_type, :date_posted, :source, :is_hybrid, :is_office, :raw_data)""",
        records
    )
    conn.commit()
    conn.close()


def get_companies(page=1, per_page=50, sort_by="score", sort_order="desc", min_score=0, industry=None, market=None, search=None):
    conn = get_db()
    query = "SELECT * FROM companies WHERE score >= ?"
    params = [min_score]

    if industry:
        query += " AND LOWER(industry) LIKE ?"
        params.append(f"%{industry.lower()}%")
    if market:
        query += " AND (LOWER(hq_city) LIKE ? OR LOWER(hq_state) LIKE ?)"
        params.extend([f"%{market.lower()}%", f"%{market.lower()}%"])
    if search:
        query += " AND (LOWER(name) LIKE ? OR LOWER(domain) LIKE ? OR LOWER(description) LIKE ?)"
        params.extend([f"%{search.lower()}%"] * 3)

    allowed_sorts = {"score", "name", "employee_count", "funding_total_usd", "job_count_90d"}
    if sort_by not in allowed_sorts:
        sort_by = "score"
    order = "DESC" if sort_order == "desc" else "ASC"
    query += f" ORDER BY {sort_by} {order}"

    total = conn.execute(
        query.replace("SELECT *", "SELECT COUNT(*)"), params
    ).fetchone()[0]

    query += " LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_company_detail(company_id: int):
    conn = get_db()
    company = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not company:
        conn.close()
        return None
    company = dict(company)
    jobs = conn.execute(
        "SELECT title, location, date_posted, source, is_hybrid FROM job_listings WHERE company_name = ? ORDER BY date_posted DESC LIMIT 20",
        (company["name"],)
    ).fetchall()
    company["recent_jobs"] = [dict(j) for j in jobs]
    conn.close()
    return company


def get_dashboard_stats():
    conn = get_db()
    stats = {}
    stats["total_companies"] = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    stats["scored_companies"] = conn.execute("SELECT COUNT(*) FROM companies WHERE score > 0").fetchone()[0]
    stats["avg_score"] = conn.execute("SELECT COALESCE(AVG(score), 0) FROM companies WHERE score > 0").fetchone()[0]
    stats["total_jobs"] = conn.execute("SELECT COUNT(*) FROM job_listings").fetchone()[0]
    stats["high_score_count"] = conn.execute("SELECT COUNT(*) FROM companies WHERE score >= 70").fetchone()[0]
    stats["medium_score_count"] = conn.execute("SELECT COUNT(*) FROM companies WHERE score >= 40 AND score < 70").fetchone()[0]

    top_industries = conn.execute(
        "SELECT industry, COUNT(*) as cnt, AVG(score) as avg_score FROM companies WHERE industry IS NOT NULL AND score > 0 GROUP BY industry ORDER BY avg_score DESC LIMIT 10"
    ).fetchall()
    stats["top_industries"] = [{"industry": r["industry"], "count": r["cnt"], "avg_score": round(r["avg_score"], 1)} for r in top_industries]

    top_markets = conn.execute(
        "SELECT hq_city, COUNT(*) as cnt, AVG(score) as avg_score FROM companies WHERE hq_city IS NOT NULL AND score > 0 GROUP BY hq_city ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    stats["top_markets"] = [{"city": r["hq_city"], "count": r["cnt"], "avg_score": round(r["avg_score"], 1)} for r in top_markets]

    last_run = conn.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    stats["last_pipeline_run"] = dict(last_run) if last_run else None

    conn.close()
    return stats


def update_company_score(company_id: int, score: float, breakdown: dict):
    conn = get_db()
    conn.execute(
        "UPDATE companies SET score = ?, score_breakdown = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
        (score, json.dumps(breakdown), company_id)
    )
    conn.commit()
    conn.close()


def get_all_companies_for_scoring():
    conn = get_db()
    rows = conn.execute("SELECT * FROM companies").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_job_count_for_company(company_name: str, days: int = 90):
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM job_listings WHERE company_name = ? AND date_posted >= date('now', ?)",
        (company_name, f"-{days} days")
    ).fetchone()[0]
    conn.close()
    return count


def create_pipeline_run():
    conn = get_db()
    cursor = conn.execute("INSERT INTO pipeline_runs (status) VALUES ('running')")
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()
    return run_id


def update_pipeline_run(run_id: int, **kwargs):
    conn = get_db()
    updates = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [run_id]
    conn.execute(f"UPDATE pipeline_runs SET {updates} WHERE id = ?", values)
    conn.commit()
    conn.close()
