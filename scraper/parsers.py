import re
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs


SKILL_KEYWORDS = [
    "Python", "SQL", "AWS", "Spark", "PySpark", "Java", "C++", "C#", "Rust",
    "Go", "Golang", "Docker", "Kubernetes", "Airflow", "Kafka", "Flink",
    "dbt", "Snowflake", "Databricks", "Azure", "GCP", "Linux", "Git",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "LLM", "RAG",
    "LangChain", "FastAPI", "Django", "Flask", "React", "TypeScript",
    "Excel", "Power BI", "Tableau", "SAS", "TensorFlow", "PyTorch",
]


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def source_job_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("jobId", "jobid"):
        if key in qs and qs[key]:
            return qs[key][0]

    # Common URL shapes include /job/<id> or slugs ending with numeric id.
    m = re.search(r"/job/(\d+)", parsed.path, re.I)
    if m:
        return m.group(1)

    m = re.search(r"(\d{6,})", parsed.path)
    if m:
        return m.group(1)

    return url


def parse_result_count(text: str) -> int | str:
    text = normalise_space(text)
    patterns = [
        r"([\d,]+)\s+jobs?\s+found",
        r"([\d,]+)\s+.+?\s+jobs?\s+in\s+Hong Kong",
        r"([\d,]+)\s+jobs?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    return ""


def _num_to_hkd(raw: str, original_fragment: str) -> int:
    raw_clean = raw.replace(",", "")
    value = float(raw_clean)
    # If the token is followed by k/K, convert 40K -> 40000.
    if re.search(rf"{re.escape(raw)}\s*[kK]\b", original_fragment):
        value *= 1000
    return int(round(value))


def parse_salary_monthly_hkd(text: str) -> tuple[int | str, int | str]:
    """
    Returns monthly HKD salary low/high. Empty string when unavailable.

    Handles examples such as:
    - HK$40K - 60K / month
    - $40,000 - $60,000 per month
    - HK$600,000 - HK$720,000 per year -> 50000, 60000
    """
    text = normalise_space(text)
    if not re.search(r"\$|HKD|HK\$|\bk\b", text, re.I):
        return "", ""

    # Work on local windows around salary-looking tokens to avoid picking random numbers.
    candidates = []
    for m in re.finditer(r"(?:HKD|HK\$|\$)?\s*\d[\d,]*(?:\.\d+)?\s*[kK]?", text):
        start = max(0, m.start() - 60)
        end = min(len(text), m.end() + 100)
        frag = text[start:end]
        if re.search(r"month|monthly|year|annual|annum|salary|薪|k\b|HKD|HK\$|\$", frag, re.I):
            candidates.append(frag)

    for frag in candidates:
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", frag)
        if not nums:
            continue
        values = [_num_to_hkd(n, frag) for n in nums[:2]]
        if not values:
            continue
        if len(values) == 1:
            values = [values[0], values[0]]

        low, high = min(values[0], values[1]), max(values[0], values[1])

        # Ignore tiny numbers unlikely to be salary.
        if high < 1000:
            continue

        if re.search(r"year|annual|annum", frag, re.I):
            low = round(low / 12)
            high = round(high / 12)

        return low, high

    return "", ""


def parse_posted_date(text: str, snapshot: date) -> str:
    text = normalise_space(text).lower()

    if re.search(r"listed\s+today|posted\s+today|today", text):
        return snapshot.isoformat()
    if re.search(r"listed\s+yesterday|posted\s+yesterday|yesterday", text):
        return (snapshot - timedelta(days=1)).isoformat()

    m = re.search(r"(\d+)\s*(?:d|day|days)\s+ago", text)
    if m:
        return (snapshot - timedelta(days=int(m.group(1)))).isoformat()

    m = re.search(r"(\d+)\s*(?:h|hour|hours)\s+ago", text)
    if m:
        return snapshot.isoformat()

    return ""


def extract_skills(text: str) -> str:
    found = []
    for skill in SKILL_KEYWORDS:
        if re.search(rf"(?<![A-Za-z0-9+#]){re.escape(skill)}(?![A-Za-z0-9+#])", text, re.I):
            found.append(skill)
    return "|".join(dict.fromkeys(found))
