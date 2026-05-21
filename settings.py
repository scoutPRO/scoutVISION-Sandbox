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


def normalize_gemini_model(model_name: str) -> str:
    """Return a Gemini model name using the Google API model prefix."""
    if model_name.startswith("models/"):
        return model_name
    return f"models/{model_name}"


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUT_DIR = Path(os.getenv("OUT_DIR", BASE_DIR / "out"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
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
KEEP_UPLOADED_VIDEOS = env_bool("KEEP_UPLOADED_VIDEOS", False)
KEEP_FAILED_UPLOADS = env_bool("KEEP_FAILED_UPLOADS", True)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
BOOTSTRAP_ADMIN_NAME = os.getenv("BOOTSTRAP_ADMIN_NAME", "Admin")
ALLOW_SIGNUP = env_bool("ALLOW_SIGNUP", True)
