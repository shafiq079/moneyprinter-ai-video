from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.local_ai.benchmark import (  # noqa: E402
    parse_target,
    run_benchmark_suite,
)


DEFAULT_TARGETS = (
    "wan22_local",
    "ltx25_local:fast",
    "ltx25_local:quality",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark AI video providers with the same scene prompt. "
            "Local targets require configured CUDA; remote targets use their "
            "configured backend."
        )
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        metavar="PROVIDER[:MODE]",
        help=(
            "benchmark target; repeat for multiple targets. "
            "Defaults to Wan 2.2, local LTX Fast, and local LTX Quality. "
            "Remote ltx25_hf must be selected explicitly to avoid spending quota."
        ),
    )
    parser.add_argument(
        "--prompt",
        default=(
            "A cinematic close-up of rain falling across a quiet neon-lit "
            "city street at night, realistic reflections, gentle camera push-in."
        ),
        help="identical visual prompt used for every provider",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="requested scene duration in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--aspect",
        choices=("9:16", "16:9", "1:1"),
        default="9:16",
        help="scene aspect ratio",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="base deterministic seed",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=2,
        help=(
            "number of generations per target after one runtime load; "
            "use >=2 to observe warm-runtime generation (default: 2)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("storage") / "benchmarks" / "local-ai",
        help="directory for clips and benchmark.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.seed < 0:
        raise SystemExit("--seed must be >= 0")
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.duration <= 0:
        raise SystemExit("--duration must be > 0")

    try:
        targets = [
            parse_target(value)
            for value in (args.target or DEFAULT_TARGETS)
        ]
        payload = run_benchmark_suite(
            targets,
            prompt=args.prompt,
            duration=args.duration,
            aspect=args.aspect,
            seed=args.seed,
            repeats=args.repeats,
            output_dir=args.output_dir,
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
    return 0 if all(
        item.get("status") == "success"
        for item in payload["results"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
