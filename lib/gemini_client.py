"""Gemini API helpers."""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

ProgressCallback = Callable[[str, str, int], None]


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


def call_gemini(
    video_path: Path,
    prompt: str,
    model: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, str, str]:
    """Upload a video to Gemini and return display, parsed, and raw responses."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required.")

    client = genai.Client(api_key=api_key)
    if progress_callback:
        progress_callback("uploading_to_gemini", "Uploading video to Gemini.", 35)
    uploaded_file = client.files.upload(file=str(video_path))
    if progress_callback:
        progress_callback("waiting_for_gemini", "Waiting for Gemini to ingest the video.", 55)
    uploaded_file = wait_for_active(client, uploaded_file)
    if progress_callback:
        progress_callback("generating_response", "Gemini is analyzing the video.", 75)
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
