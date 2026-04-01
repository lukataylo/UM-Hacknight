# SquareFootLoose

**AI-powered CRE sales intelligence agent that identifies companies about to open, expand, or relocate offices in London.**

SquareFootLoose pulls company data from LinkedIn via Bright Data, enriches it with Perplexity AI for funding, revenue, contacts, and news, then scores and ranks companies most likely to need office space. The dashboard is a static site deployed on GitHub Pages, refreshed daily via GitHub Actions.

**Live:** [https://lukataylo.github.io/UM-Hacknight/](https://lukataylo.github.io/UM-Hacknight/)

## Architecture

```
GitHub Pages (static)              Local CLI / GitHub Actions
┌──────────────────────┐          ┌──────────────────────────────┐
│  index.html           │  ←JSON   │  Bright Data LinkedIn API     │
│  data/companies.json  │  files   │  Perplexity Sonar API         │
│  data/meta.json       │          │  manage.py (CLI tool)         │
│  Password gate        │          │  → scores, exports, pushes    │
└──────────────────────┘          └──────────────────────────────┘
```

### Data Sources

| Source | What it provides | How it's used |
|---|---|---|
| **Bright Data** (LinkedIn Companies) | Employee count, industry, HQ location, LinkedIn URL, embedded funding data, featured employees, recent posts | New company discovery + base profile data |
| **Perplexity AI** (Sonar) | AI summaries, valuations, revenue estimates, CEO/CRO contacts, Glassdoor ratings, office size estimates, recent news, hiring signals | Deep enrichment of existing companies |
| **Local curation** | Glassdoor ratings, funding data, intelligence summaries | Manual enrichment for data gaps |

## Scoring Model

Each company receives a 0–100 score based on seven weighted signals:

| Signal | Weight | What it measures |
|---|---|---|
| Hiring Velocity | 30% | Job postings relative to company size |
| Funding Recency | 20% | How recently they raised, round type, amount |
| Headcount Growth | 15% | Growth rate estimated from job listings |
| Industry Fit | 10% | Whether the industry typically needs office space |
| Location Match | 10% | Presence in London and target markets |
| Company Stage | 10% | Series A–C are prime movers for office expansion |
| Glassdoor Sentiment | 5% | Low ratings + high growth = likely to upgrade space |

## Dashboard Features

### Morning Brief
Card grid showing each prospect with:
- Company favicon, name, location
- Intel score (colour-coded: green 80+, amber 60–79, red <60) with **hover tooltip** showing 7-signal breakdown
- Signal tags (Hiring Surge, Series C Funded, Growth Stage, etc.)
- **Stats row**: employees, funding amount, round type, Glassdoor rating
- AI-generated intelligence summary (truncated to 3 lines)
- Hiring trend mini bar chart (6-month)
- **Star/bookmark** button (persisted in localStorage)
- **NEW badge** on recently added companies (blue pulsing pill)
- Expandable "Why now?" evidence timeline

### Spreadsheet
Full data table with:
- **Clickable sortable columns** (score, name, employees, funding, etc.) with ascending/descending arrows
- **Star column** for bookmarking
- **NEW badges** inline with company name
- Score tooltip on hover
- Expandable rows with AI intelligence report, evidence timeline, signal tags
- Decision maker contact card (name, title, estimated email)
- "Push to CRM" action button
- CSV export (client-side, all filtered data)

### Live News Ticker
Bloomberg-style scrolling ticker at the top showing curated intelligence summaries for top-scored companies, colour-coded by priority.

### Filters
- City, signal type, industry, size (sqft) dropdowns
- **Starred Only** — show only bookmarked companies
- **New Prospects** — show recently added companies
- Full-text search across name, domain, and description

### Password Protection
SHA-256 hash-verified password gate. Password: `squarefootloose`

## Quick Start

### View the dashboard
Open [https://lukataylo.github.io/UM-Hacknight/](https://lukataylo.github.io/UM-Hacknight/) and enter the password.

### Local development

```bash
# Clone
git clone https://github.com/lukataylo/UM-Hacknight.git
cd UM-Hacknight

# Install dependencies
pip install -r requirements.txt

# Set API keys
cp .env.example .env  # then edit with your keys

# Check database status
python manage.py status

# Pull new companies from Bright Data
python manage.py pull monzo-bank revolut stripe

# Enrich with Perplexity AI
python manage.py enrich --perplexity --limit 20

# Apply Glassdoor ratings + funding
python manage.py enrich

# Re-score, export, and push to GitHub Pages
python manage.py push
```

## CLI Reference (`manage.py`)

| Command | Description |
|---|---|
| `status` | Show database stats (total, with industry, funding, Glassdoor, etc.) |
| `pull <slugs...>` | Pull new companies from Bright Data LinkedIn API. Accepts LinkedIn slugs or full URLs |
| `enrich` | Apply known Glassdoor ratings + crawl Crunchbase funding |
| `enrich --perplexity` | Deep enrichment via Perplexity AI (summaries, revenue, contacts, news, office size) |
| `enrich --perplexity --force` | Re-enrich all companies, not just those missing data |
| `enrich --perplexity --limit 10` | Limit to N companies |
| `enrich --glassdoor-only` | Only apply Glassdoor ratings |
| `enrich --funding-only` | Only crawl funding data |
| `rate <company> <rating>` | Manually set a Glassdoor rating (1.0–5.0) |
| `push` | Re-score all companies, export to JSON, git commit + push |

## Project Structure

```
index.html                  Static dashboard (vanilla HTML/CSS/JS, deployed via GitHub Pages)
data/
  companies.json            Pre-scored company data (loaded by frontend)
  meta.json                 Last updated timestamp and counts
manage.py                   Local CLI for pulling, enriching, and pushing data
scripts/
  export_data.py            Export SQLite to static JSON files
backend/
  bright_data.py            Bright Data LinkedIn Companies API client
  perplexity.py             Perplexity Sonar API client for deep enrichment
  scorer.py                 Company scoring algorithm (7 weighted signals)
  database.py               SQLite schema, queries, CRUD
  config.py                 API keys, weights, target markets
  seed_demo.py              Demo data seeder (not used in production)
  pipeline_cli.py           CLI entry point for GitHub Actions pipeline
  main.py                   FastAPI server (legacy, not used in static deployment)
.github/workflows/
  refresh-data.yml          Daily data refresh (Bright Data + Perplexity + export + push)
  pull-companies.yml        On-demand company pull triggered from UI or GitHub
.env                        API keys (not committed)
requirements.txt            Python dependencies
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BRIGHT_DATA_API_KEY` | Yes | Bright Data API key for LinkedIn Companies dataset |
| `PERPLEXITY_API_KEY` | Optional | Perplexity Sonar API key for deep enrichment |
| `DATABASE_PATH` | No | SQLite path (default: `./cre_intel.db`) |

For GitHub Actions, add these as repository secrets in Settings → Secrets → Actions.

## GitHub Actions

### Refresh Data (daily)
Runs at 6 AM UTC daily or on manual dispatch:
1. Pulls new companies from Bright Data
2. Enriches top 20 via Perplexity (if key is set)
3. Exports to JSON and pushes to GitHub Pages

### Pull Companies (on-demand)
Triggered from the dashboard UI or GitHub Actions UI:
1. Accepts comma-separated LinkedIn slugs
2. Pulls from Bright Data, enriches, scores
3. Exports and pushes

## Responsive Design

The dashboard scales across all screen sizes:
- **2200px+** (4K/ultrawide): 5-column card grid, wider layout
- **1600px+** (large monitors): 4-column cards, expanded padding
- **1024–1600px** (desktop): 3-column cards, default layout
- **700–1024px** (tablet): 2-column cards, stacked nav/filters
- **<700px** (mobile): single column, compact filters, horizontal table scroll

## Tech Stack

- **Frontend**: Vanilla HTML/CSS/JS (no build step, no framework)
- **Hosting**: GitHub Pages (static)
- **Data**: Bright Data Datasets API + Perplexity Sonar API
- **Database**: SQLite (local only, for data processing)
- **Scoring**: Python (backend/scorer.py)
- **CI/CD**: GitHub Actions
- **Fonts**: Inter, JetBrains Mono, Libre Baskerville
