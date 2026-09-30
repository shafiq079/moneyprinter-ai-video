import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import local_ai
from app.services.local_ai.base import SceneSpec
from app.services.local_ai.ltx25_hf import (
    LTX25_HF_SOURCE_ID,
    LTX25HFConfigurationError,
    LTX25HFProvider,
    LTX25HFSettings,
)
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
            "color=c=black:s=576x1024:r=24:d=2.1",
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
        self.assertEqual(backend.last_inputs["height"], 1024)
        self.assertEqual(backend.last_inputs["width"], 576)
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


if __name__ == "__main__":
    unittest.main()
