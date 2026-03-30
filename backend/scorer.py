import json
from datetime import datetime, timedelta
from backend.config import WEIGHTS, OFFICE_INDUSTRIES, TARGET_MARKETS
from backend import database as db


def calculate_hiring_velocity(company: dict) -> float:
    """Score based on job posting volume relative to company size."""
    job_count = company.get("job_count_90d") or 0
    employee_count = company.get("employee_count") or 50  # assume mid-size if unknown

    if job_count == 0:
        return 0.0

    # Ratio of open positions to total employees
    ratio = job_count / max(employee_count, 1)

    # >10% open roles = very high growth, >5% = high, >2% = moderate
    if ratio > 0.10:
        return 1.0
    elif ratio > 0.05:
        return 0.8
    elif ratio > 0.02:
        return 0.6
    elif ratio > 0.01:
        return 0.4
    else:
        return 0.2


def calculate_funding_recency(company: dict) -> float:
    """Score based on how recently the company raised funding."""
    funding_date_str = company.get("latest_funding_date")
    funding_round = (company.get("latest_funding_round") or "").lower()
    funding_amount = company.get("latest_funding_amount") or company.get("funding_total_usd") or 0

    if not funding_date_str and not funding_round:
        return 0.1  # unknown = slight signal

    score = 0.0

    # Round type scoring
    round_scores = {
        "series a": 0.6, "series b": 0.9, "series c": 1.0, "series d": 0.9,
        "series e": 0.8, "seed": 0.4, "pre-seed": 0.2, "ipo": 0.5,
        "grant": 0.1, "debt": 0.3, "private equity": 0.7,
    }
    for round_type, round_score in round_scores.items():
        if round_type in funding_round:
            score = max(score, round_score)
            break

    # Recency decay
    if funding_date_str:
        try:
            funding_date = datetime.fromisoformat(funding_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
            days_ago = (datetime.now() - funding_date).days
            if days_ago < 90:
                score *= 1.0
            elif days_ago < 180:
                score *= 0.85
            elif days_ago < 365:
                score *= 0.65
            elif days_ago < 730:
                score *= 0.4
            else:
                score *= 0.2
        except (ValueError, TypeError):
            pass

    # Funding amount bonus
    if funding_amount:
        if funding_amount > 100_000_000:
            score = min(score + 0.15, 1.0)
        elif funding_amount > 50_000_000:
            score = min(score + 0.10, 1.0)
        elif funding_amount > 10_000_000:
            score = min(score + 0.05, 1.0)

    return score


def calculate_headcount_growth(company: dict) -> float:
    """Estimate headcount growth from job listings and employee count."""
    job_count = company.get("job_count_90d") or 0
    employee_count = company.get("employee_count") or 0

    if employee_count == 0 and job_count > 0:
        return 0.6  # hiring but size unknown = moderate signal

    if job_count == 0:
        return 0.1

    growth_rate = job_count / max(employee_count, 1)
    return min(growth_rate * 5, 1.0)  # 20% growth rate = 1.0


def calculate_industry_fit(company: dict) -> float:
    """Score based on whether the industry typically needs office space."""
    industry = (company.get("industry") or "").lower()
    if not industry:
        return 0.5  # unknown = neutral

    for office_ind in OFFICE_INDUSTRIES:
        if office_ind in industry:
            return 1.0

    remote_industries = {"remote", "freelance", "gig economy"}
    for remote_ind in remote_industries:
        if remote_ind in industry:
            return 0.1

    return 0.5  # default for unrecognized industries


def calculate_location_match(company: dict) -> float:
    """Score based on whether the company is in a target market."""
    city = (company.get("hq_city") or "").lower()
    state = (company.get("hq_state") or "").lower()

    if not city and not state:
        return 0.3  # unknown location

    for market in TARGET_MARKETS:
        if market.lower() in city or market.lower() in state:
            return 1.0

    return 0.3  # not in a target market


def calculate_company_stage(company: dict) -> float:
    """Score based on company stage (Series A-C are prime movers)."""
    funding_round = (company.get("latest_funding_round") or "").lower()
    employee_count = company.get("employee_count") or 0

    stage_scores = {
        "series a": 0.8, "series b": 1.0, "series c": 0.9,
        "series d": 0.7, "series e": 0.6, "seed": 0.5,
        "pre-seed": 0.3, "ipo": 0.4, "private equity": 0.6,
    }

    for stage, score in stage_scores.items():
        if stage in funding_round:
            return score

    # Infer from employee count if no funding data
    if employee_count > 0:
        if 20 <= employee_count <= 200:
            return 0.8  # sweet spot for office expansion
        elif 200 < employee_count <= 1000:
            return 0.7
        elif employee_count > 1000:
            return 0.5
        else:
            return 0.4

    return 0.4


def calculate_glassdoor_sentiment(company: dict) -> float:
    """Score from Glassdoor rating - mid-range with high growth is interesting."""
    rating = company.get("glassdoor_rating")
    if not rating:
        return 0.5  # unknown

    # Companies with 3.0-4.0 rating + high growth often need better space
    if 3.0 <= rating <= 4.0:
        return 0.7
    elif rating > 4.0:
        return 0.5  # happy employees, less pressure to change
    elif rating < 3.0:
        return 0.8  # unhappy = might move for better space
    return 0.5


def score_company(company: dict) -> tuple[float, dict]:
    """Calculate composite score for a company. Returns (total_score, breakdown)."""
    signals = {
        "hiring_velocity": calculate_hiring_velocity(company),
        "funding_recency": calculate_funding_recency(company),
        "headcount_growth": calculate_headcount_growth(company),
        "industry_fit": calculate_industry_fit(company),
        "location_match": calculate_location_match(company),
        "company_stage": calculate_company_stage(company),
        "glassdoor_sentiment": calculate_glassdoor_sentiment(company),
    }

    # Weighted sum, scaled to 0-100
    total = sum(signals[k] * WEIGHTS[k] for k in signals) * 100
    total = round(min(total, 100), 1)

    breakdown = {k: round(v, 3) for k, v in signals.items()}
    breakdown["total"] = total

    return total, breakdown


def score_all_companies() -> int:
    """Score every company in the database. Returns count of scored companies."""
    companies = db.get_all_companies_for_scoring()
    scored = 0

    for company in companies:
        total, breakdown = score_company(company)
        db.update_company_score(company["id"], total, breakdown)
        scored += 1

    return scored
