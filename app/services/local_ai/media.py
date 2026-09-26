from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from app.services import video

from .base import SceneSpec


_DURATION_TOLERANCE_SECONDS = 0.25


class LocalAIMediaValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VideoProbe:
    duration: float
    width: int
    height: int


def _aspect_matches(width: int, height: int, aspect: str) -> bool:
    if aspect == "9:16":
        return height > width
    if aspect == "16:9":
        return width > height
    if aspect == "1:1":
        return abs(width - height) / max(width, height) <= 0.05
    return False


def validate_video_clip(path: Path, scene: SceneSpec) -> VideoProbe:
    """Open a generated clip and reject missing, corrupt, short, or wrong-aspect output."""

    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise LocalAIMediaValidationError("generated clip is missing or empty")

    clip = None
    try:
        clip = video._open_video_clip_quietly(str(candidate))
        duration = float(clip.duration or 0)
        width, height = (int(clip.size[0]), int(clip.size[1]))
    except Exception as exc:
        raise LocalAIMediaValidationError(
            f"generated clip is not decodable: {type(exc).__name__}"
        ) from exc
    finally:
        if clip is not None:
            video.close_clip(clip)

    if not math.isfinite(duration) or duration <= 0:
        raise LocalAIMediaValidationError("generated clip has invalid duration")
    if width <= 0 or height <= 0:
        raise LocalAIMediaValidationError("generated clip has invalid dimensions")
    if duration + _DURATION_TOLERANCE_SECONDS < scene.target_duration:
        raise LocalAIMediaValidationError(
            "generated clip is shorter than the requested scene duration"
        )
    if not _aspect_matches(width, height, scene.aspect):
        raise LocalAIMediaValidationError(
            f"generated clip aspect does not match requested {scene.aspect}"
        )

    return VideoProbe(duration=duration, width=width, height=height)
