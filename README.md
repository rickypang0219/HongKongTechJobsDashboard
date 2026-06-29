# Hong Kong Tech Job Market Dashboard

A Streamlit dashboard built with Polars and real, user-collected JobsDB CSV data.

## Dashboard preview

![Hong Kong Tech Job Market dashboard](assets/dashboard-overview.png)

## Data layout

```text
data/raw/jobsdb_job_listings.csv
data/raw/jobsdb_search_snapshots.csv
        -> Polars cleaning
data/processed/jobsdb_listings_clean.csv
data/processed/jobsdb_search_snapshots_clean.csv
        -> Streamlit
```

Salary benchmarks live in `data/reference/salary_benchmarks.csv`; cached Google
Trends results live in `data/processed/google_trends.csv`.

## Run locally

```bash
uv sync
uv run hk-tech-job-market-dashboard process-jobsdb
uv run streamlit run app.py
```

Open <http://localhost:8501>.

To process JobsDB and refresh Google Trends together:

```bash
uv run hk-tech-job-market-dashboard all
```

The scraper writes to `data/raw/` by default. Existing raw CSVs are appended by
the scraper and read by the cleaning pipeline from the same paths.

## Run the scraper

```bash
uv run python -m scraper.main \
  --keywords "AI Engineer" "Data Engineer" "Quant Developer" \
  --pages 10 \
  --delay 0 \
  --headless true
```

The command appends raw results to:

- `data/raw/jobsdb_job_listings.csv`
- `data/raw/jobsdb_search_snapshots.csv`

After scraping, rebuild the dashboard-ready CSV files:

```bash
uv run hk-tech-job-market-dashboard process-jobsdb
```

## Daily GitHub Actions refresh

The workflow at `.github/workflows/daily-scrape.yml` runs every day at 08:30
Hong Kong time. It installs Playwright Chromium, runs the scraper, rebuilds the
cleaned files, and commits changed CSV files back to the current repository.
It can also be started manually from **Actions → Daily JobsDB data refresh →
Run workflow**.

The repository must allow GitHub Actions to write to the repository. Under
**Settings → Actions → General → Workflow permissions**, select **Read and
write permissions**. A protected default branch may require a separate
data-update branch or pull-request workflow instead of a direct push.

## Quality checks

```bash
uv run ruff check .
uv run pytest
```

Search totals and collected job details have different grains. Advertised
salary statistics exclude listings without a valid disclosed range.
