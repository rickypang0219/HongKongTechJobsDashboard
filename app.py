from __future__ import annotations

from datetime import date

import plotly.express as px
import plotly.graph_objects as go
import polars as pl
import streamlit as st

from hk_tech_job_market_dashboard.config import PROCESSED_DIR

st.set_page_config(
    page_title="Hong Kong Tech Job Market",
    page_icon="📈",
    layout="wide",
)


@st.cache_data
def load_data() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Load legacy aggregate files if a caller explicitly supplies them."""
    names = (
        "jobs.csv",
        "job_daily_metrics.csv",
        "skill_daily_metrics.csv",
        "company_daily_metrics.csv",
    )
    return tuple(
        pl.read_csv(PROCESSED_DIR / name, try_parse_dates=True)
        for name in names
    )  # type: ignore[return-value]


def hk_money(value: float | int | None) -> str:
    return "—" if value is None else f"HK${value / 1000:,.0f}k"


def line_chart(frame: pl.DataFrame, y: str, title: str) -> go.Figure:
    fig = go.Figure()
    for family in frame["job_title"].unique(maintain_order=True):
        subset = frame.filter(pl.col("job_title") == family).sort("snapshot_date")
        fig.add_trace(
            go.Scatter(
                x=subset["snapshot_date"].to_list(),
                y=subset[y].to_list(),
                name=family,
                mode="lines",
            )
        )
    fig.update_layout(title=title, hovermode="x unified")
    return fig


def render_jobsdb_dashboard() -> None:
    listings_path = PROCESSED_DIR / "jobsdb_listings_clean.csv"
    snapshots_path = PROCESSED_DIR / "jobsdb_search_snapshots_clean.csv"
    if not listings_path.exists() or not snapshots_path.exists():
        return

    jobsdb = pl.read_csv(listings_path, try_parse_dates=True, infer_schema_length=10_000)
    snapshots = pl.read_csv(snapshots_path, try_parse_dates=True)
    latest_date = jobsdb["snapshot_date"].max()

    st.title("Hong Kong Tech Job Market")
    st.caption("JobsDB market snapshot · Real collected data")

    with st.sidebar:
        st.header("Filters")
        families = sorted(jobsdb["job_family"].unique().to_list())
        target_families = [
            family
            for family in ("AI Engineer", "Data Engineer", "Quant")
            if family in families
        ]
        selected_families = st.multiselect(
            "Role family", families, default=target_families or families
        )
        districts = sorted(jobsdb["district"].unique().to_list())
        selected_districts = st.multiselect("District", districts, default=districts)
        st.divider()
        st.success("Real JobsDB collection", icon="✅")
        st.caption(f"Latest snapshot: {latest_date:%d %b %Y}")

    filtered = jobsdb.filter(
        pl.col("job_family").is_in(selected_families)
        & pl.col("district").is_in(selected_districts)
    )
    if filtered.is_empty():
        st.info("No listings match the selected filters.")
        st.stop()

    latest_snapshot = snapshots["snapshot_date"].max()
    latest_search = snapshots.filter(
        (pl.col("snapshot_date") == latest_snapshot)
        & pl.col("job_family").is_in(selected_families)
    )
    reported_results = latest_search["result_count"].sum()
    sampled_jobs = filtered["source_job_id"].n_unique()
    salary_sample = filtered["salary_mid"].count()
    median_salary = filtered["salary_mid"].median()
    company_count = filtered["company"].n_unique()

    cards = st.columns(5)
    cards[0].metric("Reported search results", f"{reported_results:,}")
    cards[1].metric("Detailed listings sampled", f"{sampled_jobs:,}")
    cards[2].metric("Hiring companies sampled", f"{company_count:,}")
    cards[3].metric("Median monthly salary", hk_money(median_salary))
    cards[4].metric("Salary disclosure", f"{salary_sample / filtered.height:.1%}")

    st.info(
        f"JobsDB reported {reported_results:,} search results; this collection contains "
        f"{sampled_jobs:,} detailed listings. Detail-level charts describe the sample, "
        "not every reported result.",
        icon="ℹ️",
    )

    overview, location_tab, trends_tab, skills_tab, salary_tab, listings_tab = st.tabs(
        [
            "Overview",
            "Role × District",
            "Search Interest",
            "Tech Stack by Role",
            "Salary",
            "Listings",
        ]
    )

    with overview:
        skill_rank = (
            filtered.select("source_job_id", "skills")
            .with_columns(pl.col("skills").str.split("|"))
            .explode("skills", empty_as_null=True)
            .filter(pl.col("skills").str.len_chars() > 0)
            .group_by("skills")
            .agg(pl.col("source_job_id").n_unique().alias("listings"))
            .sort("listings", descending=True)
            .head(15)
        )
        fig = px.bar(
            skill_rank,
            x="listings",
            y="skills",
            orientation="h",
            color="listings",
            color_continuous_scale=["#ccfbf1", "#0f766e"],
            title="Tech-stack demand across all sampled roles",
            labels={"listings": "Listings", "skills": ""},
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Count = unique sampled job listings that mention the skill. "
            "A listing contributes at most once to each skill."
        )

    with location_tab:
        role_district = (
            filtered.filter(pl.col("district") != "Unspecified")
            .group_by(["district", "job_family"])
            .agg(pl.col("source_job_id").n_unique().alias("openings"))
            .sort(["district", "job_family"])
        )
        if role_district.is_empty():
            st.info("No district-level listings match the current filters.")
        else:
            district_order = (
                role_district.group_by("district")
                .agg(pl.col("openings").sum().alias("total"))
                .sort("total", descending=True)["district"]
                .to_list()
            )
            fig = px.bar(
                role_district,
                x="district",
                y="openings",
                color="job_family",
                barmode="group",
                category_orders={"district": district_order},
                title="Sampled openings by role and district",
                labels={
                    "openings": "Listings",
                    "district": "District",
                    "job_family": "Role family",
                },
            )
            fig.update_layout(xaxis_tickangle=-35)
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Role family is classified from the job title. Unspecified locations "
                "are excluded from this chart."
            )
            st.dataframe(role_district, width="stretch", hide_index=True)

    with trends_tab:
        trends_path = PROCESSED_DIR / "google_trends.csv"
        if not trends_path.exists():
            st.info(
                "Google Trends data is unavailable. Run "
                "`uv run hk-tech-job-market-dashboard fetch-trends`."
            )
        else:
            trend_data = pl.read_csv(trends_path, try_parse_dates=True)
            target_terms = ["Data Engineer", "AI Engineer", "Quant Developer"]
            trend_data = trend_data.filter(pl.col("search_term").is_in(target_terms))
            timeframe_value = trend_data["timeframe"].first()
            timeframe_label = (
                "last 5 years" if timeframe_value == "today 5-y" else "last 12 months"
            )
            selected_peak = trend_data["interest"].max()
            if selected_peak and selected_peak > 0:
                trend_data = trend_data.with_columns(
                    (pl.col("interest") / selected_peak * 100)
                    .round(1)
                    .alias("interest_rebased")
                )
            else:
                trend_data = trend_data.with_columns(
                    pl.col("interest").cast(pl.Float64).alias("interest_rebased")
                )
            fig = go.Figure()
            for term in target_terms:
                subset = trend_data.filter(pl.col("search_term") == term).sort("date")
                if subset.is_empty():
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=subset["date"].to_list(),
                        y=subset["interest_rebased"].to_list(),
                        name=term,
                        mode="lines+markers",
                        hovertemplate=(
                            "%{x|%d %b %Y}<br>Interest: %{y}<extra>%{fullData.name}</extra>"
                        ),
                    )
                )
            fig.update_layout(
                title=f"Role search interest in Hong Kong — {timeframe_label}",
                xaxis_title=None,
                yaxis_title="Relative search interest (0–100)",
                hovermode="x unified",
                height=480,
                legend_title_text="Search term",
            )
            st.plotly_chart(fig, width="stretch")
            st.caption(
                f"Source: Google Trends, geography HK, {timeframe_label}. Values are "
                "rebased so the highest point among these three terms equals 100; they "
                "are not absolute search volume. "
                "Low-volume searches may appear as zero."
            )

    with skills_tab:
        available_roles = sorted(filtered["job_family"].unique().to_list())
        selected_role = st.selectbox("Role family", available_roles)
        role_jobs = filtered.filter(pl.col("job_family") == selected_role)
        role_skill_rank = (
            role_jobs.select("source_job_id", "skills")
            .with_columns(pl.col("skills").str.split("|"))
            .explode("skills", empty_as_null=True)
            .filter(pl.col("skills").str.len_chars() > 0)
            .group_by("skills")
            .agg(pl.col("source_job_id").n_unique().alias("listings"))
            .with_columns(
                (pl.col("listings") / role_jobs["source_job_id"].n_unique())
                .round(3)
                .alias("share_of_role")
            )
            .sort("listings", descending=True)
            .head(15)
        )
        if role_skill_rank.is_empty():
            st.info("No extracted skills for this role family.")
        else:
            fig = px.bar(
                role_skill_rank,
                x="listings",
                y="skills",
                orientation="h",
                color="share_of_role",
                color_continuous_scale=["#fef3c7", "#d97706"],
                title=f"Tech-stack demand for {selected_role}",
                labels={
                    "listings": "Listings mentioning skill",
                    "skills": "",
                    "share_of_role": "Share of role",
                },
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, width="stretch")
            st.caption(
                f"Based on {role_jobs.height} sampled {selected_role} listings. "
                "Colour shows the share of listings in this role that mention each skill."
            )

    with salary_tab:
        benchmark_path = (
            PROCESSED_DIR.parent / "reference" / "salary_benchmarks.csv"
        )
        if benchmark_path.exists():
            benchmarks = pl.read_csv(benchmark_path)
            available_benchmark_roles = sorted(
                benchmarks["role_family"].unique().to_list()
            )
            default_benchmark_roles = [
                role
                for role in (
                    "Data Engineer",
                    "Data Scientist",
                    "Business Analyst",
                    "Data Analyst",
                    "Software Engineer",
                    "Full Stack Developer",
                )
                if role in available_benchmark_roles
            ]
            benchmark_roles = st.multiselect(
                "Historical benchmark roles",
                available_benchmark_roles,
                default=default_benchmark_roles,
                key="salary_benchmark_roles",
            )
            benchmark_filtered = benchmarks.filter(
                pl.col("role_family").is_in(benchmark_roles)
            )
            benchmark_fig = go.Figure()
            for role in benchmark_roles:
                role_data = benchmark_filtered.filter(
                    pl.col("role_family") == role
                ).sort("year")
                if role_data.is_empty():
                    continue
                benchmark_fig.add_trace(
                    go.Scatter(
                        x=role_data["year"].to_list(),
                        y=role_data["salary_mid_monthly_hkd"].to_list(),
                        name=role,
                        mode="lines+markers",
                        customdata=list(
                            zip(
                                role_data["salary_low_monthly_hkd"].to_list(),
                                role_data["salary_high_monthly_hkd"].to_list(),
                                role_data["source"].to_list(),
                                role_data["scope"].to_list(),
                                strict=True,
                            )
                        ),
                        hovertemplate=(
                            "Year: %{x}<br>Mid: HK$%{y:,.0f}/month"
                            "<br>Range: HK$%{customdata[0]:,.0f}–"
                            "HK$%{customdata[1]:,.0f}"
                            "<br>Source: %{customdata[2]}"
                            "<br>Scope: %{customdata[3]}"
                            "<extra>%{fullData.name}</extra>"
                        ),
                    )
                )
            benchmark_fig.update_layout(
                title="Published salary benchmarks by role",
                xaxis_title=None,
                yaxis_title="Monthly salary benchmark (HKD)",
                hovermode="x unified",
                height=470,
                legend_title_text="Role family",
            )
            st.plotly_chart(benchmark_fig, width="stretch")
            st.caption(
                "2018–2021: Hays annual ranges converted to monthly; mid is the range "
                "midpoint. 2022–2024: Randstad Hong Kong information-technology guides. "
                "2025: Randstad financial-services technology and engineering scopes. "
                "2026: Robert Half starting-salary percentiles converted from annual to "
                "monthly. Missing points mean no sufficiently comparable Hong Kong role "
                "benchmark was found. Source and scope changes mean this is a benchmark "
                "series, not a like-for-like salary index."
            )
            with st.expander("Benchmark data and sources"):
                st.dataframe(
                    benchmark_filtered,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "source_url": st.column_config.LinkColumn("Source")
                    },
                )

        st.subheader("Current JobsDB advertised salary sample")
        salary_jobs = filtered.filter(pl.col("salary_mid").is_not_null())
        if salary_jobs.is_empty():
            st.info("No valid salary ranges in this sample.")
        else:
            fig = px.box(
                salary_jobs,
                x="job_family",
                y="salary_mid",
                color="job_family",
                points="all",
                title="Advertised monthly salary by role family",
                labels={"salary_mid": "Monthly salary (HKD)", "job_family": ""},
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, width="stretch")
            st.caption(
                f"Based on {salary_jobs.height} disclosed salary ranges out of "
                f"{filtered.height} sampled listings."
            )

    with listings_tab:
        display = filtered.select(
            "job_title",
            "job_family",
            "company",
            "location_raw",
            "district",
            "posted_date",
            "salary_low",
            "salary_high",
            "skills",
            "link",
        )
        st.dataframe(display, width="stretch", hide_index=True, height=520)
        st.download_button(
            "Download filtered listings",
            display.write_csv(),
            file_name=f"jobsdb_filtered_{latest_date:%Y%m%d}.csv",
            mime="text/csv",
        )

    st.caption(
        "Source: user-collected JobsDB CSV · Search totals and detail samples have "
        "different grains and are deliberately shown separately."
    )
    st.stop()


render_jobsdb_dashboard()


st.title("Hong Kong Tech Job Market")
st.caption("Monitor openings, salary signals, skills and hiring companies in one view.")

try:
    jobs, daily, skills, companies = load_data()
except (FileNotFoundError, pl.exceptions.PolarsError) as error:
    st.error(str(error))
    st.code("uv run hk-tech-job-market-dashboard all\nuv run streamlit run app.py")
    st.stop()

min_date = daily["snapshot_date"].min()
max_date = daily["snapshot_date"].max()
families = sorted(daily["job_title"].unique().to_list())

with st.sidebar:
    st.header("Filters")
    selected_families = st.multiselect(
        "Job families", families, default=families, placeholder="Choose job families"
    )
    selected_dates = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    st.divider()
    st.caption(f"Latest snapshot: {max_date:%d %b %Y}")
    st.info("Legacy aggregate view", icon="ℹ️")

if not selected_families:
    st.info("Select at least one job family.")
    st.stop()

start_date, end_date = (
    selected_dates if isinstance(selected_dates, tuple) and len(selected_dates) == 2 else (min_date, max_date)
)
daily_filtered = daily.filter(
    pl.col("job_title").is_in(selected_families)
    & pl.col("snapshot_date").is_between(start_date, end_date)
)
latest_date = daily_filtered["snapshot_date"].max()
latest = daily_filtered.filter(pl.col("snapshot_date") == latest_date)
first = daily_filtered.filter(pl.col("snapshot_date") == daily_filtered["snapshot_date"].min())

latest_openings = latest["active_openings"].sum()
first_openings = first["active_openings"].sum()
opening_delta = (
    (latest_openings / first_openings - 1) * 100 if first_openings else None
)
weighted_salary = (
    latest.select(
        (
            (pl.col("salary_median") * pl.col("salary_sample_size")).sum()
            / pl.col("salary_sample_size").sum()
        ).alias("value")
    ).item()
)
company_count = (
    companies.filter(
        (pl.col("snapshot_date") == latest_date)
        & pl.col("job_title").is_in(selected_families)
    )["company"]
    .n_unique()
)
disclosure = (
    latest["salary_sample_size"].sum() / latest["active_openings"].sum()
    if latest["active_openings"].sum()
    else 0
)

cards = st.columns(4)
cards[0].metric("Active openings", f"{latest_openings:,}", f"{opening_delta:+.1f}%")
cards[1].metric("Median monthly salary", hk_money(weighted_salary))
cards[2].metric("Hiring companies", f"{company_count:,}")
cards[3].metric("Salary disclosure", f"{disclosure:.1%}")

overview_tab, salary_tab, trends_tab, skill_tab, company_tab, listings_tab = st.tabs(
    ["Overview", "Salary", "Search interest", "Skills", "Companies", "Listings"]
)

with overview_tab:
    st.plotly_chart(
        line_chart(daily_filtered, "active_openings", "Active openings over time"),
        width="stretch",
    )
    ranking = latest.sort("active_openings", descending=True)
    fig = px.bar(
        ranking,
        x="active_openings",
        y="job_title",
        orientation="h",
        color="active_openings",
        color_continuous_scale=["#dbeafe", "#2563eb"],
        labels={"active_openings": "Openings", "job_title": ""},
        title="Current openings by job family",
    )
    fig.update_layout(
        showlegend=False, coloraxis_showscale=False, yaxis={"categoryorder": "total ascending"}
    )
    st.plotly_chart(fig, width="stretch")

with salary_tab:
    salary_data = daily_filtered.filter(pl.col("salary_sample_size") > 0)
    st.plotly_chart(
        line_chart(salary_data, "salary_median", "Median advertised salary"),
        width="stretch",
    )
    st.caption(
        "Monthly HKD. Only listings with valid disclosed salary ranges are included."
    )
    st.dataframe(
        latest.select(
            "job_title",
            "salary_median",
            "salary_p25",
            "salary_p75",
            "salary_sample_size",
            "salary_disclosure_rate",
        ).sort("salary_median", descending=True),
        width="stretch",
        hide_index=True,
    )

with trends_tab:
    trends_path = PROCESSED_DIR / "google_trends.csv"
    if trends_path.exists():
        trend_data = pl.read_csv(trends_path, try_parse_dates=True)
        fig = go.Figure()
        for term in trend_data["search_term"].unique(maintain_order=True):
            subset = trend_data.filter(pl.col("search_term") == term).sort("date")
            fig.add_trace(
                go.Scatter(
                    x=subset["date"].to_list(),
                    y=subset["interest"].to_list(),
                    name=term,
                    mode="lines",
                )
            )
        fig.update_layout(
            title="Google search interest in Hong Kong",
            yaxis_title="Relative interest (0–100)",
            xaxis_title=None,
            hovermode="x unified",
            height=460,
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Real Google Trends data. Values are relative within this five-term, "
            "Hong Kong, 12-month comparison—not absolute search volume."
        )
    else:
        st.info(
            "No Google Trends cache yet. Run "
            "`uv run hk-tech-job-market-dashboard fetch-trends`."
        )

with skill_tab:
    latest_skills = (
        skills.filter(
            (pl.col("snapshot_date") == latest_date)
            & pl.col("job_title").is_in(selected_families)
        )
        .group_by("skills")
        .agg(
            pl.col("listing_count").sum(),
            pl.col("total_jobs").sum(),
        )
        .with_columns(
            (pl.col("listing_count") / pl.col("total_jobs")).alias("share_of_jobs")
        )
        .sort("listing_count", descending=True)
        .head(15)
    )
    fig = px.bar(
        latest_skills,
        x="listing_count",
        y="skills",
        orientation="h",
        color="share_of_jobs",
        color_continuous_scale="Teal",
        labels={"listing_count": "Listings mentioning skill", "skills": ""},
        title="Top skills in current listings",
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, width="stretch")

with company_tab:
    latest_companies = (
        companies.filter(
            (pl.col("snapshot_date") == latest_date)
            & pl.col("job_title").is_in(selected_families)
        )
        .sort("active_openings", descending=True)
        .head(80)
    )
    heatmap = latest_companies.pivot(
        on="job_title",
        index="company",
        values="active_openings",
        aggregate_function="sum",
    ).fill_null(0)
    heatmap = heatmap.with_columns(
        pl.sum_horizontal(pl.exclude("company")).alias("_total")
    ).sort("_total", descending=True).head(12).drop("_total")
    fig = px.imshow(
        heatmap.drop("company").to_numpy(),
        x=heatmap.columns[1:],
        y=heatmap["company"].to_list(),
        color_continuous_scale="Blues",
        text_auto=True,
        aspect="auto",
        title="Company hiring heatmap",
        labels={"color": "Openings"},
    )
    st.plotly_chart(fig, width="stretch")

with listings_tab:
    listing_rows = jobs.filter(
        (pl.col("snapshot_date") == latest_date)
        & pl.col("job_title").is_in(selected_families)
    ).select(
        "job_title",
        "company",
        "location",
        "experience",
        "salary_low",
        "salary_high",
        "skills",
        "source",
        "link",
    )
    st.dataframe(listing_rows, width="stretch", hide_index=True, height=520)
    st.download_button(
        "Download filtered listings",
        listing_rows.write_csv(),
        file_name=f"hk_tech_jobs_{date.today():%Y%m%d}.csv",
        mime="text/csv",
    )

st.caption("Legacy aggregate view.")
