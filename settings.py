"""Application settings loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
PROMPT_PATH = Path(os.getenv("BOILERPLATE_PROMPT_PATH", BASE_DIR / "prompts/boilerplate.txt"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "800"))
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}
