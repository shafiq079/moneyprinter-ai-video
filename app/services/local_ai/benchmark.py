from __future__ import annotations

import json
import math
import statistics
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import create_provider
from .base import GenerationResult, SceneSpec


@dataclass(frozen=True, slots=True)
class BenchmarkTarget:
    provider_id: str
    generation_mode: str = "fast"

    @property
    def label(self) -> str:
        return f"{self.provider_id}:{self.generation_mode}"


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    index: int
    name: str
    driver_version: str
    memory_used_mb: float
    memory_total_mb: float
    utilization_percent: float


@dataclass(slots=True)
class GpuSummary:
    device_index: int | None = None
    device_name: str | None = None
    driver_version: str | None = None
    peak_memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    peak_utilization_percent: float | None = None
    samples: int = 0

    def observe(self, snapshot: GpuSnapshot) -> None:
        self.device_index = snapshot.index
        self.device_name = snapshot.name
        self.driver_version = snapshot.driver_version
        self.memory_total_mb = snapshot.memory_total_mb
        self.peak_memory_used_mb = max(
            float(self.peak_memory_used_mb or 0.0),
            snapshot.memory_used_mb,
        )
        self.peak_utilization_percent = max(
            float(self.peak_utilization_percent or 0.0),
            snapshot.utilization_percent,
        )
        self.samples += 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkIteration:
    index: int
    seed: int
    generation_seconds: float
    validation_seconds: float
    output_path: str
    output_size_bytes: int
    actual_duration: float
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkResult:
    provider_id: str
    generation_mode: str
    status: str
    model_fingerprint: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    preflight_seconds: float | None = None
    load_seconds: float | None = None
    iterations: list[BenchmarkIteration] = field(default_factory=list)
    generation_mean_seconds: float | None = None
    generation_min_seconds: float | None = None
    generation_max_seconds: float | None = None
    gpu: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    def finalize(self) -> None:
        values = [
            item.generation_seconds
            for item in self.iterations
        ]
        if not values:
            return
        self.generation_mean_seconds = statistics.fmean(values)
        self.generation_min_seconds = min(values)
        self.generation_max_seconds = max(values)

    def to_dict(self) -> dict[str, Any]:
        self.finalize()
        return {
            "provider_id": self.provider_id,
            "generation_mode": self.generation_mode,
            "status": self.status,
            "model_fingerprint": self.model_fingerprint,
            "provider_metadata": dict(self.provider_metadata),
            "preflight_seconds": self.preflight_seconds,
            "load_seconds": self.load_seconds,
            "iterations": [item.to_dict() for item in self.iterations],
            "generation_mean_seconds": self.generation_mean_seconds,
            "generation_min_seconds": self.generation_min_seconds,
            "generation_max_seconds": self.generation_max_seconds,
            "gpu": dict(self.gpu),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def parse_target(value: str) -> BenchmarkTarget:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("benchmark target must not be empty")

    if ":" in raw:
        provider_id, generation_mode = raw.split(":", 1)
    else:
        provider_id, generation_mode = raw, "fast"

    provider_id = provider_id.strip()
    generation_mode = generation_mode.strip().lower()
    if provider_id not in {"wan22_local", "ltx25_local", "ltx25_hf"}:
        raise ValueError(
            "benchmark provider must be wan22_local, ltx25_local, or ltx25_hf"
        )
    if generation_mode not in {"fast", "quality"}:
        raise ValueError("benchmark mode must be fast or quality")
    if provider_id == "wan22_local" and generation_mode != "fast":
        raise ValueError("Wan 2.2 benchmark supports fast mode only")
    if provider_id == "ltx25_hf" and generation_mode != "fast":
        raise ValueError("LTX 2.5 Hugging Face benchmark supports fast mode only")
    return BenchmarkTarget(
        provider_id=provider_id,
        generation_mode=generation_mode,
    )


def _safe_float(value: str) -> float:
    parsed = float(value.strip())
    if not math.isfinite(parsed):
        raise ValueError("non-finite GPU metric")
    return parsed


def gpu_snapshot(device_index: int) -> GpuSnapshot | None:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,driver_version,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
        "-i",
        str(int(device_index)),
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    line = next(
        (
            item.strip()
            for item in completed.stdout.splitlines()
            if item.strip()
        ),
        "",
    )
    parts = [item.strip() for item in line.split(",")]
    if len(parts) != 6:
        return None
    try:
        return GpuSnapshot(
            index=int(parts[0]),
            name=parts[1],
            driver_version=parts[2],
            memory_used_mb=_safe_float(parts[3]),
            memory_total_mb=_safe_float(parts[4]),
            utilization_percent=_safe_float(parts[5]),
        )
    except (TypeError, ValueError):
        return None


class GpuSampler:
    def __init__(
        self,
        device_index: int,
        *,
        interval_seconds: float = 0.25,
        snapshot_fn: Callable[[int], GpuSnapshot | None] = gpu_snapshot,
    ) -> None:
        self.device_index = int(device_index)
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.snapshot_fn = snapshot_fn
        self.summary = GpuSummary()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = self.snapshot_fn(self.device_index)
            if snapshot is not None:
                self.summary.observe(snapshot)
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "GpuSampler":
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"gpu-benchmark-sampler-{self.device_index}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 4))
        self._thread = None


def _provider_uses_local_gpu(provider: Any) -> bool:
    return bool(getattr(provider, "uses_local_gpu", True))


def _provider_device_index(provider: Any) -> int:
    settings = getattr(provider, "settings", None)
    value = getattr(settings, "device_id", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _release_provider_runtime(provider: Any) -> None:
    releaser = getattr(type(provider), "release_runtime", None)
    if callable(releaser):
        releaser()


def _provider_metadata(provider: Any) -> dict[str, Any]:
    getter = getattr(provider, "safe_metadata", None)
    if not callable(getter):
        return {}
    value = getter()
    return dict(value) if isinstance(value, dict) else {}


def benchmark_target(
    target: BenchmarkTarget,
    *,
    prompt: str,
    duration: float,
    aspect: str,
    seed: int,
    repeats: int,
    output_dir: Path,
    provider_factory: Callable[..., Any] = create_provider,
    sampler_factory: Callable[..., GpuSampler] = GpuSampler,
) -> BenchmarkResult:
    if not str(prompt or "").strip():
        raise ValueError("benchmark prompt must not be empty")
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("benchmark duration must be positive")
    if aspect not in {"9:16", "16:9", "1:1"}:
        raise ValueError("benchmark aspect must be 9:16, 16:9, or 1:1")
    repeats = int(repeats)
    if repeats < 1:
        raise ValueError("benchmark repeats must be >= 1")
    seed = int(seed)
    if seed < 0:
        raise ValueError("benchmark seed must be >= 0")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = BenchmarkResult(
        provider_id=target.provider_id,
        generation_mode=target.generation_mode,
        status="failed",
    )
    provider = None
    try:
        provider = provider_factory(
            target.provider_id,
            generation_mode=target.generation_mode,
        )
        if duration > float(getattr(provider, "max_scene_duration", duration)):
            raise ValueError(
                f"{target.label} supports at most "
                f"{provider.max_scene_duration:.1f}s per benchmark scene"
            )

        result.model_fingerprint = str(
            getattr(provider, "model_fingerprint", "") or ""
        )
        result.provider_metadata = _provider_metadata(provider)

        started = time.perf_counter()
        provider.preflight()
        result.preflight_seconds = time.perf_counter() - started

        def run_iterations() -> None:
            started = time.perf_counter()
            provider.load_runtime()
            result.load_seconds = time.perf_counter() - started

            for index in range(repeats):
                iteration_seed = seed + index
                scene = SceneSpec(
                    scene_id=index + 1,
                    narration_segment="benchmark",
                    prompt=str(prompt).strip(),
                    target_duration=duration,
                    aspect=aspect,
                    seed=iteration_seed,
                    provider_settings={"mode": target.generation_mode},
                )
                output_path = output_dir / (
                    f"{target.provider_id}-{target.generation_mode}-"
                    f"r{index + 1:02d}.mp4"
                )

                started = time.perf_counter()
                provider.generate(scene, output_path)
                generation_seconds = time.perf_counter() - started

                started = time.perf_counter()
                validated: GenerationResult = provider.validate_output(
                    output_path,
                    scene,
                )
                validation_seconds = time.perf_counter() - started

                result.iterations.append(
                    BenchmarkIteration(
                        index=index + 1,
                        seed=iteration_seed,
                        generation_seconds=generation_seconds,
                        validation_seconds=validation_seconds,
                        output_path=str(output_path),
                        output_size_bytes=output_path.stat().st_size,
                        actual_duration=float(validated.actual_duration),
                        width=int(validated.width),
                        height=int(validated.height),
                    )
                )

        if _provider_uses_local_gpu(provider):
            device_index = _provider_device_index(provider)
            with sampler_factory(device_index) as sampler:
                run_iterations()
                result.gpu = sampler.summary.to_dict()
        else:
            run_iterations()
            result.gpu = {
                "measurement_scope": "remote_backend",
                "samples": 0,
            }

        result.status = "success"
        result.finalize()
        return result
    except Exception as exc:
        result.error_type = type(exc).__name__
        result.error_message = str(exc)
        result.finalize()
        return result
    finally:
        if provider is not None:
            _release_provider_runtime(provider)


def run_benchmark_suite(
    targets: Iterable[BenchmarkTarget],
    *,
    prompt: str,
    duration: float,
    aspect: str,
    seed: int,
    repeats: int,
    output_dir: Path,
    provider_factory: Callable[..., Any] = create_provider,
    sampler_factory: Callable[..., GpuSampler] = GpuSampler,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_list = list(targets)
    if not target_list:
        raise ValueError("at least one benchmark target is required")

    results = [
        benchmark_target(
            target,
            prompt=prompt,
            duration=duration,
            aspect=aspect,
            seed=seed,
            repeats=repeats,
            output_dir=output_dir,
            provider_factory=provider_factory,
            sampler_factory=sampler_factory,
        )
        for target in target_list
    ]
    payload = {
        "schema_version": 1,
        "prompt": str(prompt).strip(),
        "duration": float(duration),
        "aspect": aspect,
        "base_seed": int(seed),
        "repeats": int(repeats),
        "results": [result.to_dict() for result in results],
    }
    report_path = output_dir / "benchmark.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["report_path"] = str(report_path)
    return payload
