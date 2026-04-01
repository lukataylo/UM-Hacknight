"""CLI entry point for running the Bright Data pipeline (used by GitHub Actions)."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_db, create_pipeline_run
from backend.seed_demo import seed_database
from backend.bright_data import run_full_pipeline


def main():
    init_db()
    seed_database()
    run_id = create_pipeline_run()
    print(f"Starting pipeline run {run_id}...")
    asyncio.run(run_full_pipeline(run_id))
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
