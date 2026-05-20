"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    """A user who can submit and review Gemini prompt runs."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="tester")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class PromptRun(Base):
    """A single Gemini prompt test run and its tester feedback."""

    __tablename__ = "prompt_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    video_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_video_path: Mapped[str] = mapped_column(Text, nullable=False)
    video_duration_seconds: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    boilerplate_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    full_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text)
    parsed_response_json: Mapped[str | None] = mapped_column(Text)
    full_response_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    feedback_rating: Mapped[str | None] = mapped_column(String(20))
    feedback_notes: Mapped[str | None] = mapped_column(Text)
