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
        unchanged = old.get("fingerprint") == fingerprint
        record = {
            **scene.to_dict(),
            "fingerprint": fingerprint,
            "status": old.get("status", "pending") if unchanged else "pending",
            "active_asset": old.get("active_asset") if unchanged else None,
            "actual_duration": old.get("actual_duration") if unchanged else None,
            "versions": versions,
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
