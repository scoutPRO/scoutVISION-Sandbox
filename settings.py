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


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUT_DIR = Path(os.getenv("OUT_DIR", BASE_DIR / "out"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
PROMPT_PATH = Path(os.getenv("BOILERPLATE_PROMPT_PATH", BASE_DIR / "prompts/boilerplate.txt"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "800"))
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}
KEEP_UPLOADED_VIDEOS = env_bool("KEEP_UPLOADED_VIDEOS", False)
KEEP_FAILED_UPLOADS = env_bool("KEEP_FAILED_UPLOADS", True)
