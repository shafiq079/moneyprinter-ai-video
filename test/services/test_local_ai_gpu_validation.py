import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import generation_manifest
from app.services.local_ai.base import SceneSpec
from app.services.local_ai.benchmark import BenchmarkTarget, GpuSummary
from app.services.local_ai.gpu_validation import run_gpu_validation_suite


class _FakeSampler:
    def __init__(self, device_index):
        self.summary = GpuSummary(
            device_index=device_index,
            device_name="Validation GPU",
            driver_version="999.0",
            peak_memory_used_mb=6000.0,
            memory_total_mb=24000.0,
            peak_utilization_percent=91.0,
            samples=5,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _ValidationProvider:
    released = 0

    def __init__(self, provider_id, generation_mode="fast", *, fail_preflight=False):
        self.provider_id = provider_id
        self.generation_mode = generation_mode
        self.model_fingerprint = f"{provider_id}:{generation_mode}:validation"
        self.max_scene_duration = 8.0 if provider_id == "ltx25_local" else 5.0
        self.base_seed = 42
        self.settings = SimpleNamespace(device_id=0)
        self.fail_preflight = fail_preflight

    def preflight(self):
        if self.fail_preflight:
            raise RuntimeError("quality resources are unavailable")

    def safe_metadata(self):
        return {
            "model": "validation-model",
            "mode": self.generation_mode,
            "device_index": 0,
            "worker_python_version": "3.11.9",
            "worker_torch_version": "2.8.0+cu128",
            "worker_cuda_version": "12.8",
            "worker_numpy_version": "2.1.3",
        }

    def generation_settings(self):
        return {"mode": self.generation_mode}

    @classmethod
    def release_runtime(cls):
        cls.released += 1


def _fake_generate_materials(task_root):
    def generate(task_id, *, provider, scenes):
        manifest = generation_manifest.prepare_manifest(
            task_id,
            provider_id=provider.provider_id,
            model_fingerprint=provider.model_fingerprint,
            scenes=scenes,
            provider_metadata=provider.safe_metadata(),
        )
        manifest["telemetry"]["runtime_load_count"] = 1
        paths = []
        for scene in scenes:
            record = generation_manifest.scene_record(manifest, scene.scene_id)
            relative, final_path, _ = generation_manifest.next_scene_version(
                task_id, scene.scene_id, []
            )
            final_path.write_bytes(b"scene-video")
            record["status"] = "ready"
            record["active_asset"] = relative
            record["actual_duration"] = scene.target_duration
            record["versions"] = [relative]
            generation_manifest.remember_scene_version(
                record,
                relative,
                actual_duration=scene.target_duration,
            )
            paths.append(str(final_path))
        generation_manifest.save_manifest(task_id, manifest)
        return paths

    return generate


def _fake_final_renderer(task_root):
    def render(task_id, _params, _materials, _audio, _subtitle, _duration, **_kwargs):
        root = Path(task_root(task_id))
        combined = root / "combined-1.mp4"
        final = root / "final-1.mp4"
        combined.write_bytes(b"combined-video")
        final.write_bytes(b"final-video")
        return [str(final)], [str(combined)], []

    return render


def _fake_regenerate(task_root):
    def regenerate(task_id, scene_id, *, seed=None, prompt=None):
        manifest = generation_manifest.load_manifest(task_id)
        record = generation_manifest.scene_record(manifest, int(scene_id))
        old_versions = list(record.get("versions") or [])
        scene = SceneSpec(
            scene_id=int(scene_id),
            narration_segment=str(record.get("narration_segment") or ""),
            prompt=str(prompt or record.get("prompt") or "validation"),
            target_duration=float(record["target_duration"]),
            aspect=str(record["aspect"]),
            seed=int(seed if seed is not None else record["seed"]),
            provider_settings=dict(record.get("provider_settings") or {}),
        )
        relative, final_path, _ = generation_manifest.next_scene_version(
            task_id,
            int(scene_id),
            old_versions,
        )
        final_path.write_bytes(b"regenerated-scene")
        record.update(scene.to_dict())
        record["status"] = "ready"
        record["active_asset"] = relative
        record["versions"] = old_versions + [relative]
        generation_manifest.remember_scene_version(
            record,
            relative,
            actual_duration=scene.target_duration,
        )
        generation_manifest.save_manifest(task_id, manifest)
        root = Path(task_root(task_id))
        final = root / "final-1.mp4"
        final.write_bytes(b"regenerated-final")
        return {"scene_id": int(scene_id), "videos": [str(final)]}

    return regenerate


def _fake_rerender(task_root):
    def rerender(task_id):
        root = Path(task_root(task_id))
        final = root / "final-1.mp4"
        final.write_bytes(b"rerendered-final")
        return {"videos": [str(final)], "render_only": True}

    return rerender


def test_gpu_validation_pack_passes_required_targets_and_skips_unavailable_quality():
    _ValidationProvider.released = 0
    providers = {}

    def provider_factory(provider_id, generation_mode="fast"):
        label = f"{provider_id}:{generation_mode}"
        provider = _ValidationProvider(
            provider_id,
            generation_mode,
            fail_preflight=label == "ltx25_local:quality",
        )
        providers[label] = provider
        return provider

    with tempfile.TemporaryDirectory() as temp:
        task_base = Path(temp) / "tasks"
        report_dir = Path(temp) / "report"

        def task_dir(task_id=None):
            root = task_base if task_id is None else task_base / str(task_id)
            root.mkdir(parents=True, exist_ok=True)
            return str(root)

        with (
            patch("app.services.local_ai.gpu_validation.utils.task_dir", task_dir),
            patch("app.services.generation_manifest.utils.task_dir", task_dir),
            patch("app.services.scene_planner.utils.task_dir", task_dir),
            patch("app.services.task_artifacts.utils.task_dir", task_dir),
            patch("app.services.task.utils.task_dir", task_dir),
            patch(
                "app.services.local_ai.gpu_validation.validate_output_storage"
            ),
            patch(
                "app.services.local_ai.gpu_validation.voice.generate_silent_audio",
                side_effect=lambda _duration, output: (
                    Path(output).write_bytes(b"audio") is None
                ) or True,
            ),
            patch(
                "app.services.local_ai.gpu_validation.voice.get_audio_duration",
                return_value=6.0,
            ),
        ):
            payload = run_gpu_validation_suite(
                [
                    BenchmarkTarget("wan22_local", "fast"),
                    BenchmarkTarget("ltx25_local", "fast"),
                    BenchmarkTarget("ltx25_local", "quality"),
                ],
                script="First validation scene. Second validation scene.",
                scene_count=2,
                scene_duration=3,
                report_dir=report_dir,
                provider_factory=provider_factory,
                sampler_factory=_FakeSampler,
                generate_materials_fn=_fake_generate_materials(task_dir),
                generate_final_videos_fn=_fake_final_renderer(task_dir),
                regenerate_scene_fn=_fake_regenerate(task_dir),
                rerender_fn=_fake_rerender(task_dir),
            )

        assert payload["status"] == "passed"
        assert [item["status"] for item in payload["results"]] == [
            "passed",
            "passed",
            "skipped",
        ]
        for result in payload["results"][:2]:
            checks = {item["name"]: item["status"] for item in result["checks"]}
            assert checks["preflight"] == "passed"
            assert checks["worker_environment"] == "passed"
            assert checks["multi_scene_generation"] == "passed"
            assert checks["runtime_reuse"] == "passed"
            assert checks["final_media"] == "passed"
            assert checks["scene_regeneration"] == "passed"
            assert checks["render_only_rerender"] == "passed"
            assert checks["gpu_telemetry"] == "passed"
            assert checks["output_package"] == "passed"
            assert result["gpu"]["peak_memory_used_mb"] == 6000.0
            assert result["artifacts"]["scene_plan"] == "scene_plan.json"
            assert len(result["artifacts"]["scene_materials"]) == 2

        report = Path(payload["report_path"])
        persisted = json.loads(report.read_text(encoding="utf-8"))
        assert persisted["status"] == "passed"
        assert persisted["results"][2]["required"] is False
        assert "report_path" not in persisted
        assert _ValidationProvider.released == 3


def test_gpu_validation_pack_fails_when_required_preflight_is_unavailable():
    def provider_factory(provider_id, generation_mode="fast"):
        return _ValidationProvider(
            provider_id,
            generation_mode,
            fail_preflight=True,
        )

    with tempfile.TemporaryDirectory() as temp:
        with patch(
            "app.services.local_ai.gpu_validation.validate_output_storage"
        ):
            payload = run_gpu_validation_suite(
                [BenchmarkTarget("wan22_local", "fast")],
                script="First scene. Second scene.",
                report_dir=Path(temp),
                provider_factory=provider_factory,
                sampler_factory=_FakeSampler,
            )

        assert payload["status"] == "failed"
        assert payload["results"][0]["status"] == "failed"
        assert payload["results"][0]["required"] is True
        assert payload["results"][0]["checks"][-1]["name"] == "preflight"
