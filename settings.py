"""Application settings loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool) -> bool:
    """Return a boolean environment variable value."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Return a comma-separated environment variable as a clean list."""
    value = os.getenv(name)
    if not value:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    """Return an integer environment variable value, falling back when invalid."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def normalize_gemini_model(model_name: str) -> str:
    """Return a Gemini model name using the Google API model prefix."""
    if model_name.startswith("models/"):
        return model_name
    return f"models/{model_name}"


def normalize_database_url(database_url: str) -> str:
    """Return a SQLAlchemy URL compatible with the installed database drivers."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUT_DIR = Path(os.getenv("OUT_DIR", BASE_DIR / "out"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH}")
PROMPT_PATH = Path(os.getenv("BOILERPLATE_PROMPT_PATH", BASE_DIR / "prompts/boilerplate.txt"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "800"))
GEMINI_MODELS = {
    "models/gemini-3-flash-preview": {
        "description": (
            "Fast, low-cost, good for prototyping and bulk jobs. Multimodal (video/text)"
        ),
        "cost": "$",
        "default": False,
    },
    "models/gemini-2.5-flash": {
        "description": "Mid-size, fast multimodal model (video/text), supports up to 1M tokens.",
        "cost": "$$",
        "default": False,
    },
    "models/gemini-2.5-pro": {
        "description": "High-accuracy, stable multimodal model (video/text), released June 2025.",
        "cost": "$$$",
        "default": True,
    },
}
DEFAULT_MODEL = normalize_gemini_model(os.getenv("GEMINI_MODEL", "models/gemini-2.5-pro"))
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}
KEEP_UPLOADED_VIDEOS = env_bool("KEEP_UPLOADED_VIDEOS", True)
KEEP_FAILED_UPLOADS = env_bool("KEEP_FAILED_UPLOADS", True)
UPLOAD_RETENTION_DAYS = int(os.getenv("UPLOAD_RETENTION_DAYS", "3"))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
BOOTSTRAP_ADMIN_NAME = os.getenv("BOOTSTRAP_ADMIN_NAME", "Admin")
ALLOW_SIGNUP = env_bool("ALLOW_SIGNUP", True)
SCOUTSMART_API_KEY = os.getenv("SCOUTSMART_API_KEY")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = os.getenv(
    "EMAIL_FROM",
    "scoutVISION <noreply@red-shield.ai>",
)
WEEKLY_REPORT_RECIPIENTS = env_list("WEEKLY_REPORT_RECIPIENTS")
WEEKLY_REPORT_DAYS = env_int("WEEKLY_REPORT_DAYS", 7)
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")
