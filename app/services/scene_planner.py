from __future__ import annotations

import math
import re

from app.services.local_ai.base import SceneSpec


_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?", re.UNICODE)


def _split_narration(text: str, count: int) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ["Visual scene"] * count

    sentences = [part.strip() for part in _SENTENCE_RE.findall(cleaned) if part.strip()]
    if len(sentences) > 1:
        units = sentences
        separator = " "
    else:
        words = cleaned.split()
        if len(words) > 1:
            units = words
            separator = " "
        else:
            units = list(cleaned)
            separator = ""

    buckets: list[list[str]] = [[] for _ in range(count)]
    for index, unit in enumerate(units):
        bucket = min(count - 1, (index * count) // max(1, len(units)))
        buckets[bucket].append(unit)

    segments = [separator.join(bucket).strip() for bucket in buckets]
    return [segment or cleaned for segment in segments]


def plan_scenes(
    video_script: str,
    *,
    audio_duration: float,
    max_scene_duration: float,
    aspect: str,
    base_seed: int = 42,
) -> list[SceneSpec]:
    """Create the deterministic M1 scene plan after narration duration is known."""

    duration = float(audio_duration)
    max_duration = float(max_scene_duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("audio_duration must be a positive finite number")
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("max_scene_duration must be a positive finite number")

    scene_count = max(1, math.ceil(duration / max_duration))
    even_duration = duration / scene_count
    durations = [round(even_duration, 3) for _ in range(scene_count)]
    if scene_count > 1:
        durations[-1] = round(duration - sum(durations[:-1]), 3)
    narration_segments = _split_narration(video_script, scene_count)

    scenes = []
    for index in range(scene_count):
        segment = narration_segments[index]
        scenes.append(
            SceneSpec(
                scene_id=index + 1,
                narration_segment=segment,
                prompt=f"Cinematic visual matching this narration: {segment}",
                target_duration=durations[index],
                aspect=aspect,
                seed=int(base_seed) + index,
            )
        )
    return scenes
