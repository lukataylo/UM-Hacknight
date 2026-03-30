import asyncio
import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.database import (
    init_db, get_companies, get_company_detail, get_dashboard_stats,
    create_pipeline_run, update_pipeline_run, get_db,
)
from backend.scorer import score_all_companies
from backend.bright_data import run_full_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CRE Sales Intelligence Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    return HTMLResponse(index_path.read_text())


@app.get("/api/stats")
async def api_stats():
    return get_dashboard_stats()


@app.get("/api/companies")
async def api_companies(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str = Query("score"),
    sort_order: str = Query("desc"),
    min_score: float = Query(0),
    industry: str = Query(None),
    market: str = Query(None),
    search: str = Query(None),
):
    companies, total = get_companies(
        page=page, per_page=per_page, sort_by=sort_by,
        sort_order=sort_order, min_score=min_score,
        industry=industry, market=market, search=search,
    )
    # Parse score_breakdown JSON
    for c in companies:
        if isinstance(c.get("score_breakdown"), str):
            try:
                c["score_breakdown"] = json.loads(c["score_breakdown"])
            except (json.JSONDecodeError, TypeError):
                c["score_breakdown"] = {}
    return {
        "companies": companies,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@app.get("/api/companies/{company_id}")
async def api_company_detail(company_id: int):
    company = get_company_detail(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if isinstance(company.get("score_breakdown"), str):
        try:
            company["score_breakdown"] = json.loads(company["score_breakdown"])
        except (json.JSONDecodeError, TypeError):
            company["score_breakdown"] = {}
    return company


@app.post("/api/pipeline/run")
async def api_run_pipeline(background_tasks: BackgroundTasks):
    run_id = create_pipeline_run()
    background_tasks.add_task(run_full_pipeline, run_id)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/pipeline/status")
async def api_pipeline_status():
    conn = get_db()
    run = conn.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    conn.close()
    if not run:
        return {"status": "no_runs"}
    return dict(run)


@app.post("/api/rescore")
async def api_rescore():
    scored = score_all_companies()
    return {"scored": scored}


@app.get("/api/export")
async def api_export(min_score: float = Query(0)):
    companies, _ = get_companies(page=1, per_page=10000, min_score=min_score)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Rank", "Company", "Industry", "City", "State", "Employees",
        "Funding Total ($)", "Latest Round", "Score",
        "Contact Name", "Contact Title", "Contact Email", "Contact Phone",
        "Website", "Description"
    ])

    for i, c in enumerate(companies, 1):
        writer.writerow([
            i, c.get("name"), c.get("industry"), c.get("hq_city"), c.get("hq_state"),
            c.get("employee_count"), c.get("funding_total_usd"), c.get("latest_funding_round"),
            c.get("score"), c.get("contact_name"), c.get("contact_title"),
            c.get("contact_email"), c.get("contact_phone"),
            c.get("website"), c.get("description"),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=cre_prospects_{datetime.now().strftime('%Y%m%d')}.csv"},
    )
