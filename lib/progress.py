"""Ephemeral prompt run progress tracking for the UI."""

import threading
from typing import Any

from models import PromptRun

_progress_lock = threading.Lock()
_run_progress: dict[str, dict[str, Any]] = {}


def set_progress(run_id: str, stage: str, message: str, percent: int) -> None:
    """Store ephemeral UI progress for one running prompt run."""
    with _progress_lock:
        _run_progress[run_id] = {
            "stage": stage,
            "message": message,
            "progress_percent": percent,
        }


def progress_from_run(run: PromptRun) -> dict[str, Any]:
    """Return progress details, falling back to durable run status."""
    with _progress_lock:
        progress = dict(_run_progress.get(run.id, {}))

    if progress:
        return progress

    if run.status == "completed":
        return {
            "stage": "completed",
            "message": "Gemini response is ready.",
            "progress_percent": 100,
        }
    if run.status == "failed":
        return {
            "stage": "failed",
            "message": run.error or "Processing failed.",
            "progress_percent": 100,
        }
    if run.status == "processing":
        return {
            "stage": "processing",
            "message": "Processing is underway.",
            "progress_percent": 35,
        }
    return {
        "stage": "queued",
        "message": "Queued for processing.",
        "progress_percent": 5,
    }


def run_status_payload(run: PromptRun) -> dict[str, Any]:
    """Return JSON-serializable status details for a prompt run."""
    progress = progress_from_run(run)
    return {
        "id": run.id,
        "status": run.status,
        "stage": progress["stage"],
        "message": progress["message"],
        "progress_percent": progress["progress_percent"],
        "video_duration_seconds": run.video_duration_seconds,
        "error": run.error,
        "is_terminal": run.status in {"completed", "failed"},
    }
