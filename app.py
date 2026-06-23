"""scoutVISION Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_restx import Api, Resource, fields, reqparse
from werkzeug.datastructures import FileStorage
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
from lib.video import allowed_video, delete_expired_uploads, delete_video, get_video_duration
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
    SCOUTSMART_API_KEY,
    SECRET_KEY,
    UPLOAD_DIR,
)

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."
USER_PROMPT_SECTION_LABELS = {
    "PLAYER TO FOCUS ON": "Player to Focus On",
    "EVALUATION REQUEST": "Evaluation Request",
}
USER_PROMPT_SECTION_RE = re.compile(
    r"(PLAYER TO FOCUS ON|EVALUATION REQUEST):\s*",
    re.IGNORECASE,
)
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

LOGGER = logging.getLogger("scoutvision_sandbox")


def configure_logging() -> None:
    """Ensure app INFO logs are visible alongside Werkzeug access logs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-5s [%(name)s] %(message)s",
        force=True,
    )
    app.logger.disabled = False
    app.logger.setLevel(logging.INFO)
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)


configure_logging()
LOGGER.info("Application logging initialized")
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
evaluation_ns = api.namespace(
    "api/v1",
    description="Video evaluation endpoints.",
)

evaluation_upload_parser = reqparse.RequestParser()
evaluation_upload_parser.add_argument(
    "video",
    type=FileStorage,
    location="files",
    required=True,
    help="Video file to evaluate.",
)
evaluation_upload_parser.add_argument(
    "account_id",
    location="form",
    required=True,
    help="scoutSMART account identifier for attribution.",
)
evaluation_upload_parser.add_argument(
    "user_id",
    location="form",
    required=False,
    help="Optional scoutSMART user identifier for attribution.",
)
evaluation_upload_parser.add_argument(
    "review_type",
    location="form",
    required=False,
    default="general",
    help="Review type. One of: general, swot, position_fit, follow_up_questions.",
)
evaluation_upload_parser.add_argument(
    "player_focus",
    location="form",
    required=False,
    help="Optional description of the player Gemini should focus on.",
)
evaluation_upload_parser.add_argument(
    "evaluation_request",
    location="form",
    required=False,
    help="Optional coaching/evaluation instruction.",
)
evaluation_response_model = evaluation_ns.model(
    "EvaluationResponse",
    {
        "evaluation_id": fields.String,
        "status": fields.String,
        "review_type": fields.String,
        "video_filename": fields.String,
        "video_duration_seconds": fields.Float,
        "created_at": fields.String,
        "error": fields.String,
        "result": fields.Raw,
        "response_text": fields.String,
        "usage": fields.Raw,
    },
)
evaluation_accepted_model = evaluation_ns.model(
    "EvaluationAccepted",
    {
        "evaluation_id": fields.String,
        "status": fields.String,
        "status_url": fields.String,
    },
)
evaluation_error_model = evaluation_ns.model(
    "EvaluationError",
    {
        "evaluation_id": fields.String,
        "error": fields.String,
        "status": fields.String,
    },
)


def init_db() -> None:
    """Create runtime directories and apply database migrations."""
    ensure_storage()
    configure_logging()


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


def review_type_label_from_prompt(full_prompt: str) -> str:
    """Return the review type label represented by a stored full prompt."""
    for mode_meta in OUTPUT_MODES.values():
        if mode_meta["instruction"] in full_prompt:
            return mode_meta["label"]
    return "Unknown"


def user_prompt_display_sections(user_prompt: str | None) -> list[dict[str, str]]:
    """Return user prompt sections with friendly labels for display."""
    if not user_prompt:
        return []

    cleaned_prompt = user_prompt.strip()
    matches = list(USER_PROMPT_SECTION_RE.finditer(cleaned_prompt))
    if not matches:
        return [{"label": "", "text": cleaned_prompt}]

    sections = []
    leading_text = cleaned_prompt[: matches[0].start()].strip()
    if leading_text:
        sections.append({"label": "", "text": leading_text})

    for index, match in enumerate(matches):
        text_start = match.end()
        text_end = matches[index + 1].start() if index + 1 < len(matches) else None
        text = cleaned_prompt[text_start:text_end].strip()
        if not text:
            continue
        label = USER_PROMPT_SECTION_LABELS[match.group(1).upper()]
        sections.append({"label": label, "text": text})

    return sections


def user_prompt_section_text(user_prompt: str | None, label: str) -> str:
    """Return one parsed user prompt section value by friendly label."""
    for section in user_prompt_display_sections(user_prompt):
        if section["label"] == label:
            return section["text"]
    return ""


def validate_review_settings(output_mode: str, model: str) -> str | None:
    """Return a validation error for submitted review settings, if any."""
    if output_mode not in OUTPUT_MODES:
        return "Choose one of the available output modes."
    if model not in GEMINI_MODELS:
        return "Choose one of the available Gemini models."
    return None


def validate_api_key() -> tuple[dict[str, str], int] | None:
    """Return an API auth error when a shared scoutSMART API key is configured."""
    if not SCOUTSMART_API_KEY:
        return None

    supplied_key = request.headers.get("X-API-Key", "")
    if supplied_key != SCOUTSMART_API_KEY:
        return {"error": "Invalid or missing API key.", "status": "failed"}, 401
    return None


def build_api_user_prompt(player_focus: str, evaluation_request: str) -> str:
    """Build the user prompt from scoutSMART API form fields."""
    sections = []
    if player_focus:
        sections.append(f"PLAYER TO FOCUS ON: {player_focus}")
    sections.append(f"EVALUATION REQUEST: {evaluation_request or DEFAULT_USER_PROMPT}")
    return "\n\n".join(sections)


def parse_api_result(parsed_response_json: str | None) -> dict | list | str | None:
    """Return a JSON result payload when possible, otherwise response text."""
    if not parsed_response_json:
        return None
    try:
        return json.loads(parsed_response_json)
    except json.JSONDecodeError:
        return parsed_response_json


def extract_usage_metadata(full_response_json: str | None) -> dict:
    """Extract Gemini usage metadata from a stored full response payload."""
    if not full_response_json:
        return {}
    try:
        full_response = json.loads(full_response_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(full_response, dict):
        return {}
    usage = full_response.get("usage_metadata") or full_response.get("usageMetadata") or {}
    return usage if isinstance(usage, dict) else {}


def api_evaluation_payload(run: PromptRun) -> dict:
    """Return the public API payload for one evaluation run."""
    payload = {
        "evaluation_id": run.id,
        "status": run.status,
        "review_type": review_type_label_from_prompt(run.full_prompt),
        "video_filename": run.video_filename,
        "video_duration_seconds": run.video_duration_seconds,
        "created_at": as_utc_datetime(run.created_at).isoformat(),
        "error": run.error,
    }
    if run.status == "completed":
        payload.update(
            {
                "result": parse_api_result(run.parsed_response_json),
                "response_text": run.response_text,
                "usage": extract_usage_metadata(run.full_response_json),
            }
        )
    return payload


def create_queued_review(
    *,
    run_id: str | None = None,
    user_id: str | None,
    video_filename: str,
    stored_path: Path,
    model: str,
    user_prompt: str,
    output_mode: str,
    video_duration_seconds: float | None = None,
    external_account_id: str | None = None,
    external_user_id: str | None = None,
    integration_source: str | None = None,
) -> PromptRun:
    """Create and start a queued review for an already stored video."""
    run_id = run_id or str(uuid.uuid4())
    boilerplate_prompt = load_boilerplate_prompt()
    full_prompt = build_full_prompt(boilerplate_prompt, output_mode, user_prompt)
    review = PromptRun(
        id=run_id,
        created_at=datetime.now(UTC),
        user_id=user_id,
        external_account_id=external_account_id,
        external_user_id=external_user_id,
        integration_source=integration_source,
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
    set_progress(
        run_id,
        "queued",
        "Step 2 of 2: Video saved. Waiting to start the Gemini review.",
        5,
    )
    LOGGER.info(
        "Evaluation %s queued for %s using %s",
        run_id,
        video_filename,
        model,
    )
    start_background_run(run_id, stored_path, full_prompt, model)
    return review


def process_run(run_id: str, stored_path: str, full_prompt: str, model: str) -> None:
    """Process one queued run and persist the Gemini result or failure."""
    LOGGER.info("Evaluation %s processing started", run_id)
    update_run(run_id, status="processing", error=None)
    set_progress(
        run_id,
        "validating_video",
        "Step 2 of 2: Checking video duration.",
        15,
    )
    video_path = Path(stored_path)
    try:
        duration = get_video_duration(video_path)
        if duration > MAX_VIDEO_SECONDS:
            raise RuntimeError(
                f"Video is {duration:.1f} seconds; max is {MAX_VIDEO_SECONDS} seconds."
            )
        update_run(run_id, video_duration_seconds=duration)
        LOGGER.info(
            "Evaluation %s video validated: %.2f seconds",
            run_id,
            duration,
        )
        set_progress(
            run_id,
            "video_ready",
            "Step 2 of 2: Video validated and ready for Gemini.",
            25,
        )
        LOGGER.info("Evaluation %s Gemini review started", run_id)
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
        set_progress(run_id, "completed", "Gemini review is ready.", 100)
        LOGGER.info("Evaluation %s completed", run_id)
    except Exception as exc:
        diagnostics = getattr(exc, "gemini_file_diagnostics", None)
        if diagnostics:
            LOGGER.error("Review %s Gemini file diagnostics: %s", run_id, diagnostics)
        LOGGER.exception("Review %s failed while processing %s.", run_id, video_path)
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
    LOGGER.info("Evaluation %s background thread started", run_id)


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


@evaluation_ns.route("/evaluations")
@evaluation_ns.doc(security="ApiKeyAuth")
class EvaluationResource(Resource):
    """Create a scoutSMART video evaluation."""

    @evaluation_ns.expect(evaluation_upload_parser)
    @evaluation_ns.response(202, "Evaluation queued.", evaluation_accepted_model)
    @evaluation_ns.response(400, "Invalid request.", evaluation_error_model)
    @evaluation_ns.response(401, "Unauthorized.", evaluation_error_model)
    def post(self):
        """Upload one video and queue an asynchronous Gemini evaluation."""
        auth_error = validate_api_key()
        if auth_error is not None:
            return auth_error

        video = request.files.get("video")
        if not video or not video.filename:
            return {"error": "Upload a video file.", "status": "failed"}, 400
        if not allowed_video(video.filename):
            return {"error": "Unsupported video file type.", "status": "failed"}, 400

        account_id = request.form.get("account_id", "").strip()
        if not account_id:
            return {"error": "account_id is required.", "status": "failed"}, 400

        run_id = str(uuid.uuid4())
        safe_name = secure_filename(video.filename)
        stored_path = UPLOAD_DIR / f"{run_id}_{safe_name}"
        video.save(stored_path)

        output_mode = request.form.get("review_type", "general").strip() or "general"
        error = validate_review_settings(output_mode, DEFAULT_MODEL)
        if error:
            delete_video(stored_path)
            return {"evaluation_id": run_id, "error": error, "status": "failed"}, 400

        user_prompt = build_api_user_prompt(
            request.form.get("player_focus", "").strip(),
            request.form.get("evaluation_request", "").strip(),
        )
        review = create_queued_review(
            run_id=run_id,
            user_id=None,
            video_filename=video.filename,
            stored_path=stored_path,
            model=DEFAULT_MODEL,
            user_prompt=user_prompt,
            output_mode=output_mode,
            external_account_id=account_id,
            external_user_id=request.form.get("user_id", "").strip() or None,
            integration_source="scoutsmart_api",
        )

        return {
            "evaluation_id": review.id,
            "status": review.status,
            "status_url": url_for("api/v1_evaluation_status_resource", evaluation_id=review.id),
        }, 202


@evaluation_ns.route("/evaluations/<string:evaluation_id>")
@evaluation_ns.doc(security="ApiKeyAuth")
class EvaluationStatusResource(Resource):
    """Return status and result for a scoutSMART video evaluation."""

    @evaluation_ns.response(200, "Evaluation status.", evaluation_response_model)
    @evaluation_ns.response(401, "Unauthorized.", evaluation_error_model)
    @evaluation_ns.response(404, "Evaluation not found.", evaluation_error_model)
    def get(self, evaluation_id: str):
        """Return one queued, processing, completed, or failed evaluation."""
        auth_error = validate_api_key()
        if auth_error is not None:
            return auth_error

        run = find_run(evaluation_id)
        if run is None or run.integration_source != "scoutsmart_api":
            return {
                "evaluation_id": evaluation_id,
                "error": "Evaluation not found.",
                "status": "failed",
            }, 404
        return api_evaluation_payload(run)


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


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5055")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
