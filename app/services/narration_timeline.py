"""Natural-duration narration and monotonic retiming of existing visual cuts."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from app.services import generation_manifest as gm, narration_ranges as nr, scene_planner, video

NAME = "narration_timeline_preview.json"


def has_natural(data: dict) -> bool:
    return any(i.get("replacement", {}).get("timing_mode") == "natural" for i in data["ranges"])


def audio_timeline(data: dict) -> dict:
    elapsed = 0
    segments = []
    for item in data["ranges"]:
        replacement = item.get("replacement", {})
        frames = round(item["end"] * 16000) - round(item["start"] * 16000)
        if replacement.get("timing_mode") == "natural":
            frames = round(replacement["audio_duration"] * 16000)
        if frames <= 0:
            raise ValueError("narration segment is shorter than one sample")
        segments.append({"scene_id": item["scene_id"], "source_start": item["start"],
                         "source_end": item["end"], "start": elapsed / 16000,
                         "end": (elapsed + frames) / 16000})
        elapsed += frames
    if not 0 < elapsed <= 3600 * 16000:
        raise ValueError("retimed narration must contain at most one hour of audio")
    return {"source_duration": data["audio_duration"], "audio_duration": elapsed / 16000, "segments": segments}


def retimed_ranges(data: dict, timeline: dict) -> dict:
    return {**data, "audio_duration": timeline["audio_duration"], "ranges": [
        {**item, "start": segment["start"], "end": segment["end"]}
        for item, segment in zip(data["ranges"], timeline["segments"])]}


def visual_durations(data: dict, manifest: dict) -> tuple[dict, dict]:
    timeline = audio_timeline(data)
    order = gm.scene_playback_order(manifest)
    base = gm.scene_playback_durations(manifest)
    if sum(base.values()) + 1e-6 < data["audio_duration"]:
        raise ValueError("original visual timeline does not cover the original narration")
    def warp(t):
        for segment in timeline["segments"]:
            if t <= segment["source_end"]:
                portion = (t - segment["source_start"]) / (segment["source_end"] - segment["source_start"])
                return segment["start"] + portion * (segment["end"] - segment["start"])
        return t + timeline["audio_duration"] - data["audio_duration"]
    elapsed, previous, durations = 0.0, 0.0, []
    for scene_id in order:
        elapsed += base[str(scene_id)]
        cut = warp(elapsed)
        durations.append(cut - previous)
        previous = cut
    quantized = video._quantize_scene_durations(durations)
    return timeline, {str(i): d for i, d in zip(order, quantized)}


def preview(task_id: str, plan, source: str, speed: float) -> dict:
    if speed != 1.0:
        raise ValueError("natural narration retiming requires normal visual playback speed")
    revision = nr.revision(task_id)
    data = nr.load_validated(task_id, plan, source)
    if not has_natural(data):
        raise ValueError("save a natural-duration narration recording first")
    for item in data["ranges"]:
        if item.get("replacement"):
            nr._replacement_preview(task_id, item)
    manifest = gm.load_manifest(task_id)
    timeline, durations = visual_durations(data, manifest)
    snapshot = gm.scene_timing_snapshot(manifest)
    rows, elapsed = [], 0.0
    for scene_id in gm.scene_playback_order(manifest):
        record = gm.scene_record(manifest, scene_id)
        available, checksum = None, None
        try:
            if record.get("status") != "ready":
                raise ValueError("scene not ready")
            candidate = gm.resolve_asset(task_id, record["active_asset"])
            if record.get("asset_origin") == "imported":
                gm.validate_imported_scene(task_id, record, gm.scene_spec_from_version_metadata(record))
            checksum = gm.media_sha256(candidate)
            clip = video._open_video_clip_quietly(str(candidate))
            try:
                available = float(clip.duration)
            finally:
                video.close_clip(clip)
            if not math.isfinite(available) or available <= 0:
                raise ValueError("invalid source duration")
        except (OSError, ValueError, KeyError, TypeError):
            available, checksum = None, None
        duration = durations[str(scene_id)]
        rows.append({"scene_id": scene_id, "start": elapsed, "end": elapsed + duration,
                     "duration": duration, "available_duration": available, "asset_sha256": checksum,
                     "needs_footage": available is None or not video._scene_duration_covered(duration, available)})
        elapsed += duration
    current = scene_planner.load_scene_plan(task_id)
    if (current is None or nr.revision(task_id) != revision
            or nr._binding(task_id, current, source)[0] != data["binding"]
            or gm.scene_timing_snapshot(gm.load_manifest(task_id)) != snapshot):
        raise ValueError("narration or scene inputs changed while previewing")
    result = {"schema_version": 1, "source_revision": revision, "scene_snapshot": snapshot,
              "source_asset": data["binding"]["audio_asset"],
              "source_signature": list(nr._signature(Path(source))), "speed": speed,
              "timeline": timeline, "visual_durations": durations, "rows": rows,
              "covered": not any(row["needs_footage"] for row in rows)}
    result["signature"] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


def load_preview(task_id: str) -> dict | None:
    target = gm.resolve_asset(task_id, NAME)
    try:
        if target.stat().st_size > 1024 * 1024:
            return None
        result = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(result, dict) or result.get("schema_version") != 1
                or not isinstance(result.get("rows"), list) or len(result["rows"]) > 512
                or not all(isinstance(row, dict) for row in result["rows"])
                or result.get("source_revision") != nr.revision(task_id)
                or result.get("scene_snapshot") != gm.scene_timing_snapshot(gm.load_manifest(task_id))
                or result.get("source_signature") != list(nr._signature(gm.resolve_asset(task_id, result["source_asset"])))):
            return None
        script = json.loads(gm.resolve_asset(task_id, "script.json").read_text(encoding="utf-8"))
        if result.get("speed") != script["params"].get("video_clip_speed", 1):
            return None
        unsigned = {k: v for k, v in result.items() if k != "signature"}
        if result.get("signature") != hashlib.sha256(json.dumps(unsigned, sort_keys=True, allow_nan=False).encode()).hexdigest():
            return None
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_preview(task_id: str, plan, source: str, speed: float) -> dict:
    result = preview(task_id, plan, source, speed)
    scene_planner._atomic_write_json(gm.resolve_asset(task_id, NAME), result)
    return result
