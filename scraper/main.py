import argparse
import csv
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .models import JobListing, SearchSnapshot
from .parsers import (
    extract_skills,
    normalise_space,
    parse_posted_date,
    parse_result_count,
    parse_salary_monthly_hkd,
    source_job_id_from_url,
)

BASE = "https://hk.jobsdb.com"
SOURCE = "JobsDB"


def build_search_url(keyword: str, page: int) -> str:
    """Build a JobsDB keyword search URL."""
    slug = keyword.lower().strip().replace("/", " ").replace(" ", "-")
    slug = "-".join(part for part in slug.split("-") if part)

    if page <= 1:
        return f"{BASE}/{slug}-jobs"
    return f"{BASE}/{slug}-jobs/page-{page}"


def canonical_job_url(url: str) -> str:
    """
    Return a stable job URL.

    JobsDB may expose the same job several times with different query strings
    or #sol fragments. The canonical URL keeps only /job/<job_id>.
    """
    full_url = urljoin(BASE, url)
    job_id = source_job_id_from_url(full_url)

    if job_id and job_id != full_url:
        return f"{BASE}/job/{job_id}"

    # Fallback: at least remove the fragment.
    parts = urlsplit(full_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def safe_text(locator, timeout_ms: int = 1500) -> str:
    try:
        if locator.count() == 0:
            return ""
        return normalise_space(locator.first.inner_text(timeout=timeout_ms))
    except Exception:
        return ""


def collect_job_links(
    page,
    search_url: str,
    timeout_ms: int,
) -> tuple[list[str], int | str, int]:
    """
    Open one search-result page and return unique JobsDB jobs.

    Returns:
        unique_job_urls, result_count, raw_link_count
    """
    page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass

    # Trigger lazy-loaded cards.
    for _ in range(3):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(500)

    body_text = safe_text(page.locator("body"), timeout_ms=3000)
    result_count = parse_result_count(body_text)

    raw_links = page.locator("a").evaluate_all(
        """
        els => els
          .map(a => a.href)
          .filter(h => h && h.includes('/job/'))
        """
    )

    unique_links: list[str] = []
    seen_job_ids: set[str] = set()

    for raw_link in raw_links:
        full_link = urljoin(BASE, raw_link)
        job_id = source_job_id_from_url(full_link)

        if not job_id or job_id in seen_job_ids:
            continue

        seen_job_ids.add(job_id)
        unique_links.append(canonical_job_url(full_link))

    return unique_links, result_count, len(raw_links)


def parse_detail_page(
    page,
    job_url: str,
    snapshot: date,
    timeout_ms: int,
) -> JobListing | None:
    try:
        page.goto(job_url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass
    except Exception as exc:
        print(f"[WARN] failed to open detail page: {job_url} | {exc}")
        return None

    text = safe_text(page.locator("body"), timeout_ms=3000)
    if not text:
        print(f"[WARN] empty detail page: {job_url}")
        return None

    title = safe_text(page.locator("h1"))

    company = ""
    company_candidates = [
        page.locator("[data-automation*='advertiser']"),
        page.locator("[data-automation*='company']"),
        page.locator("a[href*='/companies/']"),
    ]
    for locator in company_candidates:
        company = safe_text(locator)
        if company and company.lower() != title.lower():
            break

    location = ""
    location_candidates = [
        page.locator("[data-automation*='location']"),
        page.locator("span:has-text('Hong Kong')"),
        page.locator("span:has-text('Kowloon')"),
        page.locator("span:has-text('Central')"),
    ]
    for locator in location_candidates:
        location = safe_text(locator)
        if location:
            break

    salary_low, salary_high = parse_salary_monthly_hkd(text)

    return JobListing(
        snapshot_date=snapshot.isoformat(),
        source_job_id=source_job_id_from_url(job_url),
        job_title=title,
        company=company,
        location=location,
        posted_date=parse_posted_date(text, snapshot),
        salary_low=salary_low,
        salary_high=salary_high,
        skills=extract_skills(text),
        job_url=canonical_job_url(job_url),
    )


def append_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        if not file_exists:
            writer.writeheader()

        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def load_existing_snapshot_job_keys(path: Path) -> set[tuple[str, str]]:
    """
    Avoid only exact same-day duplicates.

    The same job ID should be allowed again on a later snapshot date because
    that tells us the job was still visible on that later date.
    """
    if not path.exists():
        return set()

    try:
        old = pd.read_csv(
            path,
            dtype=str,
            usecols=["snapshot_date", "source_job_id"],
        )
    except Exception as exc:
        print(f"[WARN] could not read existing jobs CSV: {exc}")
        return set()

    return {
        (str(snapshot_date), str(job_id))
        for snapshot_date, job_id in zip(
            old["snapshot_date"],
            old["source_job_id"],
        )
        if pd.notna(snapshot_date) and pd.notna(job_id)
    }


def deduplicate_keyword_links(links: list[str]) -> list[str]:
    """Deduplicate all collected search pages by JobsDB source_job_id."""
    unique_links: list[str] = []
    seen_job_ids: set[str] = set()

    for link in links:
        job_id = source_job_id_from_url(link)
        if not job_id or job_id in seen_job_ids:
            continue

        seen_job_ids.add(job_id)
        unique_links.append(canonical_job_url(link))

    return unique_links


def main() -> None:
    parser = argparse.ArgumentParser(description="JobsDB MVP scraper")
    parser.add_argument("--keywords", nargs="+", required=True)
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Maximum number of JobsDB search-result pages per keyword",
    )
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--headless", choices=["true", "false"], default="true")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--snapshot-out", default="data/raw/jobsdb_search_snapshots.csv"
    )
    parser.add_argument("--jobs-out", default="data/raw/jobsdb_job_listings.csv")
    parser.add_argument(
        "--max-detail",
        type=int,
        default=0,
        help="Maximum unique detail pages per keyword; 0 means no limit",
    )
    parser.add_argument(
        "--skip-detail",
        action="store_true",
        help="Save only snapshot date, job ID and URL without opening details",
    )
    args = parser.parse_args()

    if args.pages < 1:
        parser.error("--pages must be at least 1")
    if args.max_detail < 0:
        parser.error("--max-detail cannot be negative")
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    snapshot = date.today()
    snapshot_iso = snapshot.isoformat()
    snapshot_path = Path(args.snapshot_out)
    jobs_path = Path(args.jobs_out)

    snapshot_columns = [
        "snapshot_date",
        "search_keyword",
        "result_count",
        "source",
        "search_url",
    ]
    job_columns = [
        "snapshot_date",
        "source_job_id",
        "job_title",
        "company",
        "location",
        "posted_date",
        "salary_low",
        "salary_high",
        "skills",
        "job_url",
    ]

    existing_snapshot_job_keys = load_existing_snapshot_job_keys(jobs_path)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless == "true")
        context = browser.new_context(
            locale="en-HK",
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )

        search_page = context.new_page()
        detail_page = context.new_page()

        for keyword in args.keywords:
            print(f"\n=== Keyword: {keyword} ===")

            keyword_links: list[str] = []
            first_result_count: int | str = ""
            first_search_url = build_search_url(keyword, 1)

            for page_no in range(1, args.pages + 1):
                search_url = build_search_url(keyword, page_no)
                print(f"[SEARCH] {search_url}")

                try:
                    page_links, result_count, raw_count = collect_job_links(
                        search_page,
                        search_url,
                        args.timeout_ms,
                    )
                except Exception as exc:
                    print(f"[WARN] failed search page {search_url}: {exc}")
                    continue

                if page_no == 1:
                    first_result_count = result_count

                print(
                    f"[SEARCH] page {page_no}: "
                    f"{raw_count} raw links, {len(page_links)} unique jobs"
                )

                # No unique jobs normally means we reached a non-existent page.
                if not page_links:
                    print(f"[SEARCH] page {page_no}: no jobs; stop pagination")
                    break

                keyword_links.extend(page_links)
                time.sleep(args.delay)

            snapshot_row = SearchSnapshot(
                snapshot_date=snapshot_iso,
                search_keyword=keyword,
                result_count=first_result_count,
                source=SOURCE,
                search_url=first_search_url,
            ).to_dict()
            append_csv(snapshot_path, [snapshot_row], snapshot_columns)

            unique_links = deduplicate_keyword_links(keyword_links)
            print(
                f"[SEARCH] keyword total: {len(keyword_links)} page-level jobs, "
                f"{len(unique_links)} unique jobs"
            )

            if args.max_detail > 0:
                unique_links = unique_links[: args.max_detail]
                print(f"[LIMIT] detail pages limited to {len(unique_links)}")

            if args.skip_detail:
                rows: list[dict] = []

                for link in unique_links:
                    job_id = source_job_id_from_url(link)
                    snapshot_job_key = (snapshot_iso, job_id)

                    if snapshot_job_key in existing_snapshot_job_keys:
                        print(f"[SKIP] already saved today: {job_id}")
                        continue

                    rows.append(
                        JobListing(
                            snapshot_date=snapshot_iso,
                            source_job_id=job_id,
                            job_title="",
                            company="",
                            location="",
                            posted_date="",
                            salary_low="",
                            salary_high="",
                            skills="",
                            job_url=canonical_job_url(link),
                        ).to_dict()
                    )
                    existing_snapshot_job_keys.add(snapshot_job_key)

                append_csv(jobs_path, rows, job_columns)
                continue

            saved_count = 0
            skipped_count = 0
            failed_count = 0

            for index, link in enumerate(unique_links, start=1):
                job_id = source_job_id_from_url(link)
                snapshot_job_key = (snapshot_iso, job_id)

                if snapshot_job_key in existing_snapshot_job_keys:
                    print(f"[SKIP] already saved today: {job_id}")
                    skipped_count += 1
                    continue

                print(f"[DETAIL] {index}/{len(unique_links)} {link}")
                job = parse_detail_page(
                    detail_page,
                    link,
                    snapshot,
                    args.timeout_ms,
                )

                if job is None:
                    failed_count += 1
                    time.sleep(args.delay)
                    continue

                append_csv(jobs_path, [job.to_dict()], job_columns)
                existing_snapshot_job_keys.add(snapshot_job_key)
                saved_count += 1
                time.sleep(args.delay)

            print(
                f"[DONE] {keyword}: saved={saved_count}, "
                f"already_saved_today={skipped_count}, failed={failed_count}"
            )

        context.close()
        browser.close()

    print(f"\nSaved snapshots: {snapshot_path}")
    print(f"Saved jobs: {jobs_path}")


if __name__ == "__main__":
    main()
