"""Database engine, session, and migration helpers."""

import threading
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from alembic import command
from settings import BASE_DIR, DATA_DIR, DATABASE_URL, UPLOAD_DIR


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""


engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

_storage_lock = threading.Lock()
_storage_ready = False


def make_alembic_config() -> Config:
    """Create Alembic configuration using the app's database URL."""
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def ensure_storage() -> None:
    """Create runtime directories and run pending database migrations once."""
    global _storage_ready  # noqa: PLW0603

    if _storage_ready:
        return

    with _storage_lock:
        if _storage_ready:
            return

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        if DATABASE_URL.startswith("sqlite:///"):
            sqlite_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        command.upgrade(make_alembic_config(), "head")
        _storage_ready = True
