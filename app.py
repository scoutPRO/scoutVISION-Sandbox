"""ScoutVision Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

import json
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
    GEMINI_MODELS,
    KEEP_FAILED_UPLOADS,
    KEEP_UPLOADED_VIDEOS,
    MAX_UPLOAD_MB,
    MAX_VIDEO_SECONDS,
    OUT_DIR,
    PROMPT_PATH,
    SECRET_KEY,
    UPLOAD_DIR,
)

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."
OUTPUT_MODES = {
    "general": {
        "label": "General Review",
        "instruction": (
            "Provide a balanced coach-facing review with summary, strengths, concerns, "
            "notable moments, follow-up questions, and fit signals.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short coach-facing summary",\n'
            '  "strengths": ["specific strengths visible in the reel"],\n'
            '  "concerns_or_unknowns": ['
            '"limitations, unclear signals, or things the video does not prove"'
            "],\n"
            '  "notable_moments": [\n'
            "    {\n"
            '      "timestamp": "mm:ss",\n'
            '      "observation": "what happened",\n'
            '      "why_it_matters": "why a coach might care"\n'
            "    }\n"
            "  ],\n"
            '  "coach_follow_up_questions": ["questions the coach should ask or verify"],\n'
            '  "fit_signals": ['
            '"signals related to role, athletic traits, decision making, effort, or coachability"'
            "]\n"
            "}"
        ),
    },
    "swot": {
        "label": "SWOT",
        "instruction": (
            "Frame the response as a SWOT review: strengths, weaknesses, opportunities, "
            "and threats or risks. Use only evidence visible in the video.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short coach-facing SWOT summary",\n'
            '  "strengths": ["visible strengths or advantages"],\n'
            '  "weaknesses": ["visible limitations or underdeveloped areas"],\n'
            '  "opportunities": ["ways the player could be used, developed, or evaluated"],\n'
            '  "threats": ["risks, unknowns, or reasons to request more evidence"],\n'
            '  "coach_follow_up_questions": ["questions to ask after watching the reel"]\n'
            "}"
        ),
    },
    "position_fit": {
        "label": "Position Fit",
        "instruction": (
            "Focus on position fit, likely role, transferable skills, and what additional "
            "film a coach would need before making a roster decision.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short position-fit summary",\n'
            '  "best_fit_positions": ["positions or roles that fit the visible traits"],\n'
            '  "role_projection": "how the player might be used by a team",\n'
            '  "supporting_evidence": [\n'
            "    {\n"
            '      "timestamp": "mm:ss",\n'
            '      "observation": "visible evidence for the fit",\n'
            '      "fit_signal": "trait, role, or skill shown"\n'
            "    }\n"
            "  ],\n"
            '  "concerns_or_unknowns": ["fit-related unknowns or missing evidence"],\n'
            '  "additional_film_to_request": ["specific clips a coach should ask for"]\n'
            "}"
        ),
    },
    "follow_up_questions": {
        "label": "Follow-Up Questions",
        "instruction": (
            "Focus on practical follow-up questions a coach should ask the player, "
            "club/team, or recruiting contact after watching this reel.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short summary of what the reel shows and does not prove",\n'
            '  "questions_for_player": ["questions to ask the player directly"],\n'
            '  "questions_for_coach_or_team": ["questions for a coach, club, or team contact"],\n'
            '  "film_to_request": ["specific extra film or situations to request"],\n'
            '  "verification_items": ["claims, context, or traits to verify"]\n'
            "}"
        ),
    },
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = SECRET_KEY


def init_db() -> None:
    """Create runtime directories and apply database migrations."""
    ensure_storage()


def load_boilerplate_prompt() -> str:
    """Load the coach-facing boilerplate prompt from disk."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def parse_response_json(response_json: str | None) -> dict | list | None:
    """Parse the stored Gemini response JSON for structured display."""
    if not response_json:
        return None
    try:
        return json.loads(response_json)
    except json.JSONDecodeError:
        return None


@app.template_filter("friendly_datetime")
def friendly_datetime(value: datetime | None) -> str:
    """Format a datetime for compact display in templates."""
    if value is None:
        return "Unknown"
    return value.strftime("%d %b %Y, %H:%M")


def as_utc_datetime(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime, assuming naive DB values are UTC."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@app.template_filter("iso_datetime")
def iso_datetime(value: datetime | None) -> str:
    """Format a datetime as ISO-8601 for browser-local rendering."""
    if value is None:
        return ""
    return as_utc_datetime(value).isoformat()


def build_full_prompt(boilerplate_prompt: str, output_mode: str, user_prompt: str) -> str:
    """Build the complete prompt sent to Gemini for one review."""
    output_mode_instruction = OUTPUT_MODES[output_mode]["instruction"]
    return (
        f"{boilerplate_prompt}\n\n"
        f"OUTPUT MODE:\n{output_mode_instruction}\n\n"
        f"USER REQUEST:\n{user_prompt}"
    )


def validate_review_settings(output_mode: str, model: str) -> str | None:
    """Return a validation error for submitted review settings, if any."""
    if output_mode not in OUTPUT_MODES:
        return "Choose one of the available output modes."
    if model not in GEMINI_MODELS:
        return "Choose one of the available Gemini models."
    return None


def create_queued_review(
    *,
    run_id: str | None = None,
    user_id: str,
    video_filename: str,
    stored_path: Path,
    model: str,
    user_prompt: str,
    output_mode: str,
    video_duration_seconds: float | None = None,
) -> PromptRun:
    """Create and start a queued review for an already stored video."""
    run_id = run_id or str(uuid.uuid4())
    boilerplate_prompt = load_boilerplate_prompt()
    full_prompt = build_full_prompt(boilerplate_prompt, output_mode, user_prompt)
    review = PromptRun(
        id=run_id,
        created_at=datetime.now(UTC),
        user_id=user_id,
        video_filename=video_filename,
        stored_video_path=str(stored_path),
        video_duration_seconds=video_duration_seconds,
        model=model,
        boilerplate_prompt=boilerplate_prompt,
        user_prompt=user_prompt,
        full_prompt=full_prompt,
        status="queued",
    )
    create_run(review)
    set_progress(run_id, "queued", "Video ready. Queued for processing.", 5)
    start_background_run(run_id, stored_path, full_prompt, model)
    return review


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


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5055")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
