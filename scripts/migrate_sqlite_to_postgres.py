"""Copy scoutVISION Sandbox data from SQLite into the configured Postgres database."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from database import make_alembic_config
from models import PromptRun, User
from settings import DATABASE_URL, DB_PATH, normalize_database_url


def sqlite_url_from_path(path: str) -> str:
    """Return a SQLAlchemy SQLite URL for a local database path."""
    return f"sqlite:///{Path(path).expanduser().resolve()}"


def count_rows(session: Session) -> tuple[int, int]:
    """Return user and prompt run counts for a database session."""
    user_count = session.scalar(select(func.count()).select_from(User)) or 0
    prompt_run_count = session.scalar(select(func.count()).select_from(PromptRun)) or 0
    return user_count, prompt_run_count


def clone_user(user: User) -> User:
    """Create a detached User copy for insertion into the target database."""
    return User(
        id=user.id,
        email=user.email,
        name=user.name,
        password_hash=user.password_hash,
        role=user.role,
        created_at=user.created_at,
        is_active=user.is_active,
    )


def clone_prompt_run(run: PromptRun) -> PromptRun:
    """Create a detached PromptRun copy for insertion into the target database."""
    return PromptRun(
        id=run.id,
        created_at=run.created_at,
        user_id=run.user_id,
        external_account_id=run.external_account_id,
        external_user_id=run.external_user_id,
        integration_source=run.integration_source,
        video_filename=run.video_filename,
        stored_video_path=run.stored_video_path,
        video_duration_seconds=run.video_duration_seconds,
        model=run.model,
        boilerplate_prompt=run.boilerplate_prompt,
        user_prompt=run.user_prompt,
        full_prompt=run.full_prompt,
        response_text=run.response_text,
        parsed_response_json=run.parsed_response_json,
        full_response_json=run.full_response_json,
        status=run.status,
        error=run.error,
        feedback_rating=run.feedback_rating,
        feedback_notes=run.feedback_notes,
    )


def migrate(sqlite_url: str, target_url: str, *, replace: bool) -> tuple[int, int]:
    """Copy users and prompt runs from SQLite into the target database."""
    if target_url.startswith("sqlite"):
        raise ValueError("Target DATABASE_URL must point to Postgres, not SQLite")

    alembic_config = make_alembic_config()
    alembic_config.set_main_option("sqlalchemy.url", target_url)
    command.upgrade(alembic_config, "head")

    source_engine = create_engine(sqlite_url, future=True)
    target_engine = create_engine(target_url, future=True)
    SourceSession = sessionmaker(bind=source_engine, expire_on_commit=False)
    TargetSession = sessionmaker(bind=target_engine, expire_on_commit=False)

    with SourceSession() as source_session, TargetSession() as target_session:
        target_users, target_runs = count_rows(target_session)
        if (target_users or target_runs) and not replace:
            raise RuntimeError(
                "Target database is not empty. Re-run with --replace to clear users "
                "and prompt_runs before importing."
            )

        if replace:
            target_session.execute(delete(PromptRun))
            target_session.execute(delete(User))
            target_session.commit()

        users = list(source_session.scalars(select(User).order_by(User.created_at, User.id)))
        runs = list(
            source_session.scalars(select(PromptRun).order_by(PromptRun.created_at, PromptRun.id))
        )

        target_session.add_all(clone_user(user) for user in users)
        target_session.flush()
        target_session.add_all(clone_prompt_run(run) for run in runs)
        target_session.commit()
        return len(users), len(runs)


def main() -> int:
    """Run the SQLite to Postgres migration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        default=str(DB_PATH),
        help="Path to the source SQLite database. Defaults to DATABASE_PATH.",
    )
    parser.add_argument(
        "--target-url",
        default=DATABASE_URL,
        help="Target SQLAlchemy database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Clear target users and prompt_runs before importing.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).expanduser()
    if not sqlite_path.exists():
        parser.error(f"SQLite database not found: {sqlite_path}")

    target_url = normalize_database_url(args.target_url)
    users, runs = migrate(sqlite_url_from_path(str(sqlite_path)), target_url, replace=args.replace)
    print(f"Migrated {users} user(s) and {runs} prompt run(s) to Postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
