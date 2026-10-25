"""Source-bound, reversible narration mixes for existing scene exports."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import shutil
import uuid
import wave
from pathlib import Path

from app.services import generation_manifest as gm
from app.services import narration_ranges as nr, scene_planner

NAME = "narration_mix.json"


def file(task_id: str) -> Path:
    return gm.resolve_asset(task_id, NAME)


def _signature(data: dict) -> str:
    selected = [{k: item[k] for k in ("scene_id", "start", "end", "replacement") if k in item}
                for item in data["ranges"]]
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def resolve(task_id: str, source: str) -> str:
    """Validate an active mix, or retain the legacy original-audio path."""
    target = file(task_id)
    if not target.exists():
        return source
    if target.stat().st_size > 1024 * 1024:
        raise ValueError("edited narration metadata is too large; restore original narration")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid edited narration metadata")
    plan = scene_planner.load_scene_plan(task_id)
    if plan is None:
        raise ValueError("edited narration scene plan is unavailable")
    ranges = nr.load_validated(task_id, plan, source)
    if (data.get("schema_version") != 1 or data.get("captions_omitted") is not True
            or data.get("binding") != ranges["binding"]
            or data.get("ranges_sha256") != _signature(ranges)):
        raise ValueError("edited narration inputs changed; restore original narration")
    asset = data.get("audio_asset")
    if not isinstance(asset, str):
        raise ValueError("invalid edited narration asset")
    parts = Path(asset).parts
    if (len(parts) != 3 or parts[0] != "narration_mixes" or len(parts[1]) != 32
            or any(c not in "0123456789abcdef" for c in parts[1]) or parts[2] != "audio.wav"):
        raise ValueError("invalid edited narration asset")
    output = gm.resolve_asset(task_id, asset)
    if output.stat().st_size > 3600 * 32000 + 4096 or gm.media_sha256(output) != data.get("audio_sha256"):
        raise ValueError("edited narration audio changed; restore original narration")
    with wave.open(str(output), "rb") as audio:
        if (audio.getframerate() != 16000 or audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or abs(audio.getnframes() / 16000 - ranges["audio_duration"]) > 1 / 16000):
            raise ValueError("invalid edited narration audio")
    return str(output)


def build(task_id: str, plan, source: str, expected_revision: str) -> tuple[dict, Path]:
    data = nr.load_validated(task_id, plan, source)
    if nr.revision(task_id) != expected_revision:
        raise ValueError("narration ranges changed; refresh the Scene Editor")
    if not any(item.get("replacement") for item in data["ranges"]):
        raise ValueError("save a replacement narration draft first")
    directory = gm.resolve_asset(task_id, f"narration_mixes/{uuid.uuid4().hex}")
    directory.mkdir(parents=True)
    try:
        decoded = directory / "original.wav"
        nr._extract(Path(source), decoded, 0, 3601)
        output = directory / "audio.wav"
        with wave.open(str(decoded), "rb") as original, wave.open(str(output), "wb") as target:
            if abs(original.getnframes() / 16000 - data["audio_duration"]) > 1 / 16000:
                raise ValueError("decoded narration duration changed")
            target.setparams(original.getparams())
            for item in data["ranges"]:
                start, end = round(item["start"] * 16000), round(item["end"] * 16000)
                if item.get("replacement"):
                    if item["scene_id"] not in data.get("operator_reviewed_scene_ids", []):
                        raise ValueError("review each replaced narration range first")
                    candidate = nr._replacement_preview(task_id, item)
                    with wave.open(str(candidate), "rb") as replacement:
                        frames = replacement.readframes(end - start)
                    # The draft contract permits 2 ms of decoded-length tolerance.
                    # Normalize only this tiny tail to keep every later sample fixed.
                    frames += bytes(max(0, (end - start) * 2 - len(frames)))
                    target.writeframesraw(frames)
                else:
                    original.setpos(start)
                    remaining = end - start
                    while remaining:
                        chunk = original.readframes(min(remaining, 160000))
                        if not chunk:
                            raise ValueError("original narration ended unexpectedly")
                        target.writeframesraw(chunk)
                        remaining -= len(chunk) // 2
        decoded.unlink()
        current = scene_planner.load_scene_plan(task_id)
        if (current is None or nr._binding(task_id, current, source)[0] != data["binding"]
                or nr.revision(task_id) != expected_revision):
            raise ValueError("narration inputs changed during mixing")
        metadata = {
            "schema_version": 1, "captions_omitted": True,
            "binding": data["binding"], "ranges_sha256": _signature(data),
            "audio_asset": f"narration_mixes/{directory.name}/audio.wav",
            "audio_sha256": gm.media_sha256(output),
        }
        return metadata, directory
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def cleanup(task_id: str) -> None:
    """Remove inactive owned mix directories only after successful publication."""
    root = gm.resolve_asset(task_id, "narration_mixes")
    if not root.exists():
        return
    active = None
    if file(task_id).exists():
        data = json.loads(file(task_id).read_text(encoding="utf-8"))
        active = gm.resolve_asset(task_id, data["audio_asset"]).parent
    for candidate in root.iterdir():
        if (candidate != active and not candidate.is_symlink() and candidate.is_dir()
                and len(candidate.name) == 32
                and all(c in "0123456789abcdef" for c in candidate.name)):
            shutil.rmtree(candidate, ignore_errors=True)


def restore(task_id: str, content: bytes | None) -> None:
    target = file(task_id)
    if content is None:
        target.unlink(missing_ok=True)
        return
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=".narration-mix-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
