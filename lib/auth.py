"""Authentication and session helpers."""

import uuid
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import SessionLocal
from models import User
from settings import (
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_NAME,
    BOOTSTRAP_ADMIN_PASSWORD,
)


def normalize_email(email: str) -> str:
    """Return a normalized email address."""
    return email.strip().lower()


def find_user(user_id: str) -> User | None:
    """Return a user by ID."""
    with SessionLocal() as db_session:
        return db_session.get(User, user_id)


def find_user_by_email(email: str) -> User | None:
    """Return an active user by email."""
    with SessionLocal() as db_session:
        return (
            db_session.query(User)
            .filter(User.email == normalize_email(email), User.is_active.is_(True))
            .one_or_none()
        )


def create_user(email: str, name: str, password: str, role: str = "tester") -> User:
    """Create a user with a hashed password."""
    normalized_email = normalize_email(email)
    if find_user_by_email(normalized_email):
        raise ValueError("An account with that email already exists.")
    user = User(
        id=str(uuid.uuid4()),
        email=normalized_email,
        name=name.strip() or normalized_email,
        password_hash=generate_password_hash(password),
        role=role,
        created_at=datetime.now(UTC),
        is_active=True,
    )
    with SessionLocal() as db_session:
        db_session.add(user)
        db_session.commit()
    return user


def bootstrap_admin_user() -> None:
    """Create the configured bootstrap admin if it does not already exist."""
    if not BOOTSTRAP_ADMIN_EMAIL or not BOOTSTRAP_ADMIN_PASSWORD:
        return
    if find_user_by_email(BOOTSTRAP_ADMIN_EMAIL):
        return
    create_user(
        email=BOOTSTRAP_ADMIN_EMAIL,
        name=BOOTSTRAP_ADMIN_NAME,
        password=BOOTSTRAP_ADMIN_PASSWORD,
        role="admin",
    )


def authenticate_user(email: str, password: str) -> User | None:
    """Return a user when credentials are valid."""
    user = find_user_by_email(email)
    if user is None:
        return None
    if not check_password_hash(user.password_hash, password):
        return None
    return user


def current_user() -> User | None:
    """Return the logged-in user for the current session."""
    user_id = session.get("user_id")
    if not isinstance(user_id, str):
        return None
    return find_user(user_id)


def login_user(user: User) -> None:
    """Persist a user ID in the Flask session."""
    session.clear()
    session["user_id"] = user.id


def logout_user() -> None:
    """Clear the Flask session."""
    session.clear()


def is_admin(user: User | None) -> bool:
    """Return whether a user has admin privileges."""
    return user is not None and user.role == "admin"


def wants_json_response() -> bool:
    """Return whether the current request expects a JSON response."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def login_required(route_handler: Any) -> Any:
    """Require a logged-in user before calling a route handler."""

    @wraps(route_handler)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_user() is not None:
            return route_handler(*args, **kwargs)
        if wants_json_response():
            return jsonify({"error": "Login required."}), 401
        return redirect(url_for("login", next=request.full_path))

    return wrapper
