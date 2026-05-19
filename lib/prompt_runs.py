"""Persistence helpers for prompt runs."""

from typing import Any

from database import SessionLocal
from models import PromptRun


def create_run(run: PromptRun) -> None:
    """Persist a new prompt run."""
    with SessionLocal() as session:
        session.add(run)
        session.commit()


def recent_runs(limit: int = 50) -> list[PromptRun]:
    """Return recent prompt runs for the index page."""
    with SessionLocal() as session:
        return session.query(PromptRun).order_by(PromptRun.created_at.desc()).limit(limit).all()


def find_run(run_id: str) -> PromptRun | None:
    """Return one prompt run by ID, or None when it does not exist."""
    with SessionLocal() as session:
        return session.get(PromptRun, run_id)


def update_run(run_id: str, **fields: Any) -> None:
    """Update selected columns for a prompt run."""
    if not fields:
        return
    with SessionLocal() as session:
        run = session.get(PromptRun, run_id)
        if run is None:
            return
        for field, value in fields.items():
            setattr(run, field, value)
        session.commit()
