"""Persistence helpers for prompt runs."""

from typing import Any

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models import PromptRun, User


def create_run(run: PromptRun) -> None:
    """Persist a new prompt run."""
    with SessionLocal() as session:
        session.add(run)
        session.commit()


def recent_runs(user: User, limit: int = 50) -> list[PromptRun]:
    """Return recent prompt runs for the index page."""
    with SessionLocal() as session:
        query = session.query(PromptRun).options(joinedload(PromptRun.user))
        if user.role != "admin":
            query = query.filter(PromptRun.user_id == user.id)
        return query.order_by(PromptRun.created_at.desc()).limit(limit).all()


def find_run(run_id: str, user: User | None = None) -> PromptRun | None:
    """Return one prompt run by ID, or None when it does not exist."""
    with SessionLocal() as session:
        run = (
            session.query(PromptRun)
            .options(joinedload(PromptRun.user))
            .filter(PromptRun.id == run_id)
            .one_or_none()
        )
        if run is None or user is None or user.role == "admin":
            return run
        if run.user_id != user.id:
            return None
        return run


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
