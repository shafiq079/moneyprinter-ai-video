from __future__ import annotations

import json
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import generation_manifest, scene_planner, state as sm
from app.services import task, task_artifacts, voice
from app.utils import utils

from . import create_provider, generate_scene_materials, validate_output_storage
from .benchmark import BenchmarkTarget, GpuSampler


VALIDATION_SCHEMA_VERSION = 1
_REQUIRED_WORKER_METADATA = (
    "worker_python_version",
    "worker_torch_version",
    "worker_cuda_version",
    "worker_numpy_version",
)


def _check(
    name: str,
    status: str,
    *,
    detail: str | None = None,
    **data: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status}
    if detail:
        payload["detail"] = str(detail)
    payload.update(data)
    return payload


def _safe_error_message(exc: Exception) -> str:
    # Local provider/config/media errors are intentionally path-safe. Unknown
    # exceptions are reduced to their type so validation reports never become a
    # new host-path or credential persistence surface.
    safe_types = (
        ValueError,
        RuntimeError,
        FileNotFoundError,
    )
    if isinstance(exc, safe_types):
        message = " ".join(str(exc).split()).strip()
        if message and len(message) <= 500:
            return message
    return f"{type(exc).__name__} during GPU validation"


def _git_head() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else None


def _release_provider(provider: Any) -> None:
    releaser = getattr(type(provider), "release_runtime", None)
    if callable(releaser):
        releaser()


def _active_assets(manifest: dict[str, Any]) -> dict[int, str]:
    return {
        int(record["scene_id"]): str(record.get("active_asset") or "")
        for record in manifest.get("scenes", [])
        if isinstance(record, dict) and isinstance(record.get("scene_id"), int)
    }


def _write_report_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_target(
    target: BenchmarkTarget,
    *,
    required: bool,
    script: str,
    scene_count: int,
    scene_duration: int,
    aspect: str,
    seed: int,
    provider_factory: Callable[..., Any],
    sampler_factory: Callable[..., Any],
    generate_materials_fn: Callable[..., list[str]],
    generate_final_videos_fn: Callable[..., tuple[list[str], list[str], list]],
    regenerate_scene_fn: Callable[..., dict],
    rerender_fn: Callable[..., dict],
) -> dict[str, Any]:
    label = target.label
    task_id = (
        "gpu-validation-"
        + label.replace(":", "-").replace("_", "-")
        + "-"
        + uuid4().hex[:10]
    )
    result: dict[str, Any] = {
        "provider_id": target.provider_id,
        "generation_mode": target.generation_mode,
        "required": bool(required),
        "status": "failed",
        "task_id": task_id,
        "model_fingerprint": None,
        "provider_metadata": {},
        "gpu": {},
        "checks": [],
        "artifacts": {},
        "error_type": None,
        "error_message": None,
    }
    provider = None
    sampler = None
    current_check = "preflight"

    try:
        provider = provider_factory(
            target.provider_id,
            generation_mode=target.generation_mode,
        )
        result["model_fingerprint"] = str(
            getattr(provider, "model_fingerprint", "") or ""
        )
        validate_output_storage()
        provider.preflight()
        metadata = generation_manifest.sanitize_persisted_metadata(
            provider.safe_metadata()
            if callable(getattr(provider, "safe_metadata", None))
            else {}
        )
        result["provider_metadata"] = metadata
        result["checks"].append(_check("preflight", "passed"))

        current_check = "worker_environment"
        missing_versions = [
            key for key in _REQUIRED_WORKER_METADATA
            if not str(metadata.get(key) or "").strip()
        ]
        if missing_versions:
            raise RuntimeError(
                "provider preflight did not report worker versions: "
                + ", ".join(missing_versions)
            )
        result["checks"].append(
            _check(
                "worker_environment",
                "passed",
                python=metadata["worker_python_version"],
                torch=metadata["worker_torch_version"],
                cuda=metadata["worker_cuda_version"],
                numpy=metadata["worker_numpy_version"],
            )
        )

        max_scene_duration = float(
            getattr(provider, "max_scene_duration", scene_duration)
        )
        if scene_duration > max_scene_duration:
            raise ValueError(
                f"{label} supports at most {max_scene_duration:.1f}s per validation scene"
            )

        task_root = Path(utils.task_dir(task_id))
        task_root.mkdir(parents=True, exist_ok=True)
        total_duration = float(scene_count * scene_duration)
        params = VideoParams(
            video_subject="Local AI GPU validation",
            video_script=script,
            video_source=target.provider_id,
            local_ai_generation_mode=target.generation_mode,
            local_ai_seed=seed,
            video_aspect=aspect,
            video_clip_duration=scene_duration,
            video_concat_mode=VideoConcatMode.sequential.value,
            video_count=1,
            voice_name=voice.NO_VOICE_NAME,
            subtitle_enabled=False,
            bgm_type="",
            bgm_volume=0.0,
        )
        task_artifacts.write_script_data(
            task_id,
            {
                "script": script,
                "search_terms": [],
                "params": params.model_dump(mode="json"),
            },
        )

        audio_file = task_root / "gpu-validation-audio.wav"
        if not voice.generate_silent_audio(total_duration, str(audio_file)):
            raise RuntimeError("failed to create GPU validation timing audio")
        measured_audio_duration = float(voice.get_audio_duration(str(audio_file)) or 0)
        if measured_audio_duration <= 0:
            raise RuntimeError("GPU validation timing audio duration is unavailable")

        plan = scene_planner.get_or_create_scene_plan(
            task_id,
            script,
            video_subject=params.video_subject,
            audio_duration=measured_audio_duration,
            max_scene_duration=float(scene_duration),
            aspect=aspect,
            base_seed=seed,
            provider_settings=(
                provider.generation_settings()
                if callable(getattr(provider, "generation_settings", None))
                else {}
            ),
            visual_style="cinematic realistic validation footage",
            use_llm=False,
        )
        if len(plan.scenes) < 2:
            raise RuntimeError("GPU validation requires at least two planned scenes")
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=40,
            audio_file=str(audio_file),
            audio_duration=measured_audio_duration,
            subtitle_path="",
            local_ai_provider=target.provider_id,
            generation_mode=target.generation_mode,
        )

        device_index = int(
            getattr(getattr(provider, "settings", None), "device_id", 0) or 0
        )
        with sampler_factory(device_index) as sampler:
            current_check = "multi_scene_generation"
            materials = generate_materials_fn(
                task_id,
                provider=provider,
                scenes=list(plan.scenes),
            )
            initial_manifest = generation_manifest.load_manifest(task_id)
            if initial_manifest is None:
                raise RuntimeError("generation manifest was not created")
            if len(materials) != len(plan.scenes) or not all(
                Path(item).is_file() for item in materials
            ):
                raise RuntimeError("not all planned scenes produced validated files")
            result["checks"].append(
                _check(
                    "multi_scene_generation",
                    "passed",
                    scene_count=len(plan.scenes),
                )
            )

            current_check = "runtime_reuse"
            runtime_load_count = int(
                (initial_manifest.get("telemetry") or {}).get(
                    "runtime_load_count", 0
                )
                or 0
            )
            if runtime_load_count != 1:
                raise RuntimeError(
                    "multi-scene validation expected one runtime load/reuse call"
                )
            result["checks"].append(
                _check(
                    "runtime_reuse",
                    "passed",
                    scene_count=len(plan.scenes),
                    runtime_load_count=runtime_load_count,
                )
            )

            current_check = "final_media"
            final_paths, combined_paths, warnings = generate_final_videos_fn(
                task_id,
                params,
                materials,
                str(audio_file),
                "",
                measured_audio_duration,
            )
            if not final_paths or not all(
                Path(item).is_file() and Path(item).stat().st_size > 0
                for item in final_paths
            ):
                raise RuntimeError("final validated MP4 was not produced")
            result["checks"].append(
                _check(
                    "final_media",
                    "passed",
                    final_video_count=len(final_paths),
                )
            )
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_COMPLETE,
                progress=100,
                videos=final_paths,
                combined_videos=combined_paths,
                materials=materials,
                audio_file=str(audio_file),
                audio_duration=measured_audio_duration,
                subtitle_path="",
                warnings=warnings or None,
                local_ai_provider=target.provider_id,
                generation_mode=target.generation_mode,
            )

            current_check = "scene_regeneration"
            before_regeneration = generation_manifest.load_manifest(task_id)
            if before_regeneration is None:
                raise RuntimeError("generation manifest disappeared before regeneration")
            before_assets = _active_assets(before_regeneration)
            scene = plan.scenes[0]
            regenerate_scene_fn(
                task_id,
                scene.scene_id,
                seed=int(scene.seed) + 1000,
            )
            after_regeneration = generation_manifest.load_manifest(task_id)
            if after_regeneration is None:
                raise RuntimeError("generation manifest disappeared after regeneration")
            after_assets = _active_assets(after_regeneration)
            changed_ids = sorted(
                scene_id
                for scene_id, asset in before_assets.items()
                if after_assets.get(scene_id) != asset
            )
            if changed_ids != [int(scene.scene_id)]:
                raise RuntimeError(
                    "single-scene regeneration changed unexpected active scene assets"
                )
            regenerated_record = generation_manifest.scene_record(
                after_regeneration,
                int(scene.scene_id),
            )
            if len(regenerated_record.get("versions") or []) < 2:
                raise RuntimeError("scene regeneration did not retain version history")
            result["checks"].append(
                _check(
                    "scene_regeneration",
                    "passed",
                    scene_id=int(scene.scene_id),
                    version_count=len(regenerated_record.get("versions") or []),
                )
            )

            current_check = "render_only_rerender"
            manifest_before_rerender = deepcopy(
                generation_manifest.load_manifest(task_id)
            )
            rerender_result = rerender_fn(task_id)
            manifest_after_rerender = generation_manifest.load_manifest(task_id)
            if manifest_before_rerender != manifest_after_rerender:
                raise RuntimeError(
                    "render-only rerender modified local AI generation state"
                )
            rerender_videos = list(rerender_result.get("videos") or [])
            if not rerender_videos or not all(
                Path(item).is_file() and Path(item).stat().st_size > 0
                for item in rerender_videos
            ):
                raise RuntimeError("render-only rerender did not produce final media")
            result["checks"].append(
                _check("render_only_rerender", "passed")
            )

        current_check = "gpu_telemetry"
        result["gpu"] = sampler.summary.to_dict() if sampler is not None else {}
        if (
            int(result["gpu"].get("samples") or 0) <= 0
            or not result["gpu"].get("device_name")
            or not result["gpu"].get("memory_total_mb")
        ):
            raise RuntimeError(
                "nvidia-smi GPU telemetry was unavailable during validation"
            )
        result["checks"].append(
            _check(
                "gpu_telemetry",
                "passed",
                peak_memory_used_mb=result["gpu"].get("peak_memory_used_mb"),
                peak_utilization_percent=result["gpu"].get(
                    "peak_utilization_percent"
                ),
            )
        )

        current_check = "output_package"
        current_state = sm.state.get_task(task_id) or {}
        package = task_artifacts.build_output_package(task_id, current_state)
        if (
            not package.get("final_videos")
            or not package.get("scene_plan")
            or not package.get("generation_manifest")
            or len(package.get("scene_materials") or []) < 2
        ):
            raise RuntimeError("portable local AI output package is incomplete")
        result["artifacts"] = package
        result["checks"].append(_check("output_package", "passed"))
        result["status"] = "passed"
        return result
    except Exception as exc:
        if sampler is not None and not result["gpu"]:
            result["gpu"] = sampler.summary.to_dict()
        result["error_type"] = type(exc).__name__
        result["error_message"] = _safe_error_message(exc)
        if current_check == "preflight" and not required:
            result["status"] = "skipped"
            result["checks"].append(
                _check(
                    "preflight",
                    "skipped",
                    detail=result["error_message"],
                    error_type=type(exc).__name__,
                )
            )
        else:
            result["status"] = "failed"
            result["checks"].append(
                _check(
                    current_check,
                    "failed",
                    detail=result["error_message"],
                    error_type=type(exc).__name__,
                )
            )
        return result
    finally:
        if provider is not None:
            _release_provider(provider)


def run_gpu_validation_suite(
    targets: Iterable[BenchmarkTarget],
    *,
    script: str,
    scene_count: int = 2,
    scene_duration: int = 3,
    aspect: str = "9:16",
    seed: int = 42,
    report_dir: Path = Path("storage") / "validation" / "local-ai-gpu",
    require_ltx_quality: bool = False,
    provider_factory: Callable[..., Any] = create_provider,
    sampler_factory: Callable[..., Any] = GpuSampler,
    generate_materials_fn: Callable[..., list[str]] = generate_scene_materials,
    generate_final_videos_fn: Callable[..., tuple[list[str], list[str], list]] = task.generate_final_videos,
    regenerate_scene_fn: Callable[..., dict] = task.regenerate_local_ai_scene,
    rerender_fn: Callable[..., dict] = task.rerender_local_ai_task,
) -> dict[str, Any]:
    target_list = list(targets)
    if not target_list:
        raise ValueError("at least one GPU validation target is required")
    if not str(script or "").strip():
        raise ValueError("GPU validation script must not be empty")
    if int(scene_count) < 2:
        raise ValueError("GPU validation scene_count must be >= 2")
    if int(scene_duration) < 1:
        raise ValueError("GPU validation scene_duration must be >= 1")
    if aspect not in {"9:16", "16:9", "1:1"}:
        raise ValueError("GPU validation aspect must be 9:16, 16:9, or 1:1")
    if int(seed) < 0:
        raise ValueError("GPU validation seed must be >= 0")

    results = []
    for target in target_list:
        is_quality = (
            target.provider_id == "ltx25_local"
            and target.generation_mode == "quality"
        )
        required = not is_quality or require_ltx_quality
        results.append(
            _validate_target(
                target,
                required=required,
                script=str(script).strip(),
                scene_count=int(scene_count),
                scene_duration=int(scene_duration),
                aspect=aspect,
                seed=int(seed),
                provider_factory=provider_factory,
                sampler_factory=sampler_factory,
                generate_materials_fn=generate_materials_fn,
                generate_final_videos_fn=generate_final_videos_fn,
                regenerate_scene_fn=regenerate_scene_fn,
                rerender_fn=rerender_fn,
            )
        )

    failed = [item for item in results if item["status"] == "failed"]
    required_not_passed = [
        item
        for item in results
        if item["required"] and item["status"] != "passed"
    ]
    payload = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": (
            "passed"
            if not failed and not required_not_passed
            else "failed"
        ),
        "application": {
            "git_head": _git_head(),
            "python_version": platform.python_version(),
            "platform": platform.system(),
        },
        "validation": {
            "scene_count": int(scene_count),
            "scene_duration": int(scene_duration),
            "aspect": aspect,
            "base_seed": int(seed),
            "ltx_quality_required": bool(require_ltx_quality),
        },
        "results": results,
    }
    report_path = Path(report_dir) / "gpu-validation.json"
    _write_report_atomic(report_path, payload)
    payload["report_path"] = str(report_path)
    return payload
