from dataclasses import dataclass, asdict


@dataclass
class SearchSnapshot:
    snapshot_date: str
    search_keyword: str
    result_count: int | str
    source: str
    search_url: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class JobListing:
    snapshot_date: str
    source_job_id: str
    job_title: str
    company: str
    location: str
    posted_date: str
    salary_low: int | str
    salary_high: int | str
    skills: str
    job_url: str

    def to_dict(self) -> dict:
        return asdict(self)
