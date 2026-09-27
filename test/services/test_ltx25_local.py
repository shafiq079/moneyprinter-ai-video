import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import generation_manifest, scene_planner, task
from app.services.local_ai.base import SceneSpec
from app.services.local_ai.ltx25 import (
    LTX25_SOURCE_ID,
    LTX25ConfigurationError,
    LTX25LocalProvider,
    LTX25Settings,
)
from app.utils import utils


class _FakeWorker:
    instances = []

    def __init__(self, settings, generation_mode="fast"):
        self.settings = settings
        self.generation_mode = generation_mode
        self.load_count = 0
        self.generate_count = 0
        self.closed = False
        type(self).instances.append(self)

    def load(self):
        self.load_count += 1

    def request(self, payload):
        if payload["action"] != "generate":
            return {"ok": True}
        self.generate_count += 1
        output = Path(payload["output_path"])
        aspect = payload["aspect"]
        if aspect == "9:16":
            size = "180x320"
        elif aspect == "16:9":
            size = "320x180"
        else:
            size = "240x240"
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={size}:r=24:d={float(payload['duration']) + 0.08:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        return {"ok": True}

    def close(self):
        self.closed = True


class LTX25TestCase(unittest.TestCase):
    def setUp(self):
        LTX25LocalProvider.release_runtime()
        _FakeWorker.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "LTX-2"
        (self.repo / "packages" / "ltx-core" / "src" / "ltx_core").mkdir(
            parents=True
        )
        (
            self.repo
            / "packages"
            / "ltx-pipelines"
            / "src"
            / "ltx_pipelines"
            / "utils"
        ).mkdir(parents=True)
        for relative in (
            "packages/ltx-core/src/ltx_core/__init__.py",
            "packages/ltx-pipelines/src/ltx_pipelines/distilled.py",
            "packages/ltx-pipelines/src/ltx_pipelines/dfr_pipeline.py",
            "packages/ltx-pipelines/src/ltx_pipelines/utils/model_paths.py",
        ):
            (self.repo / relative).write_text("# test\n", encoding="utf-8")

        self.models = self.root / "models"
        self.models.mkdir()
        self.transformer = self.models / "ltx-2.5-distilled-transformer.safetensors"
        self.text_encoder = self.models / "gemma4-ltx.safetensors"
        self.video_vae = self.models / "video-vae.safetensors"
        self.audio_vae = self.models / "audio-vae.safetensors"
        self.spatial = self.models / "spatial-upscaler.safetensors"
        self.detailing = self.models / "ltx-2.5-detailing-lora.safetensors"
        for path in (
            self.transformer,
            self.text_encoder,
            self.video_vae,
            self.audio_vae,
            self.spatial,
            self.detailing,
        ):
            path.write_bytes(b"test-model")

        self.settings = LTX25Settings(
            repo_path=self.repo,
            transformer_path=self.transformer,
            text_encoder_path=self.text_encoder,
            video_vae_path=self.video_vae,
            audio_vae_path=self.audio_vae,
            spatial_upsampler_path=self.spatial,
            python_executable="python",
            device_id=0,
            base_seed=91,
            offload_mode="cpu",
            fp8_cast=True,
        )
        self.quality_settings = LTX25Settings(
            repo_path=self.repo,
            transformer_path=self.transformer,
            text_encoder_path=self.text_encoder,
            video_vae_path=self.video_vae,
            audio_vae_path=self.audio_vae,
            spatial_upsampler_path=self.spatial,
            python_executable="python",
            detailing_lora_path=self.detailing,
            device_id=0,
            base_seed=91,
            offload_mode="cpu",
            fp8_cast=True,
        )

    def tearDown(self):
        LTX25LocalProvider.release_runtime()
        self.temp.cleanup()


class TestLTX25Configuration(LTX25TestCase):
    def test_missing_model_file_is_rejected(self):
        self.audio_vae.unlink()
        with self.assertRaisesRegex(
            LTX25ConfigurationError,
            "missing one or more required",
        ):
            LTX25LocalProvider(settings=self.settings)

    def test_fingerprint_and_metadata_do_not_persist_host_paths(self):
        provider = LTX25LocalProvider(settings=self.settings)
        payload = json.dumps(
            {
                "fingerprint": provider.model_fingerprint,
                "metadata": provider.safe_metadata(),
            }
        )
        self.assertTrue(
            provider.model_fingerprint.startswith("ltx25-fast:sha256:")
        )
        self.assertEqual(provider.safe_metadata()["mode"], "fast")
        self.assertEqual(provider.safe_metadata()["output_audio"], "none")
        self.assertNotIn(str(self.repo), payload)
        self.assertNotIn(str(self.models), payload)

    def test_preflight_uses_configured_worker_without_importing_gpu_stack(self):
        provider = LTX25LocalProvider(settings=self.settings)
        response = "MPT_LTX25_JSON:" + json.dumps({"ok": True}) + "\n"
        completed = subprocess.CompletedProcess([], 0, stdout=response)

        with (
            patch(
                "app.services.local_ai.ltx25.utils.check_ffmpeg_ready",
                return_value=True,
            ),
            patch(
                "app.services.local_ai.ltx25.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            provider.preflight()

        command = run.call_args.args[0]
        self.assertIn("--preflight", command)
        self.assertIn("--offload-mode", command)
        self.assertIn("--fp8-cast", command)
        self.assertEqual(command[0], self.settings.python_executable)
        self.assertIn("--generation-mode", command)
        self.assertIn("fast", command)

    def test_quality_mode_requires_detailing_lora(self):
        with self.assertRaisesRegex(
            LTX25ConfigurationError,
            "detailing_lora_path",
        ):
            LTX25LocalProvider(
                settings=self.settings,
                generation_mode="quality",
            )

    def test_quality_mode_has_distinct_fingerprint_and_metadata(self):
        fast = LTX25LocalProvider(settings=self.quality_settings)
        quality = LTX25LocalProvider(
            settings=self.quality_settings,
            generation_mode="quality",
        )

        self.assertNotEqual(fast.model_fingerprint, quality.model_fingerprint)
        self.assertTrue(
            quality.model_fingerprint.startswith("ltx25-quality:sha256:")
        )
        self.assertEqual(quality.safe_metadata()["mode"], "quality")
        self.assertEqual(
            quality.generation_settings(),
            {"mode": "quality"},
        )

    def test_quality_preflight_passes_mode_and_detailing_asset(self):
        provider = LTX25LocalProvider(
            settings=self.quality_settings,
            generation_mode="quality",
        )
        response = "MPT_LTX25_JSON:" + json.dumps({"ok": True}) + "\n"
        completed = subprocess.CompletedProcess([], 0, stdout=response)

        with (
            patch(
                "app.services.local_ai.ltx25.utils.check_ffmpeg_ready",
                return_value=True,
            ),
            patch(
                "app.services.local_ai.ltx25.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            provider.preflight()

        command = run.call_args.args[0]
        mode_index = command.index("--generation-mode")
        detail_index = command.index("--detailing-lora")
        self.assertEqual(command[mode_index + 1], "quality")
        self.assertEqual(command[detail_index + 1], str(self.detailing))


class TestLTX25Runtime(LTX25TestCase):
    def test_runtime_is_reused_across_instances_and_scenes(self):
        scene_one = SceneSpec(1, "one", "forest", 1.0, "9:16", 91)
        scene_two = SceneSpec(2, "two", "mountain", 1.0, "9:16", 92)
        first_output = self.root / "one.mp4"
        second_output = self.root / "two.mp4"

        with patch.object(LTX25LocalProvider, "_worker_factory", _FakeWorker):
            first = LTX25LocalProvider(settings=self.settings)
            first.load_runtime()
            first.generate(scene_one, first_output)
            second = LTX25LocalProvider(settings=self.settings)
            second.load_runtime()
            second.generate(scene_two, second_output)

        self.assertEqual(len(_FakeWorker.instances), 1)
        worker = _FakeWorker.instances[0]
        self.assertGreaterEqual(worker.load_count, 1)
        self.assertEqual(worker.generate_count, 2)
        first.validate_output(first_output, scene_one)
        second.validate_output(second_output, scene_two)

    def test_model_change_replaces_persistent_worker(self):
        with patch.object(LTX25LocalProvider, "_worker_factory", _FakeWorker):
            first = LTX25LocalProvider(settings=self.settings)
            first.load_runtime()
            first_worker = _FakeWorker.instances[0]

            self.transformer.write_bytes(b"updated-model")
            second = LTX25LocalProvider(settings=self.settings)
            self.assertNotEqual(first.model_fingerprint, second.model_fingerprint)
            second.load_runtime()

        self.assertTrue(first_worker.closed)
        self.assertEqual(len(_FakeWorker.instances), 2)

    def test_scene_planner_respects_ltx_fast_eight_second_cap(self):
        provider = LTX25LocalProvider(settings=self.settings)
        scenes = scene_planner.plan_scenes(
            "A longer narration that needs more than one LTX scene.",
            audio_duration=17.0,
            max_scene_duration=min(10.0, provider.max_scene_duration),
            aspect="9:16",
            base_seed=provider.base_seed,
        )
        self.assertEqual(len(scenes), 3)
        self.assertTrue(all(scene.target_duration <= 8.0 for scene in scenes))
        self.assertEqual([scene.seed for scene in scenes], [91, 92, 93])

    def test_switching_fast_to_quality_replaces_cached_worker(self):
        with patch.object(LTX25LocalProvider, "_worker_factory", _FakeWorker):
            fast = LTX25LocalProvider(settings=self.quality_settings)
            fast.load_runtime()
            first_worker = _FakeWorker.instances[0]

            quality = LTX25LocalProvider(
                settings=self.quality_settings,
                generation_mode="quality",
            )
            quality.load_runtime()

        self.assertTrue(first_worker.closed)
        self.assertEqual(len(_FakeWorker.instances), 2)
        self.assertEqual(_FakeWorker.instances[1].generation_mode, "quality")


class TestLTX25TaskIntegration(LTX25TestCase):
    def test_pipeline_preflight_fails_before_script_when_ltx_is_not_ready(self):
        params = VideoParams(
            video_subject="test",
            video_script="Prepared script",
            video_source=LTX25_SOURCE_ID,
            subtitle_enabled=False,
            bgm_type="",
        )
        with (
            patch.object(task.sm.state, "update_task"),
            patch.object(
                task.local_ai,
                "prepare_provider",
                side_effect=LTX25ConfigurationError("model missing"),
            ),
            patch.object(
                task,
                "_mark_task_failed",
                return_value={"state": -1},
            ) as failed,
            patch.object(task, "generate_script") as generate_script,
        ):
            result = task._run_pipeline("ltx-preflight", params)

        self.assertEqual(result, {"state": -1})
        generate_script.assert_not_called()
        self.assertEqual(failed.call_args.args[1], "preflight")
        self.assertIn("LTX25ConfigurationError", failed.call_args.args[2])

    def test_task_material_path_uses_ltx_scene_cap_and_no_remote_download(self):
        class FakeLTXProvider:
            provider_id = LTX25_SOURCE_ID
            model_fingerprint = "ltx-test:v1"
            max_scene_duration = 8.0
            base_seed = 91

            def safe_metadata(self):
                return {
                    "model": "LTX-2.5",
                    "mode": "quality",
                    "output_audio": "none",
                }

            def generation_settings(self):
                return {"mode": "quality"}

            def preflight(self):
                return None

            def load_runtime(self):
                return None

            def generate(self, scene, output_path):
                size = "180x320" if scene.aspect == "9:16" else "320x180"
                command = [
                    utils.get_ffmpeg_binary(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        f"color=c=black:s={size}:r=24:"
                        f"d={float(scene.target_duration) + 0.08:.3f}"
                    ),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(output_path),
                ]
                completed = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr)

            def validate_output(self, output_path, scene):
                from app.services.local_ai.base import GenerationResult
                from app.services.local_ai.media import validate_video_clip

                probe = validate_video_clip(output_path, scene)
                return GenerationResult(
                    output_path=Path(output_path),
                    actual_duration=probe.duration,
                    width=probe.width,
                    height=probe.height,
                    provider_id=self.provider_id,
                    model_fingerprint=self.model_fingerprint,
                )

            def unload(self):
                return None

        params = VideoParams(
            video_subject="test",
            video_script="A prepared narration for a longer local LTX task.",
            video_source=LTX25_SOURCE_ID,
            local_ai_generation_mode="quality",
            local_ai_seed=120,
            video_aspect="9:16",
            video_clip_duration=10,
            subtitle_enabled=False,
            bgm_type="",
        )
        task_root = self.root / "task"
        with (
            patch.object(
                task.local_ai,
                "create_provider",
                return_value=FakeLTXProvider(),
            ),
            patch.object(task.material, "download_videos") as remote_download,
            patch.object(task.sm.state, "update_task"),
            patch.object(
                scene_planner.llm,
                "generate_json_response",
                side_effect=RuntimeError("offline test"),
            ),
            patch.object(utils, "task_dir", return_value=str(task_root)),
        ):
            materials = task.get_video_materials(
                "ltx-materials",
                params,
                [],
                17.0,
                video_script=params.video_script,
            )
            manifest = generation_manifest.load_manifest("ltx-materials")

        remote_download.assert_not_called()
        self.assertEqual(len(materials), 3)
        self.assertEqual(
            [scene["seed"] for scene in manifest["scenes"]],
            [120, 121, 122],
        )
        self.assertTrue(
            all(scene["target_duration"] <= 8.0 for scene in manifest["scenes"])
        )
        self.assertTrue(
            all(
                scene["provider_settings"] == {"mode": "quality"}
                for scene in manifest["scenes"]
            )
        )


class TestLTX25Manifest(LTX25TestCase):
    def test_manifest_records_safe_ltx_metadata(self):
        provider = LTX25LocalProvider(settings=self.settings)
        scene = SceneSpec(1, "one", "forest", 1.0, "9:16", 91)
        with patch.object(
            utils,
            "task_dir",
            return_value=str(self.root / "task"),
        ):
            manifest = generation_manifest.prepare_manifest(
                "ltx-task",
                provider_id=LTX25_SOURCE_ID,
                model_fingerprint=provider.model_fingerprint,
                scenes=[scene],
                provider_metadata=provider.safe_metadata(),
            )

        serialized = json.dumps(manifest)
        self.assertEqual(manifest["provider_id"], LTX25_SOURCE_ID)
        self.assertEqual(manifest["provider_metadata"]["mode"], "fast")
        self.assertEqual(manifest["provider_metadata"]["output_audio"], "none")
        self.assertNotIn(str(self.repo), serialized)
        self.assertNotIn(str(self.models), serialized)


if __name__ == "__main__":
    unittest.main()
