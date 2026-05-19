"""ScoutVision Gemini prompt sandbox.

This is a small beta tester app for iterating on Gemini prompts against
recruit highlight reels.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, request, url_for
from werkzeug.utils import secure_filename

import cv2
from google import genai
from google.genai import types


load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prompt_lab.sqlite3"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "800"))
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}

BOILERPLATE_PROMPT = """You are helping a college or team coach evaluate a recruit's highlight reel.

Analyze only what is visible in the uploaded video. Be careful, specific, and avoid inventing context that is not in the clip.

Return JSON with this shape:
{
  "summary": "short coach-facing summary",
  "strengths": ["specific strengths visible in the reel"],
  "concerns_or_unknowns": ["limitations, unclear signals, or things the video does not prove"],
  "notable_moments": [
    {
      "timestamp": "mm:ss",
      "observation": "what happened",
      "why_it_matters": "why a coach might care"
    }
  ],
  "coach_follow_up_questions": ["questions the coach should ask or verify"],
  "fit_signals": ["signals related to role, athletic traits, decision making, effort, or coachability"]
}

Use plain language suitable for a coach reviewing many recruits. Keep the response concise unless the user's ask requests more detail."""

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def init_db() -> None:
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def allowed_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def get_video_duration(path: Path) -> float:
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
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM prompt_runs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()


def find_run(run_id: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM prompt_runs WHERE id = ?", (run_id,)).fetchone()


INDEX_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>ScoutVision Gemini Sandbox</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 960px; margin: 32px auto; line-height: 1.4; }
      label { display: block; margin-top: 16px; font-weight: 600; }
      input[type="file"], input[type="text"], textarea { width: 100%; box-sizing: border-box; }
      textarea { min-height: 150px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
      button { margin-top: 16px; padding: 8px 12px; }
      pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f5f5; padding: 12px; }
      .error { color: #a40000; font-weight: 600; }
      .run { border-top: 1px solid #ddd; padding: 10px 0; }
    </style>
  </head>
  <body>
    <h1>ScoutVision Gemini Sandbox</h1>
    <form action="{{ url_for('submit') }}" method="post" enctype="multipart/form-data">
      <label>Highlight reel, max {{ max_minutes }} minutes</label>
      <input type="file" name="video" accept="video/*" required>

      <label>Coach ask</label>
      <textarea name="user_prompt" required>{{ default_user_prompt }}</textarea>

      <label>Gemini model</label>
      <input type="text" name="model" value="{{ default_model }}" required>

      <details>
        <summary>Boilerplate prompt that will be prepended</summary>
        <pre>{{ boilerplate }}</pre>
      </details>

      <button type="submit">Submit</button>
    </form>

    {% if error %}
      <p class="error">{{ error }}</p>
    {% endif %}

    <h2>Recent runs</h2>
    {% for run in runs %}
      <div class="run">
        <a href="{{ url_for('result', run_id=run['id']) }}">{{ run['created_at'] }} - {{ run['video_filename'] }}</a>
        <div>Status: {{ run['status'] }}{% if run['feedback_rating'] %}; feedback: {{ run['feedback_rating'] }}{% endif %}</div>
      </div>
    {% else %}
      <p>No runs yet.</p>
    {% endfor %}
  </body>
</html>
"""

RESULT_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Prompt Run {{ run['id'] }}</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 960px; margin: 32px auto; line-height: 1.4; }
      textarea { width: 100%; min-height: 100px; box-sizing: border-box; }
      pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f5f5; padding: 12px; }
      .error { color: #a40000; font-weight: 600; }
      label { display: block; margin-top: 8px; }
      button { margin-top: 12px; padding: 8px 12px; }
    </style>
  </head>
  <body>
    <p><a href="{{ url_for('index') }}">Back</a></p>
    <h1>Prompt Run</h1>
    <p><strong>Status:</strong> {{ run['status'] }}</p>
    <p><strong>Video:</strong> {{ run['video_filename'] }}</p>
    <p><strong>Duration:</strong> {{ "%.1f"|format(run['video_duration_seconds'] or 0) }} seconds</p>
    <p><strong>Model:</strong> {{ run['model'] }}</p>

    {% if run['error'] %}
      <h2>Error</h2>
      <p class="error">{{ run['error'] }}</p>
    {% endif %}

    <h2>Response</h2>
    <pre>{{ run['parsed_response_json'] or run['response_text'] or '' }}</pre>

    <details>
      <summary>Full Gemini response JSON</summary>
      <pre>{{ run['full_response_json'] or '{}' }}</pre>
    </details>

    <details>
      <summary>Full prompt sent to Gemini</summary>
      <pre>{{ run['full_prompt'] }}</pre>
    </details>

    <h2>Feedback</h2>
    <form action="{{ url_for('feedback', run_id=run['id']) }}" method="post">
      <label><input type="radio" name="rating" value="like" {% if run['feedback_rating'] == 'like' %}checked{% endif %}> Like</label>
      <label><input type="radio" name="rating" value="dislike" {% if run['feedback_rating'] == 'dislike' %}checked{% endif %}> Dislike</label>
      <label>Notes</label>
      <textarea name="notes">{{ run['feedback_notes'] or '' }}</textarea>
      <button type="submit">Save feedback</button>
    </form>
  </body>
</html>
"""


@app.before_request
def ensure_db() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index():
    return render_template_string(
        INDEX_HTML,
        boilerplate=BOILERPLATE_PROMPT,
        default_model=DEFAULT_MODEL,
        default_user_prompt=DEFAULT_USER_PROMPT,
        error=request.args.get("error"),
        max_minutes=MAX_VIDEO_SECONDS // 60,
        runs=recent_runs(),
    )


@app.post("/submit")
def submit():
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
    full_prompt = f"{BOILERPLATE_PROMPT}\n\nUSER REQUEST:\n{user_prompt}"
    duration = None
    response_text = None
    parsed_response_json = None
    full_response_json = None
    status = "completed"
    error = None

    try:
        duration = get_video_duration(stored_path)
        if duration > MAX_VIDEO_SECONDS:
            raise RuntimeError(
                f"Video is {duration:.1f} seconds; max is {MAX_VIDEO_SECONDS} seconds."
            )
        response_text, parsed_response_json, full_response_json = call_gemini(
            stored_path, full_prompt, model
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)

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
                datetime.now(timezone.utc).isoformat(),
                video.filename,
                str(stored_path),
                duration,
                model,
                BOILERPLATE_PROMPT,
                user_prompt,
                full_prompt,
                response_text,
                parsed_response_json,
                full_response_json,
                status,
                error,
            ),
        )

    return redirect(url_for("result", run_id=run_id))


@app.get("/runs/<run_id>")
def result(run_id: str):
    run = find_run(run_id)
    if run is None:
        return redirect(url_for("index", error="Run not found."))
    return render_template_string(RESULT_HTML, run=run)


@app.post("/runs/<run_id>/feedback")
def feedback(run_id: str):
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
