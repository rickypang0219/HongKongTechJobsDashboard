from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

JOB_FAMILIES = {
    "AI Engineer": ("ai engineer", "machine learning engineer", "llm engineer"),
    "Data Engineer": ("data engineer", "analytics engineer", "etl developer"),
    "Data Scientist": ("data scientist", "machine learning scientist"),
    "Quant Developer": ("quant developer", "quantitative developer"),
    "Quant Researcher": ("quant researcher", "quantitative researcher"),
    "Software Engineer": ("software engineer", "software developer"),
    "Python Developer": ("python developer", "python engineer"),
    "DevOps": ("devops", "site reliability engineer", "cloud engineer"),
}

SKILLS = (
    "Python",
    "SQL",
    "AWS",
    "Azure",
    "Spark",
    "Kafka",
    "LLM",
    "PyTorch",
    "TensorFlow",
    "CUDA",
    "Docker",
    "Linux",
    "Kubernetes",
    "Rust",
    "C++",
    "RAG",
)
