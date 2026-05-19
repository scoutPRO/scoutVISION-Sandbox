"""ScoutVision Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
PROMPT_PATH = Path(os.getenv("BOILERPLATE_PROMPT_PATH", "prompts/boilerplate.txt"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "800"))
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def init_db() -> None:
    """Create runtime directories and the prompt run table if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                video_filename TEXT NOT NULL,
                stored_video_path TEXT NOT NULL,
                video_duration_seconds REAL,
                model TEXT NOT NULL,
                boilerplate_prompt TEXT NOT NULL,
                user_prompt TEXT NOT NULL,
                full_prompt TEXT NOT NULL,
                response_text TEXT,
                parsed_response_json TEXT,
                full_response_json TEXT,
                status TEXT NOT NULL,
                error TEXT,
                feedback_rating TEXT,
                feedback_notes TEXT
            )
            """
        )


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection configured to expose rows by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_boilerplate_prompt() -> str:
    """Load the coach-facing boilerplate prompt from disk."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def allowed_video(filename: str) -> bool:
    """Return whether the uploaded filename has a supported video extension."""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def get_video_duration(path: Path) -> float:
    """Return the duration of a video file in seconds."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("Could not open uploaded video.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if not fps or not frame_count:
        raise RuntimeError("Could not determine video duration.")
    return float(frame_count / fps)


def to_jsonable(value: Any) -> Any:
    """Convert a Gemini SDK response object into JSON-serializable data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "to_json_dict"):
        return value.to_json_dict()
    return str(value)


def wait_for_active(client: Any, uploaded_file: Any, max_wait_seconds: int = 180) -> Any:
    """Poll Gemini until an uploaded file is active or fails to become active."""
    start = time.time()
    while getattr(getattr(uploaded_file, "state", None), "name", None) == "PROCESSING":
        if time.time() - start > max_wait_seconds:
            raise RuntimeError("Gemini file ingestion timed out.")
        time.sleep(2)
        uploaded_file = client.files.get(name=uploaded_file.name)

    state_name = getattr(getattr(uploaded_file, "state", None), "name", None)
    if state_name and state_name != "ACTIVE":
        raise RuntimeError(f"Gemini file did not become active. State: {state_name}")
    return uploaded_file


def call_gemini(video_path: Path, prompt: str, model: str) -> tuple[str, str, str]:
    """Upload a video to Gemini and return display, parsed, and raw responses."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required.")

    client = genai.Client(api_key=api_key)
    uploaded_file = wait_for_active(client, client.files.upload(file=str(video_path)))
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=uploaded_file.mime_type,
                    ),
                    types.Part.from_text(text=prompt),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0,
            top_p=0.1,
            candidate_count=1,
        ),
    )

    response_text = response.text or ""
    try:
        parsed_response_json = json.dumps(json.loads(response_text), indent=2)
    except json.JSONDecodeError:
        parsed_response_json = response_text
    full_response_json = json.dumps(to_jsonable(response), indent=2, sort_keys=True)
    return response_text, parsed_response_json, full_response_json


def recent_runs() -> list[sqlite3.Row]:
    """Return recent prompt runs for the index page."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM prompt_runs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()


def find_run(run_id: str) -> sqlite3.Row | None:
    """Return one prompt run by ID, or None when it does not exist."""
    with get_db() as conn:
        return conn.execute("SELECT * FROM prompt_runs WHERE id = ?", (run_id,)).fetchone()


def update_run(run_id: str, **fields: Any) -> None:
    """Update selected columns for a prompt run."""
    if not fields:
        return
    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = [*fields.values(), run_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE prompt_runs SET {assignments} WHERE id = ?",
            values,
        )


def process_run(run_id: str, stored_path: str, full_prompt: str, model: str) -> None:
    """Process one queued run and persist the Gemini result or failure."""
    update_run(run_id, status="processing", error=None)
    try:
        video_path = Path(stored_path)
        duration = get_video_duration(video_path)
        if duration > MAX_VIDEO_SECONDS:
            raise RuntimeError(
                f"Video is {duration:.1f} seconds; max is {MAX_VIDEO_SECONDS} seconds."
            )
        response_text, parsed_response_json, full_response_json = call_gemini(
            video_path, full_prompt, model
        )
        update_run(
            run_id,
            video_duration_seconds=duration,
            response_text=response_text,
            parsed_response_json=parsed_response_json,
            full_response_json=full_response_json,
            status="completed",
            error=None,
        )
    except Exception as exc:
        update_run(run_id, status="failed", error=str(exc))


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


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple health-check response."""
    return {"status": "ok"}


@app.get("/")
def index():
    """Render the upload form and recent prompt runs."""
    return render_template(
        "index.html",
        boilerplate=load_boilerplate_prompt(),
        default_model=DEFAULT_MODEL,
        default_user_prompt=DEFAULT_USER_PROMPT,
        error=request.args.get("error"),
        max_minutes=MAX_VIDEO_SECONDS // 60,
        runs=recent_runs(),
    )


@app.post("/submit")
def submit():
    """Create a queued prompt run and start background processing."""
    video = request.files.get("video")
    if not video or not video.filename:
        return redirect(url_for("index", error="Upload a video file."))
    if not allowed_video(video.filename):
        return redirect(url_for("index", error="Unsupported video file type."))

    run_id = uuid.uuid4().hex
    safe_name = secure_filename(video.filename)
    stored_path = UPLOAD_DIR / f"{run_id}_{safe_name}"
    video.save(stored_path)

    user_prompt = request.form.get("user_prompt", "").strip()
    model = request.form.get("model", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    boilerplate_prompt = load_boilerplate_prompt()
    full_prompt = f"{boilerplate_prompt}\n\nUSER REQUEST:\n{user_prompt}"

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO prompt_runs (
                id, created_at, video_filename, stored_video_path, video_duration_seconds,
                model, boilerplate_prompt, user_prompt, full_prompt, response_text,
                parsed_response_json, full_response_json, status, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                datetime.now(UTC).isoformat(),
                video.filename,
                str(stored_path),
                None,
                model,
                boilerplate_prompt,
                user_prompt,
                full_prompt,
                None,
                None,
                None,
                "queued",
                None,
            ),
        )

    start_background_run(run_id, stored_path, full_prompt, model)
    return redirect(url_for("result", run_id=run_id))


@app.get("/runs/<run_id>")
def result(run_id: str):
    """Render one prompt run, including status, response, and feedback form."""
    run = find_run(run_id)
    if run is None:
        return redirect(url_for("index", error="Run not found."))
    return render_template("result.html", run=run)


@app.post("/runs/<run_id>/feedback")
def feedback(run_id: str):
    """Save tester feedback for a prompt run."""
    rating = request.form.get("rating")
    if rating not in {"like", "dislike"}:
        rating = None
    notes = request.form.get("notes", "").strip()
    with get_db() as conn:
        conn.execute(
            "UPDATE prompt_runs SET feedback_rating = ?, feedback_notes = ? WHERE id = ?",
            (rating, notes, run_id),
        )
    return redirect(url_for("result", run_id=run_id))


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5055")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
