"""任务目录中持久化文件的安全读写。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from loguru import logger

from app.utils import utils


def _script_file(task_id: str) -> Path:
    """返回任务脚本清单路径，并复用统一的任务目录创建逻辑。"""
    return Path(utils.task_dir(task_id)) / "script.json"


def _write_json_atomic(target: Path, payload: Mapping[str, Any]) -> None:
    """
    在目标目录内原子写入 JSON，避免进程中断留下半个文件。

    临时文件和目标文件必须位于同一目录，才能保证 ``os.replace`` 在常见
    本地文件系统和 Docker 挂载目录中保持原子替换语义。写入成功前不会修改
    现有文件；异常时只清理本次创建的临时文件，并把错误交给调用方决定是否
    影响主流程。
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                payload,
                temp_file,
                ensure_ascii=False,
                indent=4,
                default=lambda value: value.__dict__,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_script_data(task_id: str, payload: Mapping[str, Any]) -> None:
    """创建或完整替换任务的 ``script.json`` 清单。"""
    _write_json_atomic(_script_file(task_id), payload)


def patch_script_data(task_id: str, **updates: Any) -> bool:
    """
    在保留原有字段的前提下补充任务清单，失败时返回 ``False``。

    素材来源属于辅助诊断信息，不能因为文件权限、磁盘瞬时异常或历史文件损坏
    阻断视频生成。因此该入口会记录完整异常并降级；首次创建任务清单仍使用
    ``write_script_data``，由主流程决定基础任务数据写入失败时如何处理。
    """
    try:
        target = _script_file(task_id)
        with target.open("r", encoding="utf-8") as script_file:
            payload = json.load(script_file)
        if not isinstance(payload, dict):
            raise ValueError("task script data must be a JSON object")

        payload.update(updates)
        _write_json_atomic(target, payload)
        return True
    except FileNotFoundError:
        # ``download_videos`` 也可能被测试、脚本或第三方代码独立调用，此时没有
        # 任务清单属于正常场景，不应制造警告或为了辅助记录创建残缺文件。
        logger.debug(
            f"skip task script update because script.json does not exist: "
            f"task_id={task_id}"
        )
        return False
    except Exception as exc:
        logger.warning(
            "failed to update task script data: "
            f"task_id={task_id}, fields={sorted(updates)}, "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return False

OUTPUT_PACKAGE_SCHEMA_VERSION = 1


def _task_root(task_id: str) -> Path:
    return Path(utils.task_dir(task_id)).resolve()


def _task_relative_existing_file(
    task_id: str,
    value: str | os.PathLike[str] | None,
) -> str | None:
    """Return one existing task-local file as a portable relative path."""

    if not value:
        return None

    root = _task_root(task_id)
    candidate_value = Path(str(value))
    candidate = (
        candidate_value.resolve()
        if candidate_value.is_absolute()
        else (root / candidate_value).resolve()
    )
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return relative.as_posix()


def _discover_indexed_files(task_id: str, prefix: str) -> list[str]:
    root = _task_root(task_id)
    if not root.is_dir():
        return []

    discovered: list[tuple[int, str]] = []
    for candidate in root.glob(f"{prefix}-*.mp4"):
        if not candidate.is_file():
            continue
        stem_suffix = candidate.stem.removeprefix(f"{prefix}-")
        try:
            index = int(stem_suffix)
        except ValueError:
            continue
        discovered.append((index, candidate.relative_to(root).as_posix()))
    return [relative for _, relative in sorted(discovered)]


def _relative_files_from_state(
    task_id: str,
    values: Any,
    *,
    fallback_prefix: str,
) -> list[str]:
    if not isinstance(values, (list, tuple)):
        values = []

    result: list[str] = []
    for value in values:
        relative = _task_relative_existing_file(task_id, value)
        if relative and relative not in result:
            result.append(relative)
    if result:
        return result
    return _discover_indexed_files(task_id, fallback_prefix)


def build_output_package(
    task_id: str,
    task_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a portable artifact index for one task.

    All returned paths are relative to the task directory. Missing optional
    artifacts are represented as None or empty lists; host paths are never
    serialized into the package.
    """

    state = dict(task_state or {})
    root = _task_root(task_id)

    final_videos = _relative_files_from_state(
        task_id,
        state.get("videos"),
        fallback_prefix="final",
    )
    combined_videos = _relative_files_from_state(
        task_id,
        state.get("combined_videos"),
        fallback_prefix="combined",
    )

    script_file = _task_relative_existing_file(task_id, root / "script.json")
    subtitle_file = _task_relative_existing_file(
        task_id,
        state.get("subtitle_path") or root / "subtitle.srt",
    )
    audio_file = _task_relative_existing_file(
        task_id,
        state.get("audio_file") or root / "audio.mp3",
    )
    scene_plan = _task_relative_existing_file(task_id, root / "scene_plan.json")
    generation_manifest = _task_relative_existing_file(
        task_id,
        root / "generated_ai" / "generation_manifest.json",
    )

    scene_materials: list[str] = []
    if generation_manifest:
        # Local import avoids coupling the generic script-artifact writer to
        # the local-AI manifest module during normal module initialization.
        from app.services import generation_manifest as local_ai_manifest

        try:
            records = local_ai_manifest.local_ai_material_records(task_id)
        except (OSError, ValueError):
            records = []
        for record in records:
            relative = _task_relative_existing_file(
                task_id,
                record.get("asset"),
            )
            if relative and relative not in scene_materials:
                scene_materials.append(relative)

    return {
        "schema_version": OUTPUT_PACKAGE_SCHEMA_VERSION,
        "task_id": str(task_id),
        "final_videos": final_videos,
        "combined_videos": combined_videos,
        "script": script_file,
        "captions": subtitle_file,
        "audio": audio_file,
        "scene_plan": scene_plan,
        "generation_manifest": generation_manifest,
        "scene_materials": scene_materials,
    }


def has_local_ai_output_package(task_id: str) -> bool:
    """Return whether a task contains the local-AI manifest/scene-plan package."""

    root = _task_root(task_id)
    return (
        (root / "scene_plan.json").is_file()
        and (root / "generated_ai" / "generation_manifest.json").is_file()
    )
