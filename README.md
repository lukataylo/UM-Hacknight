# SquareFootLoose

**AI-powered CRE sales intelligence agent that identifies companies about to open, expand, or relocate offices in London.**

SquareFootLoose scrapes job boards, company databases, and funding news daily to spot companies that are hiring in hybrid mode, opening new offices, or moving into fast-growing submarkets. It cross-checks those signals against funding rounds, headcount data, and market intelligence to prioritize accounts most likely to need office space in the next 6-18 months.

Every morning, it delivers a scored list of high-priority prospects to your sales team, enriched with location, hiring trend, and competitive context.

## Architecture

```
                         +------------------+
                         |   Bright Data    |
                         |   Datasets API   |
                         +--------+---------+
                                  |
                    LinkedIn Jobs | Indeed Jobs
                    Crunchbase    | LinkedIn Companies
                    ZoomInfo      | Glassdoor
                                  |
                         +--------v---------+
                         |   Data Pipeline  |
                         |  (bright_data.py)|
                         +--------+---------+
                                  |
                         normalize & deduplicate
                                  |
                         +--------v---------+
                         |     SQLite DB    |
                         |  companies       |
                         |  job_listings    |
                         |  pipeline_runs   |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |  Scoring Engine  |
                         |   (scorer.py)    |
                         |                  |
                         |  7 weighted      |
                         |  signals:        |
                         |  - hiring vel.   |
                         |  - funding       |
                         |  - headcount     |
                         |  - industry fit  |
                         |  - location      |
                         |  - stage         |
                         |  - glassdoor     |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |    FastAPI       |
                         |   (main.py)     |
                         +--------+---------+
                                  |
                         +--------v---------+
                         |    Frontend      |
                         |  Single-page     |
                         |  Dashboard       |
                         |                  |
                         |  Morning Brief   |
                         |  (card grid)     |
                         |                  |
                         |  Spreadsheet     |
                         |  (data table)    |
                         +------------------+
```

## Scoring Model

Each company receives a 0-100 score based on seven weighted signals:

| Signal | Weight | What it measures |
|---|---|---|
| Hiring Velocity | 30% | Job postings relative to company size |
| Funding Recency | 20% | How recently they raised, round type, amount |
| Headcount Growth | 15% | Growth rate estimated from job listings |
| Industry Fit | 10% | Whether the industry typically needs office space |
| Location Match | 10% | Presence in target markets (London, etc.) |
| Company Stage | 10% | Series A-C are prime movers for office expansion |
| Glassdoor Sentiment | 5% | Low ratings + high growth = likely to upgrade space |

## Data Sources (via Bright Data)

- **LinkedIn Job Listings** - hybrid/in-office role detection
- **Indeed Job Listings** - hiring volume by location
- **Crunchbase Companies** - funding rounds, headcount, stage
- **LinkedIn Company Info** - employee count, industry, HQ
- **ZoomInfo Companies** - revenue, contacts, financials
- **Glassdoor Companies** - ratings, office culture signals

## Dashboard Views

### Morning Brief
Card grid showing each prospect with:
- Company favicon, name, location, submarket
- Intel score (colour-coded: green 80+, amber 60-79, red <60)
- Signal tags (Hiring Surge, Series C Funded, New London Office, etc.)
- AI-generated summary in italic serif
- Hiring trend mini bar chart (6-month)
- Expandable "Why now?" evidence timeline

### Spreadsheet
Full data table with:
- Sortable columns (score, hiring, hybrid %, funding)
- Expandable rows with AI intelligence report
- Evidence timeline and signal tags
- Decision maker contact card (name, title, email, phone)
- "Push to CRM" action button
- CSV export

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Seed demo data (38 London-focused companies)
python -m backend.seed_demo

# Run the server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000
```

## Project Structure

```
backend/
  main.py           FastAPI server and API endpoints
  bright_data.py    Bright Data dataset API client
  scorer.py         Company scoring algorithm (7 signals)
  database.py       SQLite schema, queries, CRUD
  seed_demo.py      Demo data seeder (38 companies)
  config.py         API keys, weights, target markets

frontend/
  index.html        Single-page dashboard (vanilla HTML/CSS/JS)

.env                API keys and configuration
requirements.txt    Python dependencies
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serve dashboard |
| `GET` | `/api/stats` | Dashboard summary stats |
| `GET` | `/api/companies` | Paginated, filterable company list |
| `GET` | `/api/companies/{id}` | Company detail with jobs and score breakdown |
| `POST` | `/api/pipeline/run` | Trigger Bright Data ingestion pipeline |
| `GET` | `/api/pipeline/status` | Check pipeline run status |
| `GET` | `/api/export` | Download scored companies as CSV |

## Tech Stack

- **Backend**: Python, FastAPI, SQLite, httpx
- **Frontend**: Vanilla HTML/CSS/JS (no build step)
- **Data**: Bright Data Datasets API
- **Fonts**: Inter, JetBrains Mono, Libre Baskerville
