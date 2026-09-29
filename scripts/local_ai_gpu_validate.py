from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.local_ai.benchmark import parse_target  # noqa: E402
from app.services.local_ai.gpu_validation import (  # noqa: E402
    run_gpu_validation_suite,
)


DEFAULT_TARGETS = (
    "wan22_local",
    "ltx25_local:fast",
    "ltx25_local:quality",
)

DEFAULT_SCRIPT = (
    "A quiet futuristic city wakes before sunrise. "
    "A lone electric train glides through reflective streets as warm light "
    "spreads between the buildings."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the manual real-GPU acceptance pack for local AI video. "
            "Wan and LTX Fast are required by default; LTX Quality may be "
            "reported as skipped when its preflight is unavailable."
        )
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        metavar="PROVIDER[:MODE]",
        help=(
            "validation target; repeat for multiple targets. Defaults to "
            "Wan 2.2, LTX Fast and LTX Quality."
        ),
    )
    parser.add_argument(
        "--script",
        default=DEFAULT_SCRIPT,
        help="offline validation narration/script; no remote LLM is used",
    )
    parser.add_argument(
        "--scene-count",
        type=int,
        default=2,
        help="minimum number of generated scenes per target (default: 2)",
    )
    parser.add_argument(
        "--scene-duration",
        type=int,
        default=3,
        help="target seconds per validation scene (default: 3)",
    )
    parser.add_argument(
        "--aspect",
        choices=("9:16", "16:9", "1:1"),
        default="9:16",
        help="validation aspect ratio",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="base deterministic seed",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("storage") / "validation" / "local-ai-gpu",
        help="directory for gpu-validation.json",
    )
    parser.add_argument(
        "--require-ltx-quality",
        action="store_true",
        help=(
            "treat an unavailable LTX Quality/DFR preflight as failure instead "
            "of SKIPPED"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = [
            parse_target(value)
            for value in (args.target or DEFAULT_TARGETS)
        ]
        payload = run_gpu_validation_suite(
            targets,
            script=args.script,
            scene_count=args.scene_count,
            scene_duration=args.scene_duration,
            aspect=args.aspect,
            seed=args.seed,
            report_dir=args.report_dir,
            require_ltx_quality=args.require_ltx_quality,
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

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
