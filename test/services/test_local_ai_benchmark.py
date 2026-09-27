import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.local_ai.base import GenerationResult
from app.services.local_ai.benchmark import (
    BenchmarkTarget,
    GpuSnapshot,
    GpuSummary,
    benchmark_target,
    gpu_snapshot,
    parse_target,
    run_benchmark_suite,
)


class _FakeSampler:
    def __init__(self, device_index):
        self.device_index = device_index
        self.summary = GpuSummary(
            device_index=device_index,
            device_name="Fake GPU",
            driver_version="999.1",
            peak_memory_used_mb=4096.0,
            memory_total_mb=24576.0,
            peak_utilization_percent=88.0,
            samples=4,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _FakeProvider:
    released = 0

    def __init__(self, provider_id, generation_mode="fast", *, fail=False):
        self.provider_id = provider_id
        self.generation_mode = generation_mode
        self.model_fingerprint = f"{provider_id}:{generation_mode}:test"
        self.max_scene_duration = 8.0 if provider_id == "ltx25_local" else 5.0
        self.settings = SimpleNamespace(device_id=2)
        self.preflight_calls = 0
        self.load_calls = 0
        self.generate_calls = 0
        self.fail = fail

    def safe_metadata(self):
        return {
            "model": "fake",
            "mode": self.generation_mode,
            "device_index": 2,
        }

    def preflight(self):
        self.preflight_calls += 1
        if self.fail:
            raise RuntimeError("preflight failed")

    def load_runtime(self):
        self.load_calls += 1

    def generate(self, scene, output_path):
        self.generate_calls += 1
        Path(output_path).write_bytes(
            f"{self.provider_id}:{scene.seed}".encode("utf-8")
        )

    def validate_output(self, output_path, scene):
        return GenerationResult(
            output_path=Path(output_path),
            actual_duration=scene.target_duration,
            width=576,
            height=1024,
            provider_id=self.provider_id,
            model_fingerprint=self.model_fingerprint,
        )

    @classmethod
    def release_runtime(cls):
        cls.released += 1


def test_parse_target_supports_wan_and_ltx_modes():
    assert parse_target("wan22_local") == BenchmarkTarget(
        "wan22_local",
        "fast",
    )
    assert parse_target("ltx25_local:fast") == BenchmarkTarget(
        "ltx25_local",
        "fast",
    )
    assert parse_target("ltx25_local:quality") == BenchmarkTarget(
        "ltx25_local",
        "quality",
    )


def test_parse_target_rejects_wan_quality():
    try:
        parse_target("wan22_local:quality")
    except ValueError as exc:
        assert "fast mode only" in str(exc)
    else:
        raise AssertionError("Wan quality benchmark should be rejected")


def test_gpu_snapshot_parses_nvidia_smi_without_gpu_dependency():
    completed = subprocess.CompletedProcess(
        [],
        0,
        stdout="0, NVIDIA Test, 555.42, 3210, 24576, 73\n",
    )
    with patch(
        "app.services.local_ai.benchmark.subprocess.run",
        return_value=completed,
    ):
        snapshot = gpu_snapshot(0)

    assert snapshot == GpuSnapshot(
        index=0,
        name="NVIDIA Test",
        driver_version="555.42",
        memory_used_mb=3210.0,
        memory_total_mb=24576.0,
        utilization_percent=73.0,
    )


def test_gpu_snapshot_returns_none_when_nvidia_smi_is_unavailable():
    with patch(
        "app.services.local_ai.benchmark.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert gpu_snapshot(0) is None


def test_benchmark_target_records_repeats_and_safe_gpu_summary():
    with tempfile.TemporaryDirectory() as temp:
        provider = _FakeProvider("ltx25_local", "fast")

        def factory(provider_id, generation_mode="fast"):
            assert provider_id == "ltx25_local"
            assert generation_mode == "fast"
            return provider

        result = benchmark_target(
            BenchmarkTarget("ltx25_local", "fast"),
            prompt="A cinematic benchmark scene",
            duration=3.0,
            aspect="9:16",
            seed=100,
            repeats=2,
            output_dir=Path(temp),
            provider_factory=factory,
            sampler_factory=_FakeSampler,
        )

        assert result.status == "success"
        assert provider.preflight_calls == 1
        assert provider.load_calls == 1
        assert provider.generate_calls == 2
        assert [item.seed for item in result.iterations] == [100, 101]
        assert all(Path(item.output_path).is_file() for item in result.iterations)
        assert result.gpu["device_name"] == "Fake GPU"
        assert result.gpu["peak_memory_used_mb"] == 4096.0
        assert result.generation_mean_seconds is not None


def test_benchmark_suite_writes_json_and_keeps_provider_failures_isolated():
    _FakeProvider.released = 0
    providers = {}

    def factory(provider_id, generation_mode="fast"):
        key = f"{provider_id}:{generation_mode}"
        provider = _FakeProvider(
            provider_id,
            generation_mode,
            fail=key == "wan22_local:fast",
        )
        providers[key] = provider
        return provider

    with tempfile.TemporaryDirectory() as temp:
        payload = run_benchmark_suite(
            [
                BenchmarkTarget("wan22_local", "fast"),
                BenchmarkTarget("ltx25_local", "quality"),
            ],
            prompt="Same scene for every provider",
            duration=3.0,
            aspect="9:16",
            seed=42,
            repeats=1,
            output_dir=Path(temp),
            provider_factory=factory,
            sampler_factory=_FakeSampler,
        )

        report = Path(payload["report_path"])
        assert report.is_file()
        persisted = json.loads(report.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == 1
        assert persisted["prompt"] == "Same scene for every provider"
        assert [item["status"] for item in persisted["results"]] == [
            "failed",
            "success",
        ]
        assert persisted["results"][0]["error_type"] == "RuntimeError"
        assert (
            persisted["results"][1]["provider_metadata"]["mode"]
            == "quality"
        )
        assert _FakeProvider.released == 2
