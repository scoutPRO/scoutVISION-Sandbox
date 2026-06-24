"""scoutVISION Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_restx import Api
from werkzeug.utils import secure_filename

from database import ensure_storage
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
from lib.evaluation_api import register_evaluation_api
from lib.progress import run_status_payload
from lib.prompt_runs import find_run, recent_runs, update_run
from lib.prompts import (
    DEFAULT_USER_PROMPT,
    OUTPUT_MODES,
    load_boilerplate_prompt,
    parse_response_json,
    review_type_label_from_prompt,
    user_prompt_display_sections,
    user_prompt_section_text,
    validate_review_settings,
)
from lib.reviews import as_utc_datetime, create_queued_review
from lib.users import list_users
from lib.video import allowed_video, delete_expired_uploads
from settings import (
    ALLOW_SIGNUP,
    DEFAULT_MODEL,
    GEMINI_MODELS,
    MAX_UPLOAD_MB,
    MAX_VIDEO_SECONDS,
    OUT_DIR,
    SECRET_KEY,
    UPLOAD_DIR,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = SECRET_KEY

LOGGER = logging.getLogger("scoutvision_sandbox")


def enable_app_loggers() -> None:
    """Re-enable app loggers after Alembic applies its logging config."""
    app.logger.disabled = False
    app.logger.setLevel(logging.INFO)
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)


def configure_logging() -> None:
    """Ensure app INFO logs are visible alongside Werkzeug access logs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-5s [%(name)s] %(message)s",
        force=True,
    )
    enable_app_loggers()


configure_logging()
LOGGER.info("Application logging initialized")


def init_db() -> None:
    """Create runtime directories and apply database migrations."""
    ensure_storage()
    enable_app_loggers()


@app.template_filter("friendly_datetime")
def friendly_datetime(value: datetime | None) -> str:
    """Format a datetime for compact display in templates."""
    if value is None:
        return "Unknown"
    return value.strftime("%d %b %Y, %H:%M")


@app.template_filter("iso_datetime")
def iso_datetime(value: datetime | None) -> str:
    """Format a datetime as ISO-8601 for browser-local rendering."""
    if value is None:
        return ""
    return as_utc_datetime(value).isoformat()


@app.before_request
def ensure_db() -> None:
    """Ensure local storage exists before handling a request."""
    init_db()
    delete_expired_uploads(UPLOAD_DIR)
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
        gemini_models=GEMINI_MODELS,
        max_minutes=MAX_VIDEO_SECONDS // 60,
        output_modes=OUTPUT_MODES,
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
    output_mode = request.form.get("output_mode", "general").strip() or "general"
    model = request.form.get("model", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    error = validate_review_settings(output_mode, model)
    if error:
        if wants_json_response():
            return jsonify({"error": error}), 400
        return redirect(url_for("index", error=error))

    review = create_queued_review(
        run_id=run_id,
        user_id=user.id,
        video_filename=video.filename,
        stored_path=stored_path,
        model=model,
        user_prompt=user_prompt,
        output_mode=output_mode,
    )

    if wants_json_response():
        return jsonify({"redirect_url": url_for("result", run_id=review.id)})
    return redirect(url_for("result", run_id=review.id))


@app.get("/runs/<run_id>")
@login_required
def result(run_id: str):
    """Render one prompt run, including status, response, and feedback form."""
    user = current_user()
    run = find_run(run_id, user)
    if run is None:
        return redirect(url_for("index", error="Run not found."))
    video_available = bool(run.stored_video_path and Path(run.stored_video_path).exists())
    return render_template(
        "result.html",
        artifact_path=str(OUT_DIR / run.id) if run.status == "completed" else None,
        current_user=user,
        error=request.args.get("error"),
        gemini_models=GEMINI_MODELS,
        output_modes=OUTPUT_MODES,
        response_data=parse_response_json(run.parsed_response_json),
        run=run,
        run_status=run_status_payload(run),
        review_type_label=review_type_label_from_prompt(run.full_prompt),
        review_again_player_focus=user_prompt_section_text(
            run.user_prompt,
            "Player to Focus On",
        ),
        user_prompt_sections=user_prompt_display_sections(run.user_prompt),
        video_available=video_available,
    )


@app.post("/runs/<run_id>/review-again")
@login_required
def review_again(run_id: str):
    """Create a new review using a retained video from a previous review."""
    user = current_user()
    source_run = find_run(run_id, user)
    if source_run is None:
        return redirect(url_for("index", error="Run not found."))
    if source_run.user_id != user.id and user.role != "admin":
        error = "Only the original submitter can review this video again."
        return redirect(url_for("result", run_id=run_id, error=error))

    if not source_run.stored_video_path:
        error = "The original video is no longer available for another review."
        return redirect(url_for("result", run_id=run_id, error=error))

    stored_path = Path(source_run.stored_video_path)
    if not stored_path.exists():
        error = "The original video is no longer available for another review."
        return redirect(url_for("result", run_id=run_id, error=error))

    user_prompt = request.form.get("user_prompt", "").strip()
    output_mode = request.form.get("output_mode", "general").strip() or "general"
    model = request.form.get("model", source_run.model).strip() or source_run.model
    error = validate_review_settings(output_mode, model)
    if error:
        return redirect(url_for("result", run_id=run_id, error=error))

    review = create_queued_review(
        user_id=user.id,
        video_filename=source_run.video_filename,
        stored_path=stored_path,
        model=model,
        user_prompt=user_prompt,
        output_mode=output_mode,
        video_duration_seconds=source_run.video_duration_seconds,
    )
    return redirect(url_for("result", run_id=review.id))


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


api_authorizations = {
    "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
}
api = Api(
    app,
    version="1.0",
    title="scoutVISION Evaluation API",
    description="Programmatic video evaluation API for scoutSMART integration.",
    doc="/api/docs",
    authorizations=api_authorizations,
)
register_evaluation_api(api)


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5055")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
