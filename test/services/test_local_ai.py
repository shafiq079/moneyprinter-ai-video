import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoConcatMode, VideoParams
from app.services import generation_manifest, scene_planner, task, video
from app.services.local_ai import FAKE_SOURCE_ID
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.utils import utils


class LocalAITestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_root = Path(self.temp_dir.name)

        def fake_task_dir(sub_dir: str = "") -> str:
            target = self.task_root / sub_dir if sub_dir else self.task_root
            target.mkdir(parents=True, exist_ok=True)
            return str(target)

        self.task_dir_patch = patch.object(utils, "task_dir", side_effect=fake_task_dir)
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def make_scenes(self, duration: float = 2.0):
        return scene_planner.plan_scenes(
            "A first idea. A second idea.",
            audio_duration=duration,
            max_scene_duration=1.0,
            aspect="9:16",
        )


class TestScenePlan(LocalAITestCase):
    def test_scene_plan_is_ordered_and_covers_audio_duration(self):
        scenes = scene_planner.plan_scenes(
            "Hook. Build the idea. Close clearly.",
            audio_duration=5.5,
            max_scene_duration=2.0,
            aspect="9:16",
            base_seed=100,
        )

        self.assertEqual([scene.scene_id for scene in scenes], [1, 2, 3])
        self.assertEqual([scene.seed for scene in scenes], [100, 101, 102])
        self.assertAlmostEqual(
            sum(scene.target_duration for scene in scenes), 5.5, places=3
        )
        self.assertTrue(all(scene.target_duration <= 2.0 for scene in scenes))
        self.assertTrue(all(scene.prompt for scene in scenes))

    def test_scene_plan_does_not_repeat_full_script_when_scenes_outnumber_sentences(self):
        script = "First point. Second point."
        scenes = scene_planner.plan_scenes(
            script,
            audio_duration=4.0,
            max_scene_duration=1.0,
            aspect="9:16",
        )

        self.assertEqual(len(scenes), 4)
        self.assertTrue(all(scene.narration_segment != script for scene in scenes))
        self.assertEqual(
            " ".join(scene.narration_segment for scene in scenes),
            "First point. Second point.",
        )


class TestLocalAIGenerationManifest(LocalAITestCase):
    def test_multiple_scenes_share_one_runtime_load_and_cached_run_skips_runtime(self):
        scenes = self.make_scenes()
        provider = FakeLocalVideoProvider()

        first_paths = generate_scene_materials(
            "runtime-reuse",
            provider=provider,
            scenes=scenes,
        )

        self.assertEqual(provider.runtime_load_count, 1)
        self.assertEqual(provider.generated_scene_ids, [1, 2])
        self.assertTrue(all(Path(path).is_file() for path in first_paths))

        cached_provider = FakeLocalVideoProvider()
        second_paths = generate_scene_materials(
            "runtime-reuse",
            provider=cached_provider,
            scenes=scenes,
        )

        self.assertEqual(second_paths, first_paths)
        self.assertEqual(cached_provider.runtime_load_count, 0)
        self.assertEqual(cached_provider.generated_scene_ids, [])

    def test_failure_preserves_ready_scene_and_retry_only_generates_missing_scene(self):
        scenes = self.make_scenes()
        failing = FakeLocalVideoProvider(fail_scene_ids={2})

        with self.assertRaisesRegex(RuntimeError, "intentional fake failure"):
            generate_scene_materials(
                "retry-scenes",
                provider=failing,
                scenes=scenes,
            )

        failed_manifest = generation_manifest.load_manifest("retry-scenes")
        self.assertEqual(failed_manifest["scenes"][0]["status"], "ready")
        self.assertEqual(failed_manifest["scenes"][1]["status"], "failed")
        first_scene_asset = failed_manifest["scenes"][0]["active_asset"]
        first_scene_path = generation_manifest.resolve_asset(
            "retry-scenes", first_scene_asset
        )
        first_scene_bytes = first_scene_path.read_bytes()

        retry = FakeLocalVideoProvider()
        output_paths = generate_scene_materials(
            "retry-scenes",
            provider=retry,
            scenes=scenes,
        )

        self.assertEqual(retry.runtime_load_count, 1)
        self.assertEqual(retry.generated_scene_ids, [2])
        self.assertEqual(Path(output_paths[0]), first_scene_path)
        self.assertEqual(first_scene_path.read_bytes(), first_scene_bytes)
        recovered = generation_manifest.load_manifest("retry-scenes")
        self.assertEqual(
            [item["status"] for item in recovered["scenes"]],
            ["ready", "ready"],
        )

    def test_corrupt_cached_clip_is_invalidated_and_versioned_replacement_is_generated(self):
        scenes = self.make_scenes()
        provider = FakeLocalVideoProvider()
        generate_scene_materials("corrupt-scene", provider=provider, scenes=scenes)

        before = generation_manifest.load_manifest("corrupt-scene")
        corrupt_relative = before["scenes"][0]["active_asset"]
        corrupt_path = generation_manifest.resolve_asset(
            "corrupt-scene", corrupt_relative
        )
        corrupt_path.write_bytes(b"not-a-video")

        replacement = FakeLocalVideoProvider()
        output_paths = generate_scene_materials(
            "corrupt-scene",
            provider=replacement,
            scenes=scenes,
        )

        self.assertEqual(replacement.generated_scene_ids, [1])
        after = generation_manifest.load_manifest("corrupt-scene")
        scene_one = after["scenes"][0]
        self.assertEqual(scene_one["status"], "ready")
        self.assertEqual(
            scene_one["versions"],
            [
                "generated_ai/scene-001/v001.mp4",
                "generated_ai/scene-001/v002.mp4",
            ],
        )
        self.assertEqual(
            scene_one["active_asset"],
            "generated_ai/scene-001/v002.mp4",
        )
        self.assertEqual(Path(output_paths[1]).name, "v001.mp4")

    def test_manifest_contains_only_task_relative_asset_paths(self):
        scenes = self.make_scenes(duration=1.0)
        provider = FakeLocalVideoProvider()
        generate_scene_materials(
            "relative-manifest",
            provider=provider,
            scenes=scenes,
        )

        manifest_file = generation_manifest.manifest_path("relative-manifest")
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        active = payload["scenes"][0]["active_asset"]

        self.assertFalse(Path(active).is_absolute())
        self.assertNotIn(
            str(self.task_root),
            manifest_file.read_text(encoding="utf-8"),
        )


class TestLocalAITaskIntegration(LocalAITestCase):
    def test_fake_source_is_disabled_outside_explicit_test_mode(self):
        from app.services import local_ai

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "test-only"):
                local_ai.create_provider(FAKE_SOURCE_ID)

    def test_local_ai_material_path_does_not_call_remote_material_download(self):
        params = VideoParams(
            video_subject="test",
            video_script="A first idea. A second idea.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=1,
            subtitle_enabled=False,
            bgm_type="",
        )

        with (
            patch.dict(
                "os.environ",
                {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"},
            ),
            patch.object(task.material, "download_videos") as remote_download,
        ):
            materials = task.get_video_materials(
                "task-materials",
                params,
                [],
                2.0,
                video_script=params.video_script,
            )

        remote_download.assert_not_called()
        self.assertEqual(len(materials), 2)
        self.assertTrue(all(Path(item).is_file() for item in materials))

    def test_fake_scene_clips_reach_existing_final_composer(self):
        scenes = self.make_scenes()
        provider = FakeLocalVideoProvider()
        materials = generate_scene_materials(
            "composer-e2e",
            provider=provider,
            scenes=scenes,
        )
        audio_path = self.task_root / "audio.m4a"
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "1.8",
            "-c:a",
            "aac",
            str(audio_path),
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        params = VideoParams(
            video_subject="test",
            video_script="A first idea. A second idea.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_concat_mode=VideoConcatMode.sequential,
            video_clip_duration=1,
            subtitle_enabled=False,
            bgm_type="",
            bgm_volume=0,
            n_threads=1,
        )
        final_paths, combined_paths, warnings = task.generate_final_videos(
            "composer-e2e",
            params,
            materials,
            str(audio_path),
            "",
            2.0,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(final_paths), 1)
        self.assertEqual(len(combined_paths), 1)
        self.assertTrue(Path(final_paths[0]).is_file())
        clip = video._open_video_clip_quietly(final_paths[0], audio=True)
        try:
            self.assertGreater(clip.duration, 1.5)
            self.assertIsNotNone(clip.audio)
        finally:
            video.close_clip(clip)
