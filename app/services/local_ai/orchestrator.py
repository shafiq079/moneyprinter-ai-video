from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import ExitStack

from loguru import logger

from app.services import generation_manifest

from .base import LocalVideoProvider, SceneSpec


def generate_scene_materials(
    task_id: str,
    *,
    provider: LocalVideoProvider,
    scenes: list[SceneSpec],
    progress_callback: Callable[[int, int, SceneSpec, bool], None] | None = None,
) -> list[str]:
    """Generate/reuse ordered scene clips and persist progress after every scene."""

    if not scenes:
        raise ValueError("local AI scene plan must contain at least one scene")

    manifest = generation_manifest.prepare_manifest(
        task_id,
        provider_id=provider.provider_id,
        model_fingerprint=provider.model_fingerprint,
        scenes=scenes,
        provider_metadata=(
            provider.safe_metadata()
            if callable(getattr(provider, "safe_metadata", None))
            else None
        ),
    )
    runtime_loaded = False
    outputs: list[str] = []

    # Heavy local providers may expose a task-level generation session. Enter it
    # lazily only when a scene actually needs generation: a fully cached retry
    # should not take the GPU lock or evict another model family just to validate
    # already-persisted clips. Once entered, keep it for the rest of the scene
    # batch so different provider families cannot thrash each other per scene.
    session_factory = getattr(provider, "generation_session", None)
    generation_session_entered = False

    total_scenes = len(scenes)
    with ExitStack() as stack:
        for scene_index, scene in enumerate(scenes, start=1):
            logger.info(
                f"local AI scene {scene_index}/{total_scenes}: "
                f"provider={provider.provider_id}, scene_id={scene.scene_id}"
            )
            record = generation_manifest.scene_record(manifest, scene.scene_id)
            active_asset = record.get("active_asset")
            if (
                record.get("status") == "ready"
                and record.get("fingerprint")
                and active_asset
            ):
                try:
                    cached_path = generation_manifest.resolve_asset(
                        task_id, active_asset
                    )
                    validated = provider.validate_output(cached_path, scene)
                except Exception as exc:
                    record["status"] = "invalid"
                    record["active_asset"] = None
                    record["actual_duration"] = None
                    record["error_type"] = type(exc).__name__
                    generation_manifest.save_manifest(task_id, manifest)
                else:
                    record["actual_duration"] = validated.actual_duration
                    record["error_type"] = None
                    outputs.append(str(cached_path))
                    if progress_callback is not None:
                        progress_callback(scene_index, total_scenes, scene, True)
                    continue

            if not runtime_loaded:
                if callable(session_factory) and not generation_session_entered:
                    stack.enter_context(session_factory())
                    generation_session_entered = True
                provider.preflight()
                provider.load_runtime()
                runtime_loaded = True

            relative, final_path, partial_path = generation_manifest.next_scene_version(
                task_id,
                scene.scene_id,
                list(record.get("versions") or []),
            )
            partial_path.unlink(missing_ok=True)
            record["status"] = "generating"
            record["error_type"] = None
            generation_manifest.save_manifest(task_id, manifest)

            try:
                provider.generate(scene, partial_path)
                provider.validate_output(partial_path, scene)
                os.replace(partial_path, final_path)
                validated = provider.validate_output(final_path, scene)
            except Exception as exc:
                partial_path.unlink(missing_ok=True)
                record["status"] = "failed"
                record["active_asset"] = None
                record["actual_duration"] = None
                # Persist only an exception type. Detailed provider errors stay in logs
                # so manifests cannot accidentally capture model paths/tokens/host data.
                record["error_type"] = type(exc).__name__
                generation_manifest.save_manifest(task_id, manifest)
                raise

            versions = list(record.get("versions") or [])
            if relative not in versions:
                versions.append(relative)
            record["versions"] = versions
            record["active_asset"] = relative
            record["actual_duration"] = validated.actual_duration
            record["status"] = "ready"
            record["error_type"] = None
            generation_manifest.save_manifest(task_id, manifest)
            outputs.append(str(final_path))
            if progress_callback is not None:
                progress_callback(scene_index, total_scenes, scene, False)

    return outputs
