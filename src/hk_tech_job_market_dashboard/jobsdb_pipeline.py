"""Clean manually collected JobsDB CSV files with Polars."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .config import PROCESSED_DIR, RAW_DIR

DISTRICTS = (
    "Central and Western District",
    "Eastern District",
    "Southern District",
    "Wan Chai District",
    "Sham Shui Po District",
    "Kowloon City District",
    "Kwun Tong District",
    "Wong Tai Sin District",
    "Yau Tsim Mong District",
    "Islands District",
    "Kwai Tsing District",
    "North District",
    "Sai Kung District",
    "Sha Tin District",
    "Tai Po District",
    "Tsuen Wan District",
    "Tuen Mun District",
    "Yuen Long District",
)

REGION_BY_DISTRICT = {
    district: (
        "Hong Kong Island"
        if district
        in {
            "Central and Western District",
            "Eastern District",
            "Southern District",
            "Wan Chai District",
        }
        else "Kowloon"
        if district
        in {
            "Sham Shui Po District",
            "Kowloon City District",
            "Kwun Tong District",
            "Wong Tai Sin District",
            "Yau Tsim Mong District",
        }
        else "New Territories"
    )
    for district in DISTRICTS
}


def _district_expr() -> pl.Expr:
    result = pl.lit("Unspecified")
    for district in reversed(DISTRICTS):
        result = (
            pl.when(pl.col("location_raw").str.contains(district, literal=True))
            .then(pl.lit(district))
            .otherwise(result)
        )
    return result.alias("district")


def _job_family_expr() -> pl.Expr:
    title = pl.col("job_title").str.to_lowercase()
    return (
        pl.when(title.str.contains(r"\b(ai|artificial intelligence|machine learning|ml|llm)\b"))
        .then(pl.lit("AI Engineer"))
        .when(title.str.contains(r"\b(quant|quantitative)\b"))
        .then(pl.lit("Quant"))
        .when(
            title.str.contains(
                r"\b(data engineer|analytics engineer|data platform|etl|data warehouse|"
                r"data model|data architect|data intelligence)\b"
            )
        )
        .then(pl.lit("Data Engineer"))
        .when(title.str.contains(r"\b(data scientist|data science|data analyst|analytics)\b"))
        .then(pl.lit("Data Science & Analytics"))
        .when(
            title.str.contains(
                r"\b(software|developer|programmer|devops|site reliability|cloud engineer)\b"
            )
        )
        .then(pl.lit("Software & Cloud"))
        .otherwise(pl.lit("Other Tech"))
        .alias("job_family")
    )


def process_jobsdb_csvs(
    listings_path: Path | None = None,
    snapshots_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    listings_path = listings_path or RAW_DIR / "jobsdb_job_listings.csv"
    snapshots_path = snapshots_path or RAW_DIR / "jobsdb_search_snapshots.csv"
    output_dir = output_dir or PROCESSED_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshots_raw = pl.read_csv(snapshots_path, infer_schema_length=10_000)
    snapshots = (
        snapshots_raw.with_row_index("_row")
        .with_columns(
            pl.col("snapshot_date").str.to_date(strict=False),
            pl.col("result_count").cast(pl.Int64, strict=False),
        )
        .sort("_row")
        .group_by(["snapshot_date", "search_keyword", "source"], maintain_order=True)
        .agg(
            pl.col("result_count").last(),
            pl.col("search_url").last(),
            pl.len().alias("observations_that_day"),
        )
        .sort(["snapshot_date", "search_keyword"])
        .with_columns(
            pl.when(pl.col("search_keyword").str.to_lowercase().str.contains("quant"))
            .then(pl.lit("Quant"))
            .when(
                pl.col("search_keyword")
                .str.to_lowercase()
                .str.contains(r"\b(ai|machine learning|llm)\b")
            )
            .then(pl.lit("AI Engineer"))
            .when(pl.col("search_keyword").str.to_lowercase().str.contains("data"))
            .then(pl.lit("Data Engineer"))
            .otherwise(pl.col("search_keyword"))
            .alias("job_family")
        )
    )

    listings = (
        pl.read_csv(listings_path, infer_schema_length=10_000)
        .with_columns(
            pl.col("snapshot_date").str.to_date(strict=False),
            pl.col("posted_date").str.to_date(strict=False),
            pl.col("source_job_id").cast(pl.String),
            pl.col("salary_low").cast(pl.Float64, strict=False),
            pl.col("salary_high").cast(pl.Float64, strict=False),
            pl.col("location").fill_null("").alias("location_raw"),
            pl.col("skills").fill_null(""),
            pl.col("job_url").alias("link"),
            pl.lit("JobsDB").alias("source"),
        )
        .with_columns(
            pl.when(
                pl.col("salary_low").is_not_null()
                & pl.col("salary_high").is_not_null()
                & (pl.col("salary_high") >= pl.col("salary_low"))
            )
            .then((pl.col("salary_low") + pl.col("salary_high")) / 2)
            .otherwise(None)
            .alias("salary_mid"),
            _district_expr(),
            _job_family_expr(),
        )
        .with_columns(
            pl.col("district")
            .replace_strict(REGION_BY_DISTRICT, default="Unspecified")
            .alias("region")
        )
        .unique(["snapshot_date", "source_job_id"], keep="last")
        .sort(["snapshot_date", "job_title"])
    )

    outputs = {
        "listings": output_dir / "jobsdb_listings_clean.csv",
        "snapshots": output_dir / "jobsdb_search_snapshots_clean.csv",
    }
    listings.write_csv(outputs["listings"])
    snapshots.write_csv(outputs["snapshots"])
    return outputs
