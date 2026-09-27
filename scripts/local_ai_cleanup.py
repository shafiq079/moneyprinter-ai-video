from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.local_ai.cleanup import (  # noqa: E402
    CleanupPolicy,
    cleanup_local_ai_storage,
)


def _at_least_two(value: str) -> int:
    parsed = int(value)
    if parsed < 2:
        raise argparse.ArgumentTypeError("keep-scene-versions must be >= 2")
    return parsed


def _non_negative(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clean local-AI temporary files, unreferenced scene clips and old "
            "scene versions. Dry-run is the default."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform deletions; without this flag only report eligible assets",
    )
    parser.add_argument(
        "--task-id",
        default="",
        help="limit cleanup to one task ID",
    )
    parser.add_argument(
        "--keep-scene-versions",
        type=_at_least_two,
        default=None,
        help="override configured number of scene versions to retain",
    )
    parser.add_argument(
        "--stale-temp-hours",
        type=_non_negative,
        default=None,
        help="override minimum age for temp/unreferenced files",
    )
    parser.add_argument(
        "--completed-task-retention-days",
        type=_non_negative,
        default=None,
        help=(
            "override completed-task retention; 0 disables whole-task deletion"
        ),
    )
    return parser


def _policy_from_args(args: argparse.Namespace) -> CleanupPolicy:
    configured = CleanupPolicy.from_config()
    return CleanupPolicy(
        keep_scene_versions=(
            args.keep_scene_versions
            if args.keep_scene_versions is not None
            else configured.keep_scene_versions
        ),
        stale_temp_hours=(
            args.stale_temp_hours
            if args.stale_temp_hours is not None
            else configured.stale_temp_hours
        ),
        completed_task_retention_days=(
            args.completed_task_retention_days
            if args.completed_task_retention_days is not None
            else configured.completed_task_retention_days
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = _policy_from_args(args)
    try:
        report = cleanup_local_ai_storage(
            policy=policy,
            dry_run=not args.apply,
            task_id=args.task_id.strip() or None,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2

    payload = report.to_dict()
    payload["status"] = "success"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
