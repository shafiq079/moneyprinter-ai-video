import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoConcatMode, VideoParams
from app.services import generation_manifest, scene_planner, task, video
from app.services.local_ai import (
    FAKE_SOURCE_ID,
    LocalAICancellationRequested,
    LocalAISceneGenerationError,
    SceneSpec,
)
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
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


    def make_audio(self, task_id: str, duration: float = 2.0) -> Path:
        audio_path = self.task_root / task_id / "audio.mp3"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration),
            "-c:a",
            "libmp3lame",
            str(audio_path),
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return audio_path


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

    def test_scene_plan_assigns_director_metadata(self):
        scenes = scene_planner.plan_scenes(
            "Open strongly. Explain the idea. Reveal the point. Close.",
            audio_duration=8.0,
            max_scene_duration=2.0,
            aspect="9:16",
            base_seed=200,
        )

        self.assertEqual(scenes[0].beat, "hook")
        self.assertEqual(scenes[-1].beat, "ending")
        self.assertTrue(all(scene.camera for scene in scenes))
        self.assertTrue(all(scene.continuity for scene in scenes))
        self.assertTrue(all("No titles" in scene.prompt for scene in scenes))

    def test_visual_style_is_visible_and_changes_plan_fingerprint(self):
        first = scene_planner.get_or_create_scene_plan(
            "visual-style-plan",
            "A person crosses a quiet street.",
            video_subject="Night walk",
            audio_duration=2.0,
            max_scene_duration=2.0,
            aspect="9:16",
            base_seed=42,
            visual_style="warm 35mm documentary with soft film grain",
            use_llm=False,
        )

        self.assertIn(
            "warm 35mm documentary with soft film grain",
            first.visual_bible,
        )
        self.assertIn(
            "warm 35mm documentary with soft film grain",
            first.scenes[0].prompt,
        )
        first_fingerprint = first.input_fingerprint

        second = scene_planner.get_or_create_scene_plan(
            "visual-style-plan",
            "A person crosses a quiet street.",
            video_subject="Night walk",
            audio_duration=2.0,
            max_scene_duration=2.0,
            aspect="9:16",
            base_seed=42,
            visual_style="minimal monochrome architectural photography",
            use_llm=False,
        )

        self.assertNotEqual(
            second.input_fingerprint,
            first_fingerprint,
        )
        self.assertIn(
            "minimal monochrome architectural photography",
            second.scenes[0].prompt,
        )

    def test_director_prompt_receives_user_visual_direction(self):
        fallback = scene_planner.get_or_create_scene_plan(
            "director-style-prompt",
            "A ceramic cup sits on a table.",
            video_subject="Ceramic cup",
            audio_duration=2.0,
            max_scene_duration=2.0,
            aspect="16:9",
            visual_style="handmade clay stop-motion",
            use_llm=False,
        )
        prompt = scene_planner.build_director_prompt(
            video_subject="Ceramic cup",
            fallback_plan=fallback,
            visual_style="handmade clay stop-motion",
        )

        self.assertIn(
            "User visual direction: handmade clay stop-motion",
            prompt,
        )
        self.assertIn(
            "must not override fixed",
            prompt.lower(),
        )

    def test_persisted_director_plan_is_reused_without_second_llm_call(self):
        director_payload = {
            "idea": "A focused coffee story",
            "story_arc": "Hook, explain, then close.",
            "visual_bible": "Warm natural light, consistent barista and cafe.",
            "scenes": [
                {
                    "scene_id": 1,
                    "beat": "hook",
                    "prompt": "Macro shot of coffee beans falling into a grinder.",
                    "camera": "macro push-in",
                    "continuity": "Establish the same warm cafe.",
                    "negative_prompt": "text, logos",
                    "narration": "THIS MUST BE IGNORED",
                },
                {
                    "scene_id": 2,
                    "beat": "ending",
                    "prompt": "Wide shot of the finished coffee on the same counter.",
                    "camera": "slow pull-back",
                    "continuity": "Keep the same cafe, cup, palette, and lighting.",
                    "negative_prompt": "text, logos",
                    "narration": "THIS MUST ALSO BE IGNORED",
                },
            ],
        }
        with patch.object(
            scene_planner.llm,
            "generate_json_response",
            return_value=director_payload,
        ) as generate:
            first = scene_planner.get_or_create_scene_plan(
                "director-cache",
                "Coffee begins with the beans. The cup completes the ritual.",
                video_subject="Coffee ritual",
                audio_duration=4.0,
                max_scene_duration=2.0,
                aspect="9:16",
                base_seed=50,
            )
            second = scene_planner.get_or_create_scene_plan(
                "director-cache",
                "Coffee begins with the beans. The cup completes the ritual.",
                video_subject="Coffee ritual",
                audio_duration=4.0,
                max_scene_duration=2.0,
                aspect="9:16",
                base_seed=50,
            )

        generate.assert_called_once()
        self.assertEqual(first.source, "configured_llm")
        self.assertEqual(second, first)
        self.assertTrue(scene_planner.scene_plan_path("director-cache").is_file())
        self.assertEqual(
            [scene.narration_segment for scene in first.scenes],
            [
                "Coffee begins with the beans.",
                "The cup completes the ritual.",
            ],
        )
        self.assertNotIn(
            "THIS MUST BE IGNORED",
            first.scenes[0].narration_segment,
        )

    def test_director_failure_uses_deterministic_persisted_fallback(self):
        with patch.object(
            scene_planner.llm,
            "generate_json_response",
            side_effect=ValueError("invalid director response"),
        ):
            plan = scene_planner.get_or_create_scene_plan(
                "director-fallback",
                "First point. Second point.",
                video_subject="Test subject",
                audio_duration=4.0,
                max_scene_duration=2.0,
                aspect="9:16",
            )

        self.assertEqual(plan.source, "deterministic_fallback")
        self.assertTrue(all(scene.prompt for scene in plan.scenes))
        persisted = scene_planner.load_scene_plan("director-fallback")
        self.assertEqual(persisted, plan)

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

    def test_progress_callback_reports_scene_before_and_after_generation(self):
        scenes = self.make_scenes(duration=1.0)
        provider = FakeLocalVideoProvider()
        events = []

        generate_scene_materials(
            "scene-progress",
            provider=provider,
            scenes=scenes,
            progress_callback=lambda current, total, scene, status, reused: events.append(
                (current, total, scene.scene_id, status, reused)
            ),
        )

        self.assertEqual(
            events,
            [
                (1, 1, 1, "checking", False),
                (1, 1, 1, "generating", False),
                (1, 1, 1, "ready", False),
            ],
        )

    def test_cancellation_boundary_stops_before_next_scene(self):
        scenes = self.make_scenes()
        provider = FakeLocalVideoProvider()
        checks = 0

        def cancel_check():
            nonlocal checks
            checks += 1
            # Scene 1 is allowed to start. The boundary before Scene 2 cancels.
            return checks >= 2

        with self.assertRaises(LocalAICancellationRequested):
            generate_scene_materials(
                "cancel-between-scenes",
                provider=provider,
                scenes=scenes,
                cancel_check=cancel_check,
            )

        self.assertEqual(provider.generated_scene_ids, [1])
        manifest = generation_manifest.load_manifest("cancel-between-scenes")
        self.assertEqual(manifest["scenes"][0]["status"], "ready")
        self.assertEqual(manifest["scenes"][1]["status"], "pending")
        self.assertTrue(
            generation_manifest.resolve_asset(
                "cancel-between-scenes",
                manifest["scenes"][0]["active_asset"],
            ).is_file()
        )

    def test_fully_cached_retry_does_not_enter_provider_generation_session(self):
        class SessionFakeProvider(FakeLocalVideoProvider):
            def __init__(self):
                super().__init__()
                self.session_entries = 0

            @contextmanager
            def generation_session(self):
                self.session_entries += 1
                yield

        scenes = self.make_scenes()
        first = SessionFakeProvider()
        generate_scene_materials(
            "cached-session",
            provider=first,
            scenes=scenes,
        )
        self.assertEqual(first.session_entries, 1)

        cached = SessionFakeProvider()
        generate_scene_materials(
            "cached-session",
            provider=cached,
            scenes=scenes,
        )
        self.assertEqual(cached.session_entries, 0)
        self.assertEqual(cached.runtime_load_count, 0)
        self.assertEqual(cached.generated_scene_ids, [])

    def test_failure_preserves_ready_scene_and_retry_only_generates_missing_scene(self):
        scenes = self.make_scenes()
        failing = FakeLocalVideoProvider(fail_scene_ids={2})

        with self.assertRaises(LocalAISceneGenerationError) as failure:
            generate_scene_materials(
                "retry-scenes",
                provider=failing,
                scenes=scenes,
            )

        self.assertEqual(failure.exception.provider_id, FAKE_SOURCE_ID)
        self.assertEqual(failure.exception.scene_id, 2)
        self.assertEqual(failure.exception.cause_type, "RuntimeError")

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

    def test_manifest_redacts_secrets_and_host_paths_from_metadata(self):
        scene = SceneSpec(
            scene_id=1,
            narration_segment="test",
            prompt="test",
            target_duration=1.0,
            aspect="9:16",
            seed=42,
            provider_settings={
                "mode": "quality",
                "api_key": "SCENE-SECRET-123",
                "nested": {
                    "access_token": "NESTED-TOKEN-456",
                    "strength": 1.0,
                },
            },
        )
        manifest = generation_manifest.prepare_manifest(
            "secret-redaction",
            provider_id="ltx25_local",
            model_fingerprint="ltx25-quality:sha256:test",
            scenes=[scene],
            provider_metadata={
                "model": "LTX-2.5",
                "mode": "quality",
                "api_key": "PROVIDER-SECRET-789",
                "checkpoint_path": "/private/models/model.safetensors",
                "nested": {
                    "password": "PASSWORD-SECRET",
                    "device_index": 0,
                },
            },
        )

        serialized = json.dumps(manifest)
        for forbidden in (
            "SCENE-SECRET-123",
            "NESTED-TOKEN-456",
            "PROVIDER-SECRET-789",
            "PASSWORD-SECRET",
            "/private/models/model.safetensors",
            "api_key",
            "access_token",
            "checkpoint_path",
            "password",
        ):
            self.assertNotIn(forbidden, serialized)

        record = generation_manifest.scene_record(manifest, 1)
        self.assertEqual(record["provider_settings"]["mode"], "quality")
        self.assertEqual(
            record["provider_settings"]["nested"]["strength"],
            1.0,
        )
        self.assertEqual(record["provider_metadata"]["model"], "LTX-2.5")
        self.assertEqual(
            record["provider_metadata"]["nested"]["device_index"],
            0,
        )


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


class TestLocalAIRenderOnlyRerender(LocalAITestCase):
    def _prepare_render_task(self, task_id: str):
        params = VideoParams(
            video_subject="render-only",
            video_script="First scene. Second scene.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_fit_mode="cover",
            video_concat_mode=VideoConcatMode.sequential,
            video_clip_duration=1,
            video_count=1,
            subtitle_enabled=False,
            bgm_type="",
            bgm_volume=0,
            n_threads=1,
        )
        plan = scene_planner.get_or_create_scene_plan(
            task_id,
            params.video_script,
            video_subject=params.video_subject,
            audio_duration=2.0,
            max_scene_duration=1.0,
            aspect="9:16",
            base_seed=42,
            use_llm=False,
        )
        provider = FakeLocalVideoProvider()
        generate_scene_materials(
            task_id,
            provider=provider,
            scenes=list(plan.scenes),
        )
        task.save_script_data(task_id, params.video_script, [], params)
        self.make_audio(task_id, 2.0)
        return params, provider

    def test_render_only_rerender_never_calls_local_video_provider(self):
        task_id = "render-only-success"
        params, provider = self._prepare_render_task(task_id)
        proposed = VideoParams.model_validate(
            {
                **params.model_dump(mode="json"),
                "video_fit_mode": "contain",
                "video_count": 2,
            }
        )

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                side_effect=AssertionError(
                    "render-only rerender must not prepare a provider"
                ),
            ),
            patch.object(
                task.local_ai,
                "create_provider",
                side_effect=AssertionError(
                    "render-only rerender must not create a provider"
                ),
            ),
        ):
            result = task.rerender_local_ai_task(
                task_id,
                proposed,
            )

        self.assertTrue(result["render_only"])
        self.assertEqual(provider.generated_scene_ids, [1, 2])
        self.assertEqual(len(result["videos"]), 2)
        self.assertTrue(all(Path(item).is_file() for item in result["videos"]))
        manifest = generation_manifest.load_manifest(task_id)
        self.assertEqual(
            [
                generation_manifest.scene_record(manifest, scene_id)["active_asset"]
                for scene_id in (1, 2)
            ],
            [
                "generated_ai/scene-001/v001.mp4",
                "generated_ai/scene-002/v001.mp4",
            ],
        )

    def test_render_only_rerender_rejects_generation_input_change(self):
        task_id = "render-only-reject"
        params, _ = self._prepare_render_task(task_id)
        proposed = VideoParams.model_validate(
            {
                **params.model_dump(mode="json"),
                "local_ai_seed": 999,
            }
        )

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            self.assertRaisesRegex(
                ValueError,
                "local_ai_seed",
            ),
        ):
            task.validate_local_ai_rerender(
                task_id,
                proposed,
            )

    def test_render_only_rerender_rejects_enabling_missing_subtitles(self):
        task_id = "render-only-no-subtitles"
        params, _ = self._prepare_render_task(task_id)
        proposed = VideoParams.model_validate(
            {
                **params.model_dump(mode="json"),
                "subtitle_enabled": True,
            }
        )

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            self.assertRaisesRegex(
                ValueError,
                "no subtitle artifact",
            ),
        ):
            task.validate_local_ai_rerender(
                task_id,
                proposed,
            )

    def test_render_only_rerender_reuses_generated_bgm_without_new_audio_or_ai(self):
        task_id = "render-only-bgm-reuse"
        params, _ = self._prepare_render_task(task_id)
        params.bgm_type = "sonilo"
        params.bgm_volume = 0.1
        params.video_music_prompt = "quiet instrumental"
        task.save_script_data(task_id, params.video_script, [], params)
        bgm_file = self.task_root / task_id / "sonilo-bgm-1.m4a"
        subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-y",
                "-i",
                str(self.task_root / task_id / "audio.mp3"),
                "-c:a",
                "aac",
                str(bgm_file),
            ],
            capture_output=True,
            check=True,
        )

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                side_effect=AssertionError("AI provider started"),
            ),
            patch.object(
                task.voice, "tts", side_effect=AssertionError("narration regenerated")
            ),
            patch.object(
                task.sonilo,
                "generate_bgm",
                side_effect=AssertionError("paid BGM requested"),
            ),
        ):
            result = task.rerender_local_ai_task(task_id)

        self.assertTrue(result["render_only"])
        self.assertTrue(Path(result["videos"][0]).is_file())
        self.assertTrue(bgm_file.is_file())
        self.assertEqual(result["warnings"], [])

    def test_failed_render_only_rerender_restores_previous_final_video(self):
        task_id = "render-only-rollback"
        self._prepare_render_task(task_id)
        final = self.task_root / task_id / "final-1.mp4"
        combined = self.task_root / task_id / "combined-1.mp4"
        final.write_bytes(b"previous final")
        combined.write_bytes(b"previous combined")
        state = MemoryState()
        state.update_task(
            task_id,
            state=task.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[str(final)],
            combined_videos=[str(combined)],
        )

        def broken_render(*_args, **_kwargs):
            final.write_bytes(b"incomplete replacement")
            raise RuntimeError("render failed")

        with (
            patch.object(task.sm, "state", state),
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                side_effect=AssertionError("AI provider started"),
            ),
            patch.object(task, "generate_final_videos", side_effect=broken_render),
            self.assertRaisesRegex(RuntimeError, "render failed"),
        ):
            task.rerender_local_ai_task(task_id)

        self.assertEqual(final.read_bytes(), b"previous final")
        self.assertEqual(combined.read_bytes(), b"previous combined")
        self.assertEqual(state.get_task(task_id)["state"], task.const.TASK_STATE_COMPLETE)
        self.assertFalse(list((self.task_root / task_id).glob("*rerender-backup")))


class TestLocalAISceneRegeneration(LocalAITestCase):
    def _prepare_task(self, task_id: str):
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
        plan = scene_planner.get_or_create_scene_plan(
            task_id,
            params.video_script,
            video_subject=params.video_subject,
            audio_duration=2.0,
            max_scene_duration=1.0,
            aspect="9:16",
            base_seed=42,
            use_llm=False,
        )
        provider = FakeLocalVideoProvider()
        generate_scene_materials(
            task_id,
            provider=provider,
            scenes=list(plan.scenes),
        )
        task.save_script_data(task_id, params.video_script, [], params)
        self.make_audio(task_id, 2.0)
        return params, plan

    def test_single_scene_edit_creates_only_one_new_version_and_rerenders(self):
        task_id = "scene-edit-success"
        _, original_plan = self._prepare_task(task_id)
        replacement = FakeLocalVideoProvider()

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                return_value=replacement,
            ),
        ):
            result = task.regenerate_local_ai_scene(
                task_id,
                1,
                prompt="A new close-up visual for only the first scene.",
                seed=99,
            )

        self.assertEqual(replacement.generated_scene_ids, [1])
        self.assertTrue(Path(result["videos"][0]).is_file())
        manifest = generation_manifest.load_manifest(task_id)
        first = generation_manifest.scene_record(manifest, 1)
        second = generation_manifest.scene_record(manifest, 2)
        self.assertEqual(
            first["versions"],
            [
                "generated_ai/scene-001/v001.mp4",
                "generated_ai/scene-001/v002.mp4",
            ],
        )
        self.assertEqual(first["active_asset"], "generated_ai/scene-001/v002.mp4")
        first_v1 = generation_manifest.scene_version_metadata(
            first,
            "generated_ai/scene-001/v001.mp4",
        )
        first_v2 = generation_manifest.scene_version_metadata(
            first,
            "generated_ai/scene-001/v002.mp4",
        )
        self.assertIsNotNone(first_v1)
        self.assertIsNotNone(first_v2)
        self.assertEqual(first_v1["seed"], original_plan.scenes[0].seed)
        self.assertEqual(first_v2["seed"], 99)
        self.assertEqual(
            first_v1["prompt"],
            original_plan.scenes[0].prompt,
        )
        self.assertEqual(second["versions"], ["generated_ai/scene-002/v001.mp4"])
        self.assertEqual(second["active_asset"], "generated_ai/scene-002/v001.mp4")

        revised = scene_planner.load_scene_plan(task_id)
        self.assertEqual(revised.source, "manual_edit")
        self.assertEqual(revised.scenes[0].seed, 99)
        self.assertNotEqual(
            revised.scenes[0].prompt,
            original_plan.scenes[0].prompt,
        )
        self.assertEqual(
            revised.scenes[1].prompt,
            original_plan.scenes[1].prompt,
        )

    def test_failed_scene_edit_preserves_previous_active_asset_and_plan(self):
        task_id = "scene-edit-failure"
        _, original_plan = self._prepare_task(task_id)
        before = generation_manifest.load_manifest(task_id)
        before_active = generation_manifest.scene_record(before, 1)["active_asset"]
        replacement = FakeLocalVideoProvider(fail_scene_ids={1})

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                return_value=replacement,
            ),
            self.assertRaises(LocalAISceneGenerationError),
        ):
            task.regenerate_local_ai_scene(
                task_id,
                1,
                prompt="This variation intentionally fails.",
                seed=100,
            )

        after = generation_manifest.load_manifest(task_id)
        first = generation_manifest.scene_record(after, 1)
        self.assertEqual(first["active_asset"], before_active)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["regeneration_status"], "failed")
        self.assertEqual(
            first["versions"],
            ["generated_ai/scene-001/v001.mp4"],
        )
        persisted = scene_planner.load_scene_plan(task_id)
        self.assertEqual(persisted.scenes[0], original_plan.scenes[0])


    def test_previous_scene_version_can_be_restored_without_new_inference(self):
        task_id = "scene-version-restore"
        _, original_plan = self._prepare_task(task_id)
        replacement = FakeLocalVideoProvider()

        with (
            patch.object(task.local_ai, "is_public_source", return_value=True),
            patch.object(
                task.local_ai,
                "prepare_provider",
                return_value=replacement,
            ),
        ):
            task.regenerate_local_ai_scene(
                task_id,
                1,
                prompt="A newer first-scene prompt.",
                seed=99,
            )

        replacement.generated_scene_ids.clear()
        with patch.object(
            task.local_ai,
            "is_public_source",
            return_value=True,
        ):
            result = task.restore_local_ai_scene_version(
                task_id,
                1,
                "generated_ai/scene-001/v001.mp4",
            )

        self.assertTrue(result["restored"])
        self.assertEqual(replacement.generated_scene_ids, [])
        self.assertTrue(Path(result["videos"][0]).is_file())

        manifest = generation_manifest.load_manifest(task_id)
        first = generation_manifest.scene_record(manifest, 1)
        self.assertEqual(
            first["active_asset"],
            "generated_ai/scene-001/v001.mp4",
        )
        restored_plan = scene_planner.load_scene_plan(task_id)
        self.assertEqual(restored_plan.source, "version_restore")
        self.assertEqual(
            restored_plan.scenes[0].prompt,
            original_plan.scenes[0].prompt,
        )
        self.assertEqual(
            restored_plan.scenes[0].seed,
            original_plan.scenes[0].seed,
        )

    def test_legacy_scene_version_without_metadata_cannot_be_restored(self):
        task_id = "legacy-scene-version"
        self._prepare_task(task_id)
        manifest = generation_manifest.load_manifest(task_id)
        first = generation_manifest.scene_record(manifest, 1)
        first["version_metadata"] = {}
        generation_manifest.save_manifest(task_id, manifest)

        with self.assertRaisesRegex(ValueError, "predates version metadata"):
            generation_manifest.restore_scene_version(
                task_id,
                1,
                first["active_asset"],
            )


class TestLocalAIProvenance(LocalAITestCase):
    def test_active_material_records_identify_provider_without_host_paths(self):
        task_id = "local-ai-provenance"
        scenes = self.make_scenes(duration=1.0)
        provider = FakeLocalVideoProvider()

        generate_scene_materials(
            task_id,
            provider=provider,
            scenes=scenes,
        )
        records = generation_manifest.local_ai_material_records(task_id)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["provider"], FAKE_SOURCE_ID)
        self.assertEqual(record["scene_id"], 1)
        self.assertEqual(
            record["asset"],
            "generated_ai/scene-001/v001.mp4",
        )
        self.assertFalse(Path(record["asset"]).is_absolute())
        serialized = json.dumps(records)
        self.assertNotIn(str(self.task_root), serialized)
        self.assertIn("model_fingerprint", record)
        self.assertIn("provider_metadata", record)
        self.assertIn("generation_settings", record)


class TestLocalAIStoragePreflight(LocalAITestCase):
    def test_prepare_provider_checks_writable_storage_before_provider_preflight(self):
        from app.services import local_ai

        provider = FakeLocalVideoProvider()
        with (
            patch.object(
                local_ai,
                "create_provider",
                return_value=provider,
            ),
            patch.object(
                provider,
                "preflight",
            ) as provider_preflight,
            patch.object(
                local_ai.tempfile,
                "NamedTemporaryFile",
                side_effect=PermissionError("read-only"),
            ),
            self.assertRaises(local_ai.LocalAIStorageError),
        ):
            local_ai.prepare_provider("wan22_local")

        provider_preflight.assert_not_called()

    def test_preflight_status_returns_actionable_storage_error(self):
        from app.services import local_ai

        with (
            patch.object(
                local_ai,
                "create_provider",
                return_value=FakeLocalVideoProvider(),
            ),
            patch.object(
                local_ai.tempfile,
                "NamedTemporaryFile",
                side_effect=PermissionError("read-only"),
            ),
        ):
            status = local_ai.preflight_status("wan22_local")

        self.assertFalse(status["ready"])
        self.assertEqual(
            status["error_type"],
            "LocalAIStorageError",
        )
        self.assertIn("not writable", status["message"])


class _SyntheticCudaOOM(RuntimeError):
    code = "cuda_oom"


class _OOMFakeProvider(FakeLocalVideoProvider):
    def generate(self, scene, output_path):
        if scene.scene_id == 2:
            raise _SyntheticCudaOOM("synthetic CUDA out of memory")
        return super().generate(scene, output_path)


class TestLocalAITaskIntegration(LocalAITestCase):
    def test_full_fake_pipeline_writes_video_state_and_safe_artifacts(self):
        task_id = "full-fake-pipeline"
        state = MemoryState()
        params = VideoParams(
            video_subject="A short local video",
            video_script="Open the story. Finish the story.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=1,
            local_ai_seed=17,
            local_ai_visual_style="warm documentary",
            subtitle_enabled=True,
            bgm_type="random",
            bgm_volume=0.1,
            font_size=32,
            n_threads=1,
        )

        def offline_tts(*, voice_file, **_kwargs):
            audio = self.make_audio(task_id, 2.0)
            self.assertEqual(str(audio), voice_file)
            return object()

        def offline_subtitle(*, subtitle_file, **_kwargs):
            Path(subtitle_file).write_text(
                "1\n00:00:00,100 --> 00:00:01,700\nOpen the story.\n\n",
                encoding="utf-8",
            )

        with (
            patch.dict("os.environ", {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"}),
            patch.object(task.sm, "state", state),
            patch.object(task.voice, "tts", side_effect=offline_tts),
            patch.object(task.voice, "create_subtitle", side_effect=offline_subtitle),
            patch.object(task.material, "download_videos") as download_videos,
        ):
            result = task.start(task_id, params)

        download_videos.assert_not_called()
        self.assertEqual(state.get_task(task_id)["state"], task.const.TASK_STATE_COMPLETE)
        self.assertEqual(result["warnings"], None)
        self.assertTrue(Path(result["videos"][0]).is_file())
        self.assertTrue(Path(result["subtitle_path"]).is_file())
        self.assertTrue(Path(result["audio_file"]).is_file())
        self.assertGreaterEqual(len(result["materials"]), 2)
        self.assertEqual(
            len(list((self.task_root / task_id).glob("generated_ai/scene-*/v001.mp4"))),
            len(result["materials"]),
        )

        script = json.loads(
            (self.task_root / task_id / "script.json").read_text(encoding="utf-8")
        )
        plan = json.loads(
            (self.task_root / task_id / "scene_plan.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (
                self.task_root / task_id / "generated_ai" / "generation_manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(script["script"], params.video_script)
        self.assertEqual(len(plan["scenes"]), len(result["materials"]))
        self.assertEqual(manifest["provider_id"], FAKE_SOURCE_ID)
        self.assertEqual(len(script["local_ai_materials"]), len(result["materials"]))
        self.assertEqual(
            state.get_task(task_id)["local_ai_materials"],
            script["local_ai_materials"],
        )
        self.assertTrue(
            all(item["provider"] == FAKE_SOURCE_ID for item in script["local_ai_materials"])
        )
        self.assertNotIn(str(self.task_root), json.dumps(script))
        self.assertNotIn(str(self.task_root), json.dumps(plan))
        self.assertNotIn(str(self.task_root), json.dumps(manifest))

    def test_full_fake_pipeline_no_voice_never_calls_tts_provider(self):
        task_id = "full-fake-no-voice"
        state = MemoryState()
        params = VideoParams(
            video_subject="A silent local video",
            video_script="Open the story. Finish the story.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=1,
            local_ai_seed=23,
            voice_name=task.voice.NO_VOICE_NAME,
            subtitle_enabled=True,
            bgm_type="",
            bgm_volume=0,
            font_size=32,
            n_threads=1,
        )

        with (
            patch.dict("os.environ", {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"}),
            patch.object(task.sm, "state", state),
            patch.object(
                task.config,
                "app",
                dict(task.config.app, subtitle_provider="whisper"),
            ),
            patch.object(
                task.voice,
                "tts",
                side_effect=AssertionError(
                    "No Voice mode must not call the generic TTS dispatcher"
                ),
            ) as tts,
            patch.object(task.subtitle, "create") as whisper_create,
            patch.object(task.material, "download_videos") as download_videos,
        ):
            result = task.start(task_id, params)

        tts.assert_not_called()
        whisper_create.assert_not_called()
        download_videos.assert_not_called()
        self.assertEqual(
            state.get_task(task_id)["state"],
            task.const.TASK_STATE_COMPLETE,
        )
        self.assertTrue(Path(result["audio_file"]).is_file())
        self.assertGreater(result["audio_duration"], 0)
        self.assertTrue(Path(result["subtitle_path"]).is_file())
        self.assertTrue(Path(result["videos"][0]).is_file())
        self.assertGreaterEqual(len(result["materials"]), 1)

        script = json.loads(
            (self.task_root / task_id / "script.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            script["params"]["voice_name"],
            task.voice.NO_VOICE_NAME,
        )
        self.assertEqual(
            len(script["local_ai_materials"]),
            len(result["materials"]),
        )

    def test_synthetic_cuda_oom_preserves_completed_scene_and_recovery_hint(self):
        params = VideoParams(
            video_subject="OOM test",
            video_script="First scene. Second scene.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=1,
            subtitle_enabled=False,
            bgm_type="",
        )
        provider = _OOMFakeProvider()

        with (
            patch.object(task.sm.state, "update_task"),
            patch.object(
                task,
                "_mark_task_failed",
                return_value={"state": -1},
            ) as failed,
        ):
            result = task.get_video_materials(
                "synthetic-cuda-oom",
                params,
                [],
                2.0,
                video_script=params.video_script,
                local_ai_provider=provider,
            )

        self.assertIsNone(result)
        manifest = generation_manifest.load_manifest("synthetic-cuda-oom")
        self.assertEqual(manifest["scenes"][0]["status"], "ready")
        self.assertTrue(manifest["scenes"][0]["active_asset"])
        self.assertEqual(manifest["scenes"][1]["status"], "failed")
        self.assertIsNone(manifest["scenes"][1]["active_asset"])
        self.assertEqual(manifest["scenes"][1]["error_code"], "cuda_oom")

        details = failed.call_args.kwargs["details"]
        self.assertEqual(details["local_ai_error_code"], "cuda_oom")
        self.assertTrue(details["recoverable"])
        self.assertEqual(
            details["recovery_action"],
            "adjust_gpu_settings_and_retry_scene",
        )

    def test_scene_failure_records_structured_recovery_fields(self):
        params = VideoParams(
            video_subject="test",
            video_script="One scene.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=2,
            subtitle_enabled=False,
            bgm_type="",
        )
        provider = FakeLocalVideoProvider(fail_scene_ids={1})

        with (
            patch.object(task.sm.state, "update_task"),
            patch.object(
                task,
                "_mark_task_failed",
                return_value={"state": -1},
            ) as failed,
        ):
            result = task.get_video_materials(
                "structured-scene-failure",
                params,
                [],
                1.0,
                video_script=params.video_script,
                local_ai_provider=provider,
            )

        self.assertIsNone(result)
        details = failed.call_args.kwargs["details"]
        self.assertEqual(details["local_ai_provider"], FAKE_SOURCE_ID)
        self.assertEqual(details["scene_id"], 1)
        self.assertTrue(details["recoverable"])
        self.assertEqual(details["recovery_action"], "retry_scene")
        self.assertEqual(details["local_ai_error_type"], "RuntimeError")


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
