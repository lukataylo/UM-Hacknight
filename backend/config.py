import os
from dotenv import load_dotenv

load_dotenv()

BRIGHT_DATA_API_KEY = os.getenv("BRIGHT_DATA_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./cre_intel.db")
TARGET_MARKETS = [m.strip() for m in os.getenv("TARGET_MARKETS", "London,Manchester,Berlin,Amsterdam,Paris,Dublin,Edinburgh,Bristol,Cambridge,Oxford").split(",")]

# Bright Data dataset IDs (only these 2 are active on this account)
DATASET_LINKEDIN_JOBS = ""  # not available
DATASET_INDEED_JOBS = "gd_l1vijqt9jfj7olije"
DATASET_CRUNCHBASE = ""  # not available
DATASET_LINKEDIN_COMPANIES = "gd_l1vikfnt1wgvvqz95w"
DATASET_ZOOMINFO = ""  # not available
DATASET_GLASSDOOR = ""  # not available

# Scoring weights
WEIGHTS = {
    "hiring_velocity": 0.30,
    "funding_recency": 0.20,
    "headcount_growth": 0.15,
    "industry_fit": 0.10,
    "location_match": 0.10,
    "company_stage": 0.10,
    "glassdoor_sentiment": 0.05,
}

# High-value industries for office space
OFFICE_INDUSTRIES = {
    "technology", "software", "fintech", "financial services", "finance",
    "consulting", "legal", "healthcare", "biotech", "media", "advertising",
    "marketing", "insurance", "real estate", "professional services",
    "information technology", "computer software", "internet",
}
