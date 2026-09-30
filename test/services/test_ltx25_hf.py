import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import config
from app.models.schema import VideoParams
from app.services import generation_manifest, local_ai, scene_planner, task
from app.services.local_ai.base import SceneSpec
from app.services.local_ai.ltx25_hf import (
    LTX25_HF_SOURCE_ID,
    LTX25HFConfigurationError,
    LTX25HFProvider,
    LTX25HFSettings,
)
from app.services.state import MemoryState
from app.utils import utils


class _FakeHFBackend:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.preflight_count = 0
        self.generate_count = 0
        self.last_inputs = None
        type(self).instances.append(self)

    def preflight(self):
        self.preflight_count += 1
        return {
            "backend": "huggingface_zerogpu",
            "api_name": self.kwargs["api_name"],
        }

    def generate(self, inputs, output_path):
        self.generate_count += 1
        self.last_inputs = dict(inputs)
        output = Path(output_path)
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=832x1472:r=24:d=2.1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
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
        return {"backend": "huggingface_zerogpu", "output_bytes": output.stat().st_size}


class LTX25HFTestCase(unittest.TestCase):
    def setUp(self):
        _FakeHFBackend.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = LTX25HFSettings(
            space_url="https://owner-space.hf.space",
            api_name="generate_scene",
            token_env="TEST_HF_TOKEN",
            deployment_revision="space-rev-123",
            base_seed=77,
            max_scene_duration=5.0,
            decoder="conv",
            job_timeout_seconds=300,
        )

    def tearDown(self):
        self.temp.cleanup()


class TestLTX25HFProvider(LTX25HFTestCase):
    def test_space_settings_load_from_config_without_storing_token(self):
        with (
            patch.dict(
                config.ltx25_hf,
                {
                    "space_url": self.settings.space_url,
                    "api_name": self.settings.api_name,
                    "token_env": "TEST_HF_TOKEN",
                    "deployment_revision": self.settings.deployment_revision,
                },
                clear=True,
            ),
            patch.dict(os.environ, {"TEST_HF_TOKEN": "hf_test"}, clear=True),
            patch.object(LTX25HFProvider, "_backend_factory", _FakeHFBackend),
        ):
            settings = LTX25HFSettings.from_config()
            provider = LTX25HFProvider(settings=settings)
            provider.preflight()

        self.assertEqual(settings.space_url, self.settings.space_url)
        self.assertEqual(settings.deployment_revision, self.settings.deployment_revision)
        self.assertEqual(_FakeHFBackend.instances[-1].kwargs["token"], "hf_test")
        self.assertNotIn("hf_test", repr(settings) + json.dumps(provider.safe_metadata()))

    def test_metadata_and_fingerprint_never_persist_token(self):
        with patch.dict(os.environ, {"TEST_HF_TOKEN": "hf_super_secret"}):
            provider = LTX25HFProvider(settings=self.settings)
            payload = json.dumps(
                {
                    "fingerprint": provider.model_fingerprint,
                    "metadata": provider.safe_metadata(),
                }
            )

        self.assertTrue(provider.model_fingerprint.startswith("ltx25-hf:sha256:"))
        self.assertEqual(provider.safe_metadata()["backend"], "huggingface_zerogpu")
        self.assertEqual(provider.safe_metadata()["space_host"], "owner-space.hf.space")
        self.assertNotIn("hf_super_secret", payload)
        self.assertNotIn("TEST_HF_TOKEN", payload)

    def test_missing_token_fails_before_remote_request(self):
        provider = LTX25HFProvider(settings=self.settings)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                LTX25HFConfigurationError,
                "TEST_HF_TOKEN",
            ):
                provider.preflight()

    def test_preflight_and_generation_use_remote_backend_then_strip_audio(self):
        scene = SceneSpec(
            scene_id=1,
            narration_segment="one",
            prompt="a calm city street",
            target_duration=1.0,
            aspect="9:16",
            seed=99,
        )
        output = self.root / "scene.mp4"

        with (
            patch.dict(os.environ, {"TEST_HF_TOKEN": "hf_test"}),
            patch.object(LTX25HFProvider, "_backend_factory", _FakeHFBackend),
        ):
            provider = LTX25HFProvider(settings=self.settings)
            provider.preflight()
            provider.generate(scene, output)
            result = provider.validate_output(output, scene)

        backend = _FakeHFBackend.instances[0]
        self.assertEqual(backend.preflight_count, 1)
        self.assertEqual(backend.generate_count, 1)
        self.assertEqual(backend.last_inputs["prompt"], scene.prompt)
        self.assertEqual(backend.last_inputs["height"], 1472)
        self.assertEqual(backend.last_inputs["width"], 832)
        self.assertEqual(backend.last_inputs["duration_s"], 2.0)
        self.assertEqual(backend.last_inputs["seed"], 99)
        self.assertEqual(result.provider_id, LTX25_HF_SOURCE_ID)
        self.assertTrue(output.is_file())

        from app.services import video

        clip = video._open_video_clip_quietly(str(output), audio=True)
        try:
            self.assertIsNone(clip.audio)
        finally:
            video.close_clip(clip)

    def test_public_registry_creates_fast_hf_provider_only(self):
        with patch(
            "app.services.local_ai.ltx25_hf.LTX25HFSettings.from_config",
            return_value=self.settings,
        ):
            provider = local_ai.create_provider(
                LTX25_HF_SOURCE_ID,
                generation_mode="fast",
            )

        self.assertIsInstance(provider, LTX25HFProvider)
        self.assertTrue(local_ai.is_local_ai_source(LTX25_HF_SOURCE_ID))
        self.assertTrue(local_ai.is_public_source(LTX25_HF_SOURCE_ID))
        with self.assertRaisesRegex(ValueError, "fast mode only"):
            local_ai.create_provider(
                LTX25_HF_SOURCE_ID,
                generation_mode="quality",
            )


class TestLTX25HFFullPipeline(LTX25HFTestCase):
    def test_twenty_second_multiscene_task_composes_without_real_gpu(self):
        class OfflineSpace(_FakeHFBackend):
            def generate(self, inputs, output_path):
                self.generate_count += 1
                self.last_inputs = dict(inputs)
                duration = float(inputs["duration_s"]) + 0.25
                command = [
                    utils.get_ffmpeg_binary(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=blue:s={inputs['width']}x{inputs['height']}:r=2:d={duration}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(output_path),
                ]
                subprocess.run(command, capture_output=True, check=True)

        def task_dir(sub_dir=""):
            destination = self.root / sub_dir if sub_dir else self.root
            destination.mkdir(parents=True, exist_ok=True)
            return str(destination)

        def offline_tts(*, voice_file, **_kwargs):
            subprocess.run(
                [
                    utils.get_ffmpeg_binary(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t",
                    "20",
                    "-c:a",
                    "libmp3lame",
                    voice_file,
                ],
                capture_output=True,
                check=True,
            )
            return object()

        def offline_subtitles(*, subtitle_file, **_kwargs):
            Path(subtitle_file).write_text(
                "1\n00:00:00,100 --> 00:00:19,500\nA quiet garden grows.\n\n",
                encoding="utf-8",
            )

        params = VideoParams(
            video_subject="A garden through a day",
            video_script=(
                "Sunlight reaches the garden. Leaves move in the breeze. "
                "A flower opens. The garden rests at dusk."
            ),
            video_source=LTX25_HF_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=5,
            local_ai_generation_mode="fast",
            local_ai_seed=77,
            subtitle_enabled=True,
            bgm_type="random",
            bgm_volume=0.1,
            n_threads=1,
        )
        state = MemoryState()
        with (
            patch.object(utils, "task_dir", side_effect=task_dir),
            patch.object(task.sm, "state", state),
            patch.object(LTX25HFSettings, "from_config", return_value=self.settings),
            patch.object(LTX25HFProvider, "_backend_factory", OfflineSpace),
            patch.dict(os.environ, {"TEST_HF_TOKEN": "hf_offline_test_only"}),
            patch.object(task.voice, "tts", side_effect=offline_tts),
            patch.object(task.voice, "create_subtitle", side_effect=offline_subtitles),
            patch.object(
                scene_planner.llm,
                "generate_json_response",
                side_effect=RuntimeError("offline"),
            ),
            patch.object(
                task.material,
                "download_videos",
                side_effect=AssertionError("stock downloader called"),
            ),
        ):
            result = task.start("hf-full-cpu", params)
            plan = scene_planner.load_scene_plan("hf-full-cpu")
            manifest = generation_manifest.load_manifest("hf-full-cpu")

        self.assertEqual(
            state.get_task("hf-full-cpu")["state"], task.const.TASK_STATE_COMPLETE
        )
        # MP3 encoder padding makes the measured narration slightly longer
        # than 20 seconds, so the planner correctly requests one more scene.
        self.assertEqual(len(plan.scenes), 5)
        self.assertEqual(len(manifest["scenes"]), len(plan.scenes))
        self.assertEqual(manifest["provider_id"], LTX25_HF_SOURCE_ID)
        self.assertEqual(len(result["materials"]), len(plan.scenes))
        self.assertEqual(
            sum(backend.generate_count for backend in OfflineSpace.instances),
            len(plan.scenes),
        )
        self.assertEqual(OfflineSpace.instances[0].last_inputs["width"], 832)
        self.assertEqual(OfflineSpace.instances[0].last_inputs["height"], 1472)
        self.assertTrue(Path(result["subtitle_path"]).is_file())
        self.assertTrue(Path(result["videos"][0]).is_file())


if __name__ == "__main__":
    unittest.main()
