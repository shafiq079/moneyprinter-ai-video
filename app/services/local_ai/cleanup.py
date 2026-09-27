from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import config
from app.models import const
from app.services import generation_manifest
from app.services import state as sm
from app.utils import utils


_VERSION_FILE_RE = re.compile(r"^v(\d+)\.mp4$")
_TEMP_FILE_PATTERNS = (
    re.compile(r"^\.v\d+\.partial\.mp4$"),
    re.compile(r"^\.v\d+\.wan-raw\.mp4$"),
    re.compile(r"^\.v\d+\.ltx-raw\.mp4$"),
    re.compile(r"^\.generation-manifest-.*\.json\.tmp$"),
    re.compile(r"^\.scene-plan-.*\.json\.tmp$"),
)
_ACTIVE_CROSS_POST_STATES = {
    const.CROSS_POST_STATE_PENDING,
    const.CROSS_POST_STATE_PROCESSING,
}


@dataclass(frozen=True, slots=True)
class CleanupPolicy:
    keep_scene_versions: int = 2
    stale_temp_hours: float = 24.0
    completed_task_retention_days: float = 0.0

    @classmethod
    def from_config(cls) -> "CleanupPolicy":
        section = dict(getattr(config, "local_ai_cleanup", {}) or {})
        return cls(
            keep_scene_versions=_bounded_int(
                section.get("keep_scene_versions", 2),
                default=2,
                minimum=2,
            ),
            stale_temp_hours=_non_negative_float(
                section.get("stale_temp_hours", 24),
                default=24.0,
            ),
            completed_task_retention_days=_non_negative_float(
                section.get("completed_task_retention_days", 0),
                default=0.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class CleanupEntry:
    task_id: str
    relative_path: str
    reason: str
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CleanupReport:
    dry_run: bool
    policy: CleanupPolicy
    removed: list[CleanupEntry] = field(default_factory=list)
    skipped_tasks: list[dict[str, str]] = field(default_factory=list)
    inspected_tasks: int = 0
    removed_task_count: int = 0

    @property
    def reclaimed_bytes(self) -> int:
        return sum(item.size_bytes for item in self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "policy": asdict(self.policy),
            "inspected_tasks": self.inspected_tasks,
            "removed_task_count": self.removed_task_count,
            "reclaimed_bytes": self.reclaimed_bytes,
            "removed": [item.to_dict() for item in self.removed],
            "skipped_tasks": list(self.skipped_tasks),
        }


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _non_negative_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 0:
        return 0.0
    return parsed


def _task_is_busy(task: dict[str, Any] | None) -> bool:
    if not task:
        return False
    state = task.get("state")
    try:
        state = int(state)
    except (TypeError, ValueError):
        pass
    return (
        state == const.TASK_STATE_PROCESSING
        or task.get("cross_post_state") in _ACTIVE_CROSS_POST_STATES
    )


def _task_root(task_id: str) -> Path:
    tasks_root = Path(utils.task_dir()).resolve()
    candidate = (tasks_root / str(task_id)).resolve()
    try:
        candidate.relative_to(tasks_root)
    except ValueError as exc:
        raise ValueError("cleanup task escapes task storage") from exc
    return candidate


def _version_number(relative_path: str) -> int:
    match = _VERSION_FILE_RE.match(Path(relative_path).name)
    return int(match.group(1)) if match else -1


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _directory_size(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return total
    for current_root, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not Path(current_root, name).is_symlink()
        ]
        for name in files:
            candidate = Path(current_root, name)
            if candidate.is_symlink():
                continue
            total += _file_size(candidate)
    return total


def _age_seconds(path: Path, now: float) -> float:
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return 0.0


def _record_entry(
    report: CleanupReport,
    *,
    task_id: str,
    relative_path: str,
    reason: str,
    path: Path | None = None,
    size_bytes: int | None = None,
) -> None:
    report.removed.append(
        CleanupEntry(
            task_id=str(task_id),
            relative_path=str(relative_path),
            reason=str(reason),
            size_bytes=(
                int(size_bytes)
                if size_bytes is not None
                else _file_size(path) if path is not None else 0
            ),
        )
    )


def _unlink_if_requested(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _cleanup_scene_versions(
    task_id: str,
    manifest: dict[str, Any],
    *,
    policy: CleanupPolicy,
    report: CleanupReport,
) -> bool:
    changed = False
    dry_run = report.dry_run

    for record in manifest.get("scenes", []):
        if not isinstance(record, dict):
            continue

        versions = [
            str(value)
            for value in record.get("versions", [])
            if isinstance(value, str) and value
        ]
        # Deduplicate while preserving historical order.
        versions = list(dict.fromkeys(versions))
        active = str(record.get("active_asset") or "")
        if active and active not in versions:
            versions.append(active)

        keep: set[str] = {active} if active else set()
        for relative in sorted(
            versions,
            key=_version_number,
            reverse=True,
        ):
            if len(keep) >= policy.keep_scene_versions:
                break
            keep.add(relative)

        retained: list[str] = []
        metadata = dict(record.get("version_metadata") or {})
        for relative in versions:
            if relative in keep:
                retained.append(relative)
                continue

            try:
                candidate = generation_manifest.resolve_asset(
                    task_id,
                    relative,
                )
            except ValueError:
                # Never follow or delete an unsafe path. Drop only the stale
                # non-active manifest reference when cleanup is applied.
                _record_entry(
                    report,
                    task_id=task_id,
                    relative_path=relative,
                    reason="unsafe_non_active_scene_reference",
                )
                if not dry_run:
                    metadata.pop(relative, None)
                    changed = True
                else:
                    retained.append(relative)
                continue

            _record_entry(
                report,
                task_id=task_id,
                relative_path=relative,
                reason="old_scene_version",
                path=candidate,
            )
            _unlink_if_requested(candidate, dry_run=dry_run)
            if dry_run:
                retained.append(relative)
            else:
                metadata.pop(relative, None)
                changed = True

        if not dry_run and (
            retained != versions
            or metadata != dict(record.get("version_metadata") or {})
        ):
            record["versions"] = retained
            record["version_metadata"] = metadata
            changed = True

    return changed


def _cleanup_stale_generated_files(
    task_id: str,
    manifest: dict[str, Any] | None,
    *,
    policy: CleanupPolicy,
    report: CleanupReport,
    now: float,
) -> None:
    task_root = _task_root(task_id)
    generated_root = task_root / "generated_ai"
    stale_seconds = policy.stale_temp_hours * 3600.0

    registered: set[str] = set()
    if manifest:
        for record in manifest.get("scenes", []):
            if not isinstance(record, dict):
                continue
            registered.update(
                str(value)
                for value in record.get("versions", [])
                if isinstance(value, str) and value
            )
            active = record.get("active_asset")
            if isinstance(active, str) and active:
                registered.add(active)

    scan_roots = [task_root, generated_root]
    seen: set[Path] = set()
    for scan_root in scan_roots:
        if not scan_root.is_dir():
            continue
        for current_root, directories, files in os.walk(
            scan_root,
            followlinks=False,
        ):
            directories[:] = [
                name
                for name in directories
                if not Path(current_root, name).is_symlink()
            ]
            for name in files:
                candidate = Path(current_root, name)
                if candidate in seen or candidate.is_symlink():
                    continue
                seen.add(candidate)

                try:
                    relative = candidate.relative_to(task_root).as_posix()
                except ValueError:
                    continue

                is_temp = any(
                    pattern.match(name)
                    for pattern in _TEMP_FILE_PATTERNS
                )
                is_unreferenced_scene = (
                    relative.startswith("generated_ai/scene-")
                    and _VERSION_FILE_RE.match(name) is not None
                    and relative not in registered
                )
                if not is_temp and not is_unreferenced_scene:
                    continue
                if _age_seconds(candidate, now) < stale_seconds:
                    continue

                _record_entry(
                    report,
                    task_id=task_id,
                    relative_path=relative,
                    reason=(
                        "stale_temporary_asset"
                        if is_temp
                        else "unreferenced_scene_asset"
                    ),
                    path=candidate,
                )
                _unlink_if_requested(candidate, dry_run=report.dry_run)


def cleanup_task_assets(
    task_id: str,
    *,
    policy: CleanupPolicy | None = None,
    dry_run: bool = True,
    now: float | None = None,
    report: CleanupReport | None = None,
) -> CleanupReport:
    policy = policy or CleanupPolicy.from_config()
    report = report or CleanupReport(
        dry_run=bool(dry_run),
        policy=policy,
    )
    report.inspected_tasks += 1

    task = sm.state.get_task(task_id)
    if _task_is_busy(task):
        report.skipped_tasks.append(
            {
                "task_id": str(task_id),
                "reason": "task_is_busy",
            }
        )
        return report

    task_root = _task_root(task_id)
    if not task_root.is_dir():
        report.skipped_tasks.append(
            {
                "task_id": str(task_id),
                "reason": "task_directory_missing",
            }
        )
        return report

    manifest = generation_manifest.load_manifest(task_id)
    changed = False
    if manifest is not None:
        changed = _cleanup_scene_versions(
            task_id,
            manifest,
            policy=policy,
            report=report,
        )

    _cleanup_stale_generated_files(
        task_id,
        manifest,
        policy=policy,
        report=report,
        now=time.time() if now is None else float(now),
    )

    if changed and not report.dry_run and manifest is not None:
        generation_manifest.save_manifest(task_id, manifest)
    return report


def _is_completed_task(
    task_id: str,
    task_root: Path,
    state: dict[str, Any] | None,
) -> bool:
    if _task_is_busy(state):
        return False
    raw_state = (state or {}).get("state")
    try:
        raw_state = int(raw_state)
    except (TypeError, ValueError):
        pass
    if raw_state == const.TASK_STATE_COMPLETE:
        return True
    return any(task_root.glob("final-*.mp4"))


def _delete_expired_completed_task(
    task_id: str,
    *,
    task_root: Path,
    policy: CleanupPolicy,
    report: CleanupReport,
    now: float,
) -> bool:
    days = policy.completed_task_retention_days
    if days <= 0:
        return False

    state = sm.state.get_task(task_id)
    if not _is_completed_task(task_id, task_root, state):
        return False
    if _age_seconds(task_root, now) < days * 86400.0:
        return False

    size = _directory_size(task_root)
    _record_entry(
        report,
        task_id=task_id,
        relative_path=".",
        reason="expired_completed_task",
        size_bytes=size,
    )
    report.removed_task_count += 1
    if not report.dry_run:
        shutil.rmtree(task_root)
        sm.state.delete_task(task_id)
    return True


def cleanup_local_ai_storage(
    *,
    policy: CleanupPolicy | None = None,
    dry_run: bool = True,
    task_id: str | None = None,
    now: float | None = None,
) -> CleanupReport:
    policy = policy or CleanupPolicy.from_config()
    report = CleanupReport(
        dry_run=bool(dry_run),
        policy=policy,
    )
    now_value = time.time() if now is None else float(now)

    if task_id:
        task_root = _task_root(task_id)
        if task_root.is_dir() and _delete_expired_completed_task(
            task_id,
            task_root=task_root,
            policy=policy,
            report=report,
            now=now_value,
        ):
            report.inspected_tasks += 1
            return report
        return cleanup_task_assets(
            task_id,
            policy=policy,
            dry_run=dry_run,
            now=now_value,
            report=report,
        )

    tasks_root = Path(utils.task_dir())
    if not tasks_root.is_dir():
        return report

    with os.scandir(tasks_root) as entries:
        task_entries = [
            entry
            for entry in entries
            if not entry.name.startswith(".")
            and entry.is_dir(follow_symlinks=False)
        ]

    for entry in task_entries:
        current_task_id = entry.name
        task_root = Path(entry.path)
        if _delete_expired_completed_task(
            current_task_id,
            task_root=task_root,
            policy=policy,
            report=report,
            now=now_value,
        ):
            report.inspected_tasks += 1
            continue
        cleanup_task_assets(
            current_task_id,
            policy=policy,
            dry_run=dry_run,
            now=now_value,
            report=report,
        )
    return report
