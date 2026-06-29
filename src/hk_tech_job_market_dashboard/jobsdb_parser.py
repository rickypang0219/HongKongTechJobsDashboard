"""Offline parser for manually saved JobsDB HTML.

This module intentionally performs no network requests and contains no browser
automation. It extracts Schema.org ``JobPosting`` JSON-LD from HTML files that
the user already has locally.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import polars as pl
from bs4 import BeautifulSoup

from .config import RAW_DIR


def _job_postings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _job_postings(item)
    elif isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            yield value
        for key in ("@graph", "itemListElement"):
            if key in value:
                yield from _job_postings(value[key])
        if "item" in value:
            yield from _job_postings(value["item"])


def _salary(posting: dict[str, Any]) -> tuple[float | None, float | None]:
    base = posting.get("baseSalary") or {}
    value = base.get("value") if isinstance(base, dict) else {}
    if isinstance(value, (int, float)):
        amount = float(value)
        return amount, amount
    if not isinstance(value, dict):
        return None, None
    low = value.get("minValue")
    high = value.get("maxValue")
    return (
        float(low) if isinstance(low, (int, float)) else None,
        float(high) if isinstance(high, (int, float)) else None,
    )


def _location(posting: dict[str, Any]) -> str:
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address", {}) if isinstance(location, dict) else {}
    if not isinstance(address, dict):
        return ""
    return ", ".join(
        str(address[key])
        for key in ("addressLocality", "addressRegion")
        if address.get(key)
    )


def parse_saved_html(
    input_path: Path,
    output_path: Path | None = None,
    snapshot_date: date | None = None,
) -> Path:
    """Parse local JSON-LD JobPosting records into the raw CSV contract."""
    output_path = output_path or RAW_DIR / "jobsdb_manual_export.csv"
    snapshot_date = snapshot_date or date.today()
    soup = BeautifulSoup(input_path.read_text(encoding="utf-8"), "html.parser")
    rows: list[dict[str, Any]] = []

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text(strip=True))
        except json.JSONDecodeError:
            continue
        for posting in _job_postings(payload):
            low, high = _salary(posting)
            organisation = posting.get("hiringOrganization") or {}
            company = organisation.get("name", "") if isinstance(organisation, dict) else ""
            source_id = posting.get("identifier") or posting.get("url") or posting.get("title")
            if isinstance(source_id, dict):
                source_id = source_id.get("value", "")
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "source": "jobsdb_manual_html",
                    "source_job_id": str(source_id or ""),
                    "job_title": posting.get("title", ""),
                    "company": company,
                    "salary_low": low,
                    "salary_high": high,
                    "location": _location(posting),
                    "industry": posting.get("industry", ""),
                    "experience": posting.get("experienceRequirements", ""),
                    "skills": "",
                    "link": posting.get("url", ""),
                }
            )

    if not rows:
        raise ValueError("No Schema.org JobPosting JSON-LD found in the saved HTML.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(output_path)
    return output_path
