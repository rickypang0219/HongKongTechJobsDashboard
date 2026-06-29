"""Google Trends collector.

Google Trends is free to view, but pytrends uses an undocumented endpoint. The
official API remains limited-access alpha, so failures are surfaced clearly and
the last successful CSV remains available to the dashboard.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from pytrends.request import TrendReq

from .config import PROCESSED_DIR

TREND_TERMS = (
    "Data Engineer",
    "AI Engineer",
    "Quant Developer",
)


def fetch_google_trends(
    output: Path | None = None,
    terms: tuple[str, ...] = TREND_TERMS,
    timeframe: str = "today 5-y",
    geo: str = "HK",
) -> Path:
    """Fetch one comparable Trends request (Google limits requests to 5 terms)."""
    if not 1 <= len(terms) <= 5:
        raise ValueError("Google Trends comparisons require between 1 and 5 terms.")

    output = output or PROCESSED_DIR / "google_trends.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    # pytrends' retry adapter is incompatible with modern urllib3, so retries
    # are handled by the scheduled job rather than inside the archived client.
    client = TrendReq(hl="en-US", tz=-480, retries=0)
    client.build_payload(list(terms), timeframe=timeframe, geo=geo)
    pandas_frame = client.interest_over_time()
    if pandas_frame.empty:
        raise RuntimeError("Google Trends returned no data.")

    frame = (
        pl.from_pandas(pandas_frame.reset_index())
        .drop("isPartial", strict=False)
        .unpivot(index="date", variable_name="search_term", value_name="interest")
        .with_columns(
            pl.col("date").cast(pl.Date),
            pl.lit(geo).alias("geo"),
            pl.lit(timeframe).alias("timeframe"),
            pl.lit("Google Trends via unofficial pytrends client").alias("source"),
        )
        .sort(["date", "search_term"])
    )
    frame.write_csv(output)
    return output
