"""User query helpers."""

from database import SessionLocal
from models import User


def list_users() -> list[User]:
    """Return all users ordered by creation date."""
    with SessionLocal() as session:
        return session.query(User).order_by(User.created_at.desc()).all()
