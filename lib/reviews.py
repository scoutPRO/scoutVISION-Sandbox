"""Review creation, background processing, and API payload helpers."""

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from lib.artifacts import export_run_artifacts
from lib.gemini_client import call_gemini
from lib.progress import set_progress
from lib.prompt_runs import create_run, find_run, update_run
from lib.prompts import build_full_prompt, load_boilerplate_prompt, review_type_label_from_prompt
from lib.video import delete_video, get_video_duration
from models import PromptRun
from settings import KEEP_FAILED_UPLOADS, KEEP_UPLOADED_VIDEOS, MAX_VIDEO_SECONDS

LOGGER = logging.getLogger("scoutvision_sandbox")


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


def as_utc_datetime(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime, assuming naive DB values are UTC."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
