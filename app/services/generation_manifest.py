from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.services.local_ai.base import SceneSpec, scene_fingerprint
from app.utils import utils


SCHEMA_VERSION = 1
_MANIFEST_NAME = "generation_manifest.json"
_VERSION_RE = re.compile(r"^v(\d+)\.mp4$")


def manifest_path(task_id: str) -> Path:
    return Path(utils.task_dir(task_id)) / "generated_ai" / _MANIFEST_NAME


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".generation-manifest-",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def load_manifest(task_id: str) -> dict[str, Any] | None:
    path = manifest_path(task_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("local AI generation manifest is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported local AI generation manifest schema")
    if not isinstance(payload.get("scenes"), list):
        raise ValueError("local AI generation manifest has invalid scenes")
    return payload


def save_manifest(task_id: str, manifest: dict[str, Any]) -> None:
    _atomic_write(manifest_path(task_id), manifest)


def prepare_manifest(
    task_id: str,
    *,
    provider_id: str,
    model_fingerprint: str,
    scenes: list[SceneSpec],
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = load_manifest(task_id) or {}
    previous_by_id = {
        item.get("scene_id"): item
        for item in previous.get("scenes", [])
        if isinstance(item, dict) and isinstance(item.get("scene_id"), int)
    }

    records = []
    for scene in scenes:
        fingerprint = scene_fingerprint(
            scene,
            provider_id=provider_id,
            model_fingerprint=model_fingerprint,
        )
        old = previous_by_id.get(scene.scene_id) or {}
        versions = [
            value
            for value in old.get("versions", [])
            if isinstance(value, str) and value
        ]
        version_metadata = {
            str(key): dict(value)
            for key, value in (old.get("version_metadata") or {}).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        unchanged = old.get("fingerprint") == fingerprint
        record = {
            **scene.to_dict(),
            "provider_id": str(provider_id),
            "model_fingerprint": str(model_fingerprint),
            "provider_metadata": dict(provider_metadata or {}),
            "fingerprint": fingerprint,
            "status": old.get("status", "pending") if unchanged else "pending",
            "active_asset": old.get("active_asset") if unchanged else None,
            "actual_duration": old.get("actual_duration") if unchanged else None,
            "versions": versions,
            "version_metadata": version_metadata,
            "error_type": old.get("error_type") if unchanged else None,
            "error_code": old.get("error_code") if unchanged else None,
        }
        records.append(record)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "task_id": str(task_id),
        "provider_id": str(provider_id),
        "model_fingerprint": str(model_fingerprint),
        "provider_metadata": dict(provider_metadata or {}),
        "scenes": records,
    }
    save_manifest(task_id, manifest)
    return manifest


def scene_record(manifest: dict[str, Any], scene_id: int) -> dict[str, Any]:
    for record in manifest["scenes"]:
        if record.get("scene_id") == scene_id:
            return record
    raise KeyError(f"scene {scene_id} is missing from generation manifest")


def resolve_asset(task_id: str, relative_path: str) -> Path:
    relative = Path(str(relative_path or ""))
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid task-local asset path")

    root = Path(utils.task_dir(task_id)).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("task-local asset escapes the task directory") from exc
    return candidate


def next_scene_version(
    task_id: str,
    scene_id: int,
    versions: list[str],
) -> tuple[str, Path, Path]:
    highest = 0
    for item in versions:
        name = Path(item).name
        match = _VERSION_RE.match(name)
        if match:
            highest = max(highest, int(match.group(1)))

    version = highest + 1
    relative = (
        Path("generated_ai")
        / f"scene-{scene_id:03d}"
        / f"v{version:03d}.mp4"
    )
    final_path = Path(utils.task_dir(task_id)) / relative
    final_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = final_path.with_name(f".{final_path.stem}.partial.mp4")
    return relative.as_posix(), final_path, partial_path


def remember_scene_version(
    record: dict[str, Any],
    relative_path: str,
    *,
    actual_duration: float | None = None,
) -> None:
    """Persist the exact scene inputs used for one versioned clip."""

    relative = str(relative_path or "")
    if not relative:
        raise ValueError("scene version path must not be empty")

    metadata = {
        key: record.get(key)
        for key in (
            "scene_id",
            "narration_segment",
            "prompt",
            "target_duration",
            "aspect",
            "seed",
            "beat",
            "negative_prompt",
            "continuity",
            "camera",
            "provider_settings",
            "provider_id",
            "model_fingerprint",
            "provider_metadata",
            "fingerprint",
        )
    }
    metadata["actual_duration"] = (
        float(actual_duration)
        if actual_duration is not None
        else record.get("actual_duration")
    )

    history = dict(record.get("version_metadata") or {})
    history[relative] = metadata
    record["version_metadata"] = history


def scene_version_metadata(
    record: dict[str, Any],
    relative_path: str,
) -> dict[str, Any] | None:
    value = (record.get("version_metadata") or {}).get(str(relative_path))
    return dict(value) if isinstance(value, dict) else None


def scene_spec_from_version_metadata(
    metadata: dict[str, Any],
) -> SceneSpec:
    """Rebuild a portable SceneSpec from stored version metadata."""

    provider_settings = metadata.get("provider_settings")
    if not isinstance(provider_settings, dict):
        provider_settings = {}
    return SceneSpec(
        scene_id=int(metadata["scene_id"]),
        narration_segment=str(metadata.get("narration_segment") or ""),
        prompt=str(metadata["prompt"]),
        target_duration=float(metadata["target_duration"]),
        aspect=str(metadata["aspect"]),
        seed=int(metadata["seed"]),
        beat=str(metadata.get("beat") or "build"),
        negative_prompt=str(metadata.get("negative_prompt") or ""),
        continuity=str(metadata.get("continuity") or ""),
        camera=str(metadata.get("camera") or ""),
        provider_settings=provider_settings,
    )


def restore_scene_version(
    task_id: str,
    scene_id: int,
    relative_path: str,
) -> tuple[dict[str, Any], SceneSpec, Path]:
    """Activate one stored scene version and restore its generation metadata."""

    manifest = load_manifest(task_id)
    if manifest is None:
        raise ValueError("local AI generation manifest is missing")

    record = scene_record(manifest, int(scene_id))
    relative = str(relative_path or "")
    if relative not in list(record.get("versions") or []):
        raise ValueError("scene version is not registered in the task manifest")

    metadata = scene_version_metadata(record, relative)
    if metadata is None:
        raise ValueError(
            "scene version predates version metadata and cannot be safely restored"
        )

    candidate = resolve_asset(task_id, relative)
    if not candidate.is_file():
        raise ValueError("scene version file is missing")

    scene = scene_spec_from_version_metadata(metadata)
    if scene.scene_id != int(scene_id):
        raise ValueError("scene version metadata does not match scene ID")

    from app.services.local_ai.media import validate_video_clip

    validated = validate_video_clip(candidate, scene)
    record.update(scene.to_dict())
    for key in (
        "provider_id",
        "model_fingerprint",
        "provider_metadata",
        "fingerprint",
    ):
        if key in metadata:
            record[key] = metadata[key]
    record["active_asset"] = relative
    record["actual_duration"] = validated.duration
    record["status"] = "ready"
    record["error_type"] = None
    record["error_code"] = None
    record["regeneration_status"] = "restored"
    record["regeneration_error_type"] = None
    record["regeneration_error_code"] = None
    save_manifest(task_id, manifest)
    return manifest, scene, candidate


def active_scene_paths(task_id: str) -> list[str]:
    """Return validated task-local active scene paths in scene order."""

    manifest = load_manifest(task_id)
    if manifest is None:
        raise ValueError("local AI generation manifest is missing")

    records = sorted(
        manifest.get("scenes", []),
        key=lambda item: int(item.get("scene_id", 0)),
    )
    if not records:
        raise ValueError("local AI generation manifest contains no scenes")

    paths: list[str] = []
    for record in records:
        if record.get("status") != "ready" or not record.get("active_asset"):
            raise ValueError(
                f"scene {record.get('scene_id')} does not have an active ready asset"
            )
        candidate = resolve_asset(task_id, record["active_asset"])
        if not candidate.is_file():
            raise ValueError(
                f"scene {record.get('scene_id')} active asset is missing"
            )
        paths.append(str(candidate))
    return paths

