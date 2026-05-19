"""Filesystem artifact export helpers."""

import json
from datetime import UTC, datetime
from pathlib import Path

from models import PromptRun
from settings import OUT_DIR


def _write_json(path: Path, content: str) -> None:
    """Write a JSON string as pretty JSON when possible."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        path.with_suffix(".txt").write_text(content, encoding="utf-8")
        return
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def export_run_artifacts(run: PromptRun) -> Path:
    """Write prompt, response, raw response, and metadata files for a run."""
    run_dir = OUT_DIR / run.id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "prompt.txt").write_text(run.full_prompt, encoding="utf-8")

    if run.parsed_response_json:
        _write_json(run_dir / "response.json", run.parsed_response_json)
    if run.full_response_json:
        _write_json(run_dir / "gemini_response_full.json", run.full_response_json)

    metadata = {
        "id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "exported_at": datetime.now(UTC).isoformat(),
        "video_filename": run.video_filename,
        "stored_video_path": run.stored_video_path,
        "video_duration_seconds": run.video_duration_seconds,
        "model": run.model,
        "status": run.status,
        "error": run.error,
        "feedback_rating": run.feedback_rating,
        "feedback_notes": run.feedback_notes,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_dir
