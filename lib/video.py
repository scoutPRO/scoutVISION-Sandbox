"""Video upload and inspection helpers."""

from pathlib import Path

import cv2

from settings import ALLOWED_EXTENSIONS


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


def delete_video(path: Path) -> None:
    """Delete an uploaded video if it still exists."""
    path.unlink(missing_ok=True)
