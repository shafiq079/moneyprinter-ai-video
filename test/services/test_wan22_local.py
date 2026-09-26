import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import generation_manifest, scene_planner
from app.services.local_ai.base import SceneSpec
from app.services.local_ai.runtime import LocalAIRuntimeManager
from app.services.local_ai.wan22 import (
    WAN22_SOURCE_ID,
    Wan22ConfigurationError,
    Wan22LocalProvider,
    Wan22Settings,
)
from app.utils import utils


class _FakeWorker:
    instances = []

    def __init__(self, settings):
        self.settings = settings
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


class Wan22TestCase(unittest.TestCase):
    def setUp(self):
        Wan22LocalProvider.release_runtime()
        _FakeWorker.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "Wan2.2"
        self.checkpoint = self.root / "Wan2.2-TI2V-5B"
        (self.repo / "wan" / "configs").mkdir(parents=True)
        (self.repo / "wan" / "utils").mkdir(parents=True)
        (self.checkpoint / "google" / "umt5-xxl").mkdir(parents=True)
        for relative in (
            "wan/textimage2video.py",
            "wan/configs/wan_ti2v_5B.py",
            "wan/utils/utils.py",
        ):
            (self.repo / relative).write_text("# test\n", encoding="utf-8")
        for name in (
            "config.json",
            "models_t5_umt5-xxl-enc-bf16.pth",
            "Wan2.2_VAE.pth",
        ):
            (self.checkpoint / name).write_bytes(b"test")
        (self.checkpoint / "model-00001.safetensors").write_bytes(b"weights")
        (self.checkpoint / "diffusion_pytorch_model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"layer": "model-00001.safetensors"}}),
            encoding="utf-8",
        )
        self.settings = Wan22Settings(
            repo_path=self.repo,
            checkpoint_path=self.checkpoint,
            python_executable="python",
            device_id=0,
            base_seed=77,
        )

    def tearDown(self):
        Wan22LocalProvider.release_runtime()
        self.temp.cleanup()

    def provider(self):
        with patch.object(Wan22LocalProvider, "_worker_factory", _FakeWorker):
            return Wan22LocalProvider(settings=self.settings)


class TestWan22Configuration(Wan22TestCase):
    def test_checkpoint_preflight_rejects_missing_or_unsafe_shards(self):
        index = self.checkpoint / "diffusion_pytorch_model.safetensors.index.json"
        index.write_text(
            json.dumps({"weight_map": {"layer": "missing.safetensors"}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Wan22ConfigurationError, "missing model shard"):
            Wan22LocalProvider(settings=self.settings)

        index.write_text(
            json.dumps({"weight_map": {"layer": "../escape.safetensors"}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Wan22ConfigurationError, "unsafe shard"):
            Wan22LocalProvider(settings=self.settings)

    def test_fingerprint_and_metadata_do_not_persist_host_paths(self):
        provider = Wan22LocalProvider(settings=self.settings)
        payload = json.dumps(
            {
                "fingerprint": provider.model_fingerprint,
                "metadata": provider.safe_metadata(),
            }
        )
        self.assertNotIn(str(self.repo), payload)
        self.assertNotIn(str(self.checkpoint), payload)
        self.assertIn("Wan2.2-TI2V-5B", payload)
        self.assertTrue(provider.model_fingerprint.startswith("wan22-ti2v5b:sha256:"))

    def test_preflight_uses_configured_worker_without_importing_gpu_stack_in_app(self):
        provider = Wan22LocalProvider(settings=self.settings)
        response = "MPT_WAN22_JSON:" + json.dumps({"ok": True}) + "\n"
        completed = subprocess.CompletedProcess([], 0, stdout=response)

        with (
            patch("app.services.local_ai.wan22.utils.check_ffmpeg_ready", return_value=True),
            patch("app.services.local_ai.wan22.subprocess.run", return_value=completed) as run,
        ):
            provider.preflight()

        command = run.call_args.args[0]
        self.assertIn("--preflight", command)
        self.assertEqual(command[0], self.settings.python_executable)


class TestWan22Runtime(Wan22TestCase):
    def test_runtime_is_reused_across_provider_instances_and_scenes(self):
        scene_one = SceneSpec(1, "one", "forest", 1.0, "9:16", 77)
        scene_two = SceneSpec(2, "two", "mountain", 1.0, "9:16", 78)
        first_output = self.root / "one.mp4"
        second_output = self.root / "two.mp4"

        with patch.object(Wan22LocalProvider, "_worker_factory", _FakeWorker):
            first = Wan22LocalProvider(settings=self.settings)
            first.load_runtime()
            first.generate(scene_one, first_output)
            second = Wan22LocalProvider(settings=self.settings)
            second.load_runtime()
            second.generate(scene_two, second_output)

        self.assertEqual(len(_FakeWorker.instances), 1)
        worker = _FakeWorker.instances[0]
        self.assertGreaterEqual(worker.load_count, 1)
        self.assertEqual(worker.generate_count, 2)
        self.assertTrue(first_output.is_file())
        self.assertTrue(second_output.is_file())
        first.validate_output(first_output, scene_one)
        second.validate_output(second_output, scene_two)

    def test_provider_caps_scene_duration_at_five_seconds(self):
        provider = Wan22LocalProvider(settings=self.settings)
        scenes = scene_planner.plan_scenes(
            "One long narration segment for a local Wan task.",
            audio_duration=11.0,
            max_scene_duration=min(10.0, provider.max_scene_duration),
            aspect="9:16",
            base_seed=provider.base_seed,
        )
        self.assertEqual(len(scenes), 3)
        self.assertTrue(all(scene.target_duration <= 5.0 for scene in scenes))
        self.assertEqual([scene.seed for scene in scenes], [77, 78, 79])

    def test_runtime_manager_evicts_previous_family_before_switch(self):
        manager = LocalAIRuntimeManager()
        calls = []
        manager.register_family("wan22", lambda: calls.append("release-wan"))
        manager.register_family("ltx25", lambda: calls.append("release-ltx"))

        with manager.generation_slot("wan22"):
            self.assertEqual(manager.active_family, "wan22")
        with manager.generation_slot("ltx25"):
            self.assertEqual(manager.active_family, "ltx25")

        self.assertEqual(calls, ["release-wan"])

    def test_runtime_manager_serializes_same_family_generation(self):
        manager = LocalAIRuntimeManager()
        entered = []
        first_inside = threading.Event()
        release_first = threading.Event()

        def first():
            with manager.generation_slot("wan22"):
                entered.append("first")
                first_inside.set()
                release_first.wait(timeout=2)

        def second():
            first_inside.wait(timeout=2)
            with manager.generation_slot("wan22"):
                entered.append("second")

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        first_inside.wait(timeout=2)
        self.assertEqual(entered, ["first"])
        release_first.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(entered, ["first", "second"])


class TestWan22Manifest(Wan22TestCase):
    def test_manifest_records_safe_wan_provider_metadata(self):
        provider = Wan22LocalProvider(settings=self.settings)
        scene = SceneSpec(1, "one", "forest", 1.0, "9:16", 77)

        with patch.object(utils, "task_dir", return_value=str(self.root / "task")):
            manifest = generation_manifest.prepare_manifest(
                "wan-task",
                provider_id=WAN22_SOURCE_ID,
                model_fingerprint=provider.model_fingerprint,
                scenes=[scene],
                provider_metadata=provider.safe_metadata(),
            )

        serialized = json.dumps(manifest)
        self.assertEqual(manifest["provider_id"], WAN22_SOURCE_ID)
        self.assertEqual(manifest["provider_metadata"]["output_audio"], "none")
        self.assertNotIn(str(self.repo), serialized)
        self.assertNotIn(str(self.checkpoint), serialized)


if __name__ == "__main__":
    unittest.main()
