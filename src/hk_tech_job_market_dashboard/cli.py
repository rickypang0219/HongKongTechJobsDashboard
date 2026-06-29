from __future__ import annotations

import argparse
from pathlib import Path

from .jobsdb_parser import parse_saved_html
from .jobsdb_pipeline import process_jobsdb_csvs
from .trends import fetch_google_trends


def main() -> None:
    parser = argparse.ArgumentParser(description="HK Tech Job Market data pipeline")
    parser.add_argument(
        "command",
        choices=(
            "fetch-trends",
            "import-jobsdb-html",
            "process-jobsdb",
            "all",
        ),
        nargs="?",
        default="all",
    )
    parser.add_argument("--input", type=Path, help="Path to a manually saved HTML file")
    args = parser.parse_args()

    if args.command in {"fetch-trends", "all"}:
        try:
            path = fetch_google_trends()
            print(f"Fetched real Google Trends data: {path}")
        except Exception as error:
            if args.command == "fetch-trends":
                raise
            print(f"Google Trends unavailable; retained existing cache if present: {error}")
    if args.command == "import-jobsdb-html":
        if args.input is None:
            parser.error("--input is required for import-jobsdb-html")
        print(f"Parsed local JobsDB HTML: {parse_saved_html(args.input)}")
    if args.command in {"process-jobsdb", "all"}:
        for name, path in process_jobsdb_csvs().items():
            print(f"Wrote JobsDB {name}: {path}")
