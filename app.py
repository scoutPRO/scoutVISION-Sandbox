"""ScoutVision Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from database import ensure_storage
from lib.artifacts import export_run_artifacts
from lib.auth import (
    admin_required,
    authenticate_user,
    bootstrap_admin_user,
    create_user,
    current_user,
    login_required,
    login_user,
    logout_user,
    wants_json_response,
)
from lib.gemini_client import call_gemini
from lib.progress import run_status_payload, set_progress
from lib.prompt_runs import create_run, find_run, recent_runs, update_run
from lib.users import list_users
from lib.video import allowed_video, delete_video, get_video_duration
from models import PromptRun
from settings import (
    ALLOW_SIGNUP,
    DEFAULT_MODEL,
    KEEP_FAILED_UPLOADS,
    KEEP_UPLOADED_VIDEOS,
    MAX_UPLOAD_MB,
    MAX_VIDEO_SECONDS,
    PROMPT_PATH,
    SECRET_KEY,
    UPLOAD_DIR,
)

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = SECRET_KEY


def init_db() -> None:
    """Create runtime directories and apply database migrations."""
    ensure_storage()


def load_boilerplate_prompt() -> str:
    """Load the coach-facing boilerplate prompt from disk."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def process_run(run_id: str, stored_path: str, full_prompt: str, model: str) -> None:
    """Process one queued run and persist the Gemini result or failure."""
    update_run(run_id, status="processing", error=None)
    set_progress(run_id, "validating_video", "Checking video duration.", 15)
    video_path = Path(stored_path)
    try:
        duration = get_video_duration(video_path)
        if duration > MAX_VIDEO_SECONDS:
            raise RuntimeError(
                f"Video is {duration:.1f} seconds; max is {MAX_VIDEO_SECONDS} seconds."
            )
        update_run(run_id, video_duration_seconds=duration)
        set_progress(run_id, "video_ready", "Video validated and ready for Gemini.", 25)
        response_text, parsed_response_json, full_response_json = call_gemini(
            video_path,
            full_prompt,
            model,
            progress_callback=lambda stage, message, percent: set_progress(
                run_id,
                stage,
                message,
                percent,
            ),
        )
        update_run(
            run_id,
            response_text=response_text,
            parsed_response_json=parsed_response_json,
            full_response_json=full_response_json,
            status="completed",
            error=None,
        )
        completed_run = find_run(run_id)
        if completed_run is not None:
            export_run_artifacts(completed_run)
        set_progress(run_id, "completed", "Gemini response is ready.", 100)
    except Exception as exc:
        update_run(run_id, status="failed", error=str(exc))
        set_progress(run_id, "failed", str(exc), 100)
        if not KEEP_UPLOADED_VIDEOS and not KEEP_FAILED_UPLOADS:
            delete_video(video_path)
    else:
        if not KEEP_UPLOADED_VIDEOS:
            delete_video(video_path)


def start_background_run(
    run_id: str,
    stored_path: Path,
    full_prompt: str,
    model: str,
) -> None:
    """Start a daemon thread that processes one prompt run."""
    thread = threading.Thread(
        target=process_run,
        args=(run_id, str(stored_path), full_prompt, model),
        daemon=True,
    )
    thread.start()


@app.before_request
def ensure_db() -> None:
    """Ensure local storage exists before handling a request."""
    init_db()
    bootstrap_admin_user()


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple health-check response."""
    return {"status": "ok"}


@app.get("/")
@login_required
def index():
    """Render the upload form and recent prompt runs."""
    user = current_user()
    runs = recent_runs(user)
    return render_template(
        "index.html",
        boilerplate=load_boilerplate_prompt(),
        current_user=user,
        default_model=DEFAULT_MODEL,
        default_user_prompt=DEFAULT_USER_PROMPT,
        error=request.args.get("error"),
        max_minutes=MAX_VIDEO_SECONDS // 60,
        run_statuses={run.id: run_status_payload(run) for run in runs},
        runs=runs,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log in a user with email and password."""
    if current_user() is not None:
        return redirect(url_for("index"))

    error = None
    next_url = request.values.get("next") or url_for("index")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("index")

    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        user = authenticate_user(email, password)
        if user is None:
            error = "Invalid email or password."
        else:
            login_user(user)
            return redirect(next_url)

    return render_template(
        "login.html",
        allow_signup=ALLOW_SIGNUP,
        error=error,
        next_url=next_url,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Create a tester account and log in."""
    if not ALLOW_SIGNUP:
        return redirect(url_for("login"))
    if current_user() is not None:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "")
        name = request.form.get("name", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            try:
                user = create_user(
                    email=email,
                    name=name,
                    password=password,
                    role="tester",
                )
            except ValueError as exc:
                error = str(exc)
            else:
                login_user(user)
                return redirect(url_for("index"))

    return render_template("signup.html", error=error)


@app.post("/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    return redirect(url_for("login"))


@app.get("/admin/users")
@admin_required
def admin_users():
    """Render an admin-only user list."""
    return render_template(
        "admin_users.html",
        current_user=current_user(),
        users=list_users(),
    )


@app.post("/submit")
@login_required
def submit():
    """Create a queued prompt run and start background processing."""
    user = current_user()
    video = request.files.get("video")
    if not video or not video.filename:
        if wants_json_response():
            return jsonify({"error": "Upload a video file."}), 400
        return redirect(url_for("index", error="Upload a video file."))
    if not allowed_video(video.filename):
        if wants_json_response():
            return jsonify({"error": "Unsupported video file type."}), 400
        return redirect(url_for("index", error="Unsupported video file type."))

    run_id = str(uuid.uuid4())
    safe_name = secure_filename(video.filename)
    stored_path = UPLOAD_DIR / f"{run_id}_{safe_name}"
    video.save(stored_path)

    user_prompt = request.form.get("user_prompt", "").strip()
    model = request.form.get("model", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    boilerplate_prompt = load_boilerplate_prompt()
    full_prompt = f"{boilerplate_prompt}\n\nUSER REQUEST:\n{user_prompt}"

    create_run(
        PromptRun(
            id=run_id,
            created_at=datetime.now(UTC),
            user_id=user.id,
            video_filename=video.filename,
            stored_video_path=str(stored_path),
            model=model,
            boilerplate_prompt=boilerplate_prompt,
            user_prompt=user_prompt,
            full_prompt=full_prompt,
            status="queued",
        )
    )

    set_progress(run_id, "queued", "Upload complete. Queued for processing.", 5)
    start_background_run(run_id, stored_path, full_prompt, model)
    if wants_json_response():
        return jsonify({"redirect_url": url_for("result", run_id=run_id)})
    return redirect(url_for("result", run_id=run_id))


@app.get("/runs/<run_id>")
@login_required
def result(run_id: str):
    """Render one prompt run, including status, response, and feedback form."""
    user = current_user()
    run = find_run(run_id, user)
    if run is None:
        return redirect(url_for("index", error="Run not found."))
    return render_template(
        "result.html",
        current_user=user,
        run=run,
        run_status=run_status_payload(run),
    )


@app.get("/runs/<run_id>/status")
@login_required
def run_status(run_id: str):
    """Return live status details for one prompt run."""
    run = find_run(run_id, current_user())
    if run is None:
        return jsonify({"error": "Run not found."}), 404
    return jsonify(run_status_payload(run))


@app.post("/runs/<run_id>/feedback")
@login_required
def feedback(run_id: str):
    """Save tester feedback for a prompt run."""
    run = find_run(run_id, current_user())
    if run is None:
        return redirect(url_for("index", error="Run not found."))
    rating = request.form.get("rating")
    if rating not in {"like", "dislike"}:
        rating = None
    notes = request.form.get("notes", "").strip()
    update_run(run_id, feedback_rating=rating, feedback_notes=notes)
    return redirect(url_for("result", run_id=run_id))


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5055")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
