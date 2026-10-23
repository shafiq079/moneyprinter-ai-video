"""Task-local, video-only scene imports. No provider or network calls."""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path

from app.services import generation_manifest
from app.utils import utils

from .base import SceneSpec
from .media import validate_video_clip


MAX_CLIP_UPLOAD_BYTES = 100 * 1024 * 1024


def validate_upload_bytes(content: bytes) -> None:
    if not isinstance(content, bytes) or not content:
        raise ValueError("select a non-empty MP4 clip")
    if len(content) > MAX_CLIP_UPLOAD_BYTES:
        raise ValueError("replacement clip exceeds the 100 MiB limit")


def validate_start_seconds(start_seconds: float) -> None:
    if (
        isinstance(start_seconds, bool)
        or not isinstance(start_seconds, (int, float))
        or not math.isfinite(start_seconds)
        or start_seconds < 0
    ):
        raise ValueError("clip start must be a finite non-negative number")


def stage_clip_import(
    task_id: str, scene: SceneSpec, content: bytes, *, start_seconds: float = 0.0,
    source_metadata: dict | None = None,
) -> tuple[dict, Path]:
    """Publish a validated new file and return an uncommitted manifest snapshot.

    The caller commits the manifest for composition and rolls it back on render
    failure. Input names/paths and raw decoder diagnostics are never persisted.
    """
    validate_upload_bytes(content)
    validate_start_seconds(start_seconds)
    manifest = generation_manifest.load_manifest(task_id)
    if manifest is None:
        raise ValueError("generation manifest is missing")
    record = generation_manifest.scene_record(manifest, scene.scene_id)
    scene_dir = generation_manifest.resolve_asset(
        task_id, f"generated_ai/scene-{scene.scene_id:03d}"
    )
    scene_dir.mkdir(parents=True, exist_ok=True)
    versions = list(record.get("versions") or [])
    # A previous crash may have published a file before registering its version.
    occupied = versions + [item.name for item in scene_dir.glob("v*.mp4")]
    relative, final_path, partial_path = generation_manifest.next_scene_version(
        task_id, scene.scene_id, occupied
    )
    generation_manifest.resolve_asset(task_id, relative)
    output_duration = max(scene.target_duration, generation_manifest.scene_playback_durations(manifest)[str(scene.scene_id)])
    raw_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=scene_dir, prefix=".clip-upload-", suffix=".partial.mp4", delete=False
        ) as stream:
            raw_path = Path(stream.name)
            stream.write(content)
        command = [
            utils.get_ffmpeg_binary(),
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(raw_path),
            "-ss",
            f"{start_seconds:.6f}",
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-vf",
            "setsar=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-threads",
            "1",
            "-t",
            f"{output_duration:.3f}",
            "-movflags",
            "+faststart",
            str(partial_path),
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("replacement clip processing timed out") from exc
        if result.returncode:
            raise ValueError("replacement clip could not be decoded as video")
        probe = validate_video_clip(partial_path, scene)
        if probe.duration + 0.05 < output_duration:
            raise ValueError("replacement clip is shorter than the scene duration")

        old_active = record.get("active_asset")
        if (
            old_active
            and generation_manifest.scene_version_metadata(record, old_active) is None
        ):
            generation_manifest.remember_scene_version(record, old_active)
        os.replace(partial_path, final_path)
        record.update(scene.to_dict())
        record.update(
            active_asset=relative,
            actual_duration=probe.duration,
            versions=versions + [relative],
            status="ready",
            asset_origin="imported",
            import_metadata={
                **(source_metadata or {}),
                "media_sha256": generation_manifest.media_sha256(final_path),
                "start_seconds": float(start_seconds),
            },
            error_type=None,
            error_code=None,
            generation_seconds=None,
            validation_seconds=None,
        )
        generation_manifest.remember_scene_version(
            record, relative, actual_duration=probe.duration
        )
        return manifest, final_path
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    finally:
        partial_path.unlink(missing_ok=True)
        if raw_path is not None:
            raw_path.unlink(missing_ok=True)
