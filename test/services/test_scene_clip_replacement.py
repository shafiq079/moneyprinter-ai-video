import json
import ast
from io import BytesIO
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import av
from streamlit.testing.v1 import AppTest

from app.models import const
from app.models.schema import VideoParams
from app.services import generation_manifest as gm
from app.services import scene_planner, task, task_artifacts, webui_task
from app.services.local_ai import FAKE_SOURCE_ID, LocalAISceneGenerationError
from app.services.local_ai import clip_import
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestSceneClipReplacement(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.state = MemoryState()
        self.state_patch = patch.object(task.sm, "state", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.public_patch = patch.object(
            task.local_ai, "is_public_source", return_value=True
        )
        self.public_patch.start()
        self.addCleanup(self.public_patch.stop)
        self.task_id = "clip-edit"
        self.params = VideoParams(
            video_subject="Garden",
            video_script="Flowers open. Bees arrive.",
            video_source=FAKE_SOURCE_ID,
            video_aspect="9:16",
            video_clip_duration=1,
            subtitle_enabled=True,
            font_name="MicrosoftYaHeiBold.ttc",
            font_size=32,
            bgm_type="",
            bgm_volume=0,
            n_threads=1,
        )
        self.plan = scene_planner.get_or_create_scene_plan(
            self.task_id,
            self.params.video_script,
            audio_duration=2,
            max_scene_duration=1,
            aspect="9:16",
            base_seed=42,
            use_llm=False,
        )
        generate_scene_materials(
            self.task_id,
            provider=FakeLocalVideoProvider(),
            scenes=list(self.plan.scenes),
        )
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.root = Path(utils.task_dir(self.task_id))
        self.make_audio(self.task_id)
        (self.root / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nFlowers open.\n\n", encoding="utf-8"
        )

    def upload(self, *, size="90x160", duration=2, audio=True):
        target = self.task_root / "upload.mp4"
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s={size}:r=24:d={duration}",
        ]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
        command += [
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
        ]
        if audio:
            command += ["-c:a", "aac"]
        subprocess.run(command + [str(target)], capture_output=True, check=True)
        return target.read_bytes()

    def long_active_clip(self):
        record = gm.scene_record(gm.load_manifest(self.task_id), 1)
        asset = record["active_asset"]
        destination = gm.resolve_asset(self.task_id, asset)
        subprocess.run([
            utils.get_ffmpeg_binary(), "-y", "-f", "lavfi", "-i",
            "color=c=red:s=90x160:r=24:d=1", "-f", "lavfi", "-i",
            "color=c=blue:s=90x160:r=24:d=2", "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[out]", "-map", "[out]",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
            str(destination),
        ], capture_output=True, check=True)
        return asset

    def test_trim_saved_clip_exports_selected_frames_and_preserves_assets(self):
        asset = self.long_active_clip()
        before = gm.load_manifest(self.task_id)
        before["playback_order"] = [2, 1]
        gm.save_manifest(self.task_id, before)
        immutable = {name: (self.root / name).read_bytes() for name in (
            "audio.mp3", "subtitle.srt", "scene_plan.json",
        )}
        with (
            patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("AI")),
            patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
            patch.object(task, "generate_subtitle", side_effect=AssertionError("caption")),
            patch.object(task.sonilo, "generate_bgm", side_effect=AssertionError("BGM")),
            patch.object(task, "_schedule_cross_post", side_effect=AssertionError("publish")),
        ):
            result = task.trim_local_ai_scene_clip(self.task_id, 1, 1.5, expected_asset=asset)
        after = gm.load_manifest(self.task_id)
        self.assertEqual(gm.scene_record(before, 2), gm.scene_record(after, 2))
        self.assertEqual(gm.scene_playback_order(after), [2, 1])
        for name, data in immutable.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        for candidate in (result["scene_file"], result["videos"][0]):
            with av.open(candidate) as container:
                threshold = 0.1 if candidate == result["scene_file"] else 1.5
                for frame in container.decode(video=0):
                    if frame.time >= threshold:
                        break
                rgb = frame.to_ndarray(format="rgb24").mean(axis=(0, 1))
                self.assertGreater(rgb[2], rgb[0] + 100)
        record = gm.scene_record(after, 1)
        self.assertEqual(record["import_metadata"]["source_asset"], asset)
        self.assertEqual(record["import_metadata"]["start_seconds"], 1.5)
        self.assertEqual(next(r for r in gm.local_ai_material_records(self.task_id) if r["scene_id"] == 1)["provider"], "scene_trim")
        self.assertIn(asset, record["versions"])
        provider = FakeLocalVideoProvider()
        generate_scene_materials(self.task_id, provider=provider, scenes=list(self.plan.scenes))
        self.assertEqual(provider.generated_scene_ids, [])
        task.restore_local_ai_scene_version(self.task_id, 1, asset)
        task.restore_local_ai_scene_version(self.task_id, 1, record["active_asset"])
        self.assertEqual(next(r for r in gm.local_ai_material_records(self.task_id) if r["scene_id"] == 1)["provider"], "scene_trim")

    def test_upload_start_uses_later_footage_and_rejects_short_remainder(self):
        asset = self.long_active_clip()
        content = gm.resolve_asset(self.task_id, asset).read_bytes()
        manifest, candidate = clip_import.stage_clip_import(
            self.task_id, self.plan.scenes[0], content, start_seconds=1.5,
        )
        with av.open(str(candidate)) as container:
            self.assertFalse(container.streams.audio)
            frame = next(container.decode(video=0)).to_ndarray(format="rgb24")
            self.assertGreater(frame[:, :, 2].mean(), 200)
        self.assertEqual(gm.scene_record(manifest, 1)["import_metadata"]["start_seconds"], 1.5)
        with self.assertRaises(ValueError):
            clip_import.stage_clip_import(self.task_id, self.plan.scenes[0], content, start_seconds=2.8)

    def test_trim_invalid_offsets_and_stale_version_leave_previous_outputs(self):
        asset = self.long_active_clip()
        previous = gm.manifest_path(self.task_id).read_bytes()
        (self.root / "final-1.mp4").write_bytes(b"previous")
        for offset in (-1, float("nan"), float("inf"), True, "1", 2.8):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                task.trim_local_ai_scene_clip(self.task_id, 1, offset, expected_asset=asset)
            self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), previous)
            self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"previous")
        with self.assertRaisesRegex(ValueError, "changed"):
            task.trim_local_ai_scene_clip(self.task_id, 1, 1, expected_asset="stale.mp4")

    def test_trim_render_failure_rolls_back_manifest_and_both_outputs(self):
        asset = self.long_active_clip()
        before = gm.manifest_path(self.task_id).read_bytes()
        for name in ("final-1.mp4", "combined-1.mp4"):
            (self.root / name).write_bytes(b"previous")
        with patch.object(task, "generate_final_videos", side_effect=RuntimeError("render")):
            with self.assertRaisesRegex(RuntimeError, "render"):
                task.trim_local_ai_scene_clip(self.task_id, 1, 1.5, expected_asset=asset)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        for name in ("final-1.mp4", "combined-1.mp4"):
            self.assertEqual((self.root / name).read_bytes(), b"previous")
        self.assertFalse((self.root / "generated_ai/scene-001/v002.mp4").exists())

    def test_trim_restart_reuses_cut_after_model_change_and_blocks_damage(self):
        asset = self.long_active_clip()
        manifest, candidate = clip_import.stage_clip_import(
            self.task_id, self.plan.scenes[0], gm.resolve_asset(self.task_id, asset).read_bytes(),
            start_seconds=1.5, source_metadata={"operation": "trim", "source_asset": asset},
        )
        gm.save_manifest(self.task_id, manifest)
        provider = FakeLocalVideoProvider()
        provider.model_fingerprint = "fake:new-model"
        generate_scene_materials(self.task_id, provider=provider, scenes=list(self.plan.scenes))
        self.assertEqual(provider.generated_scene_ids, [2])
        self.assertEqual(gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"], str(candidate.relative_to(self.root)))
        candidate.write_bytes(b"damaged")
        provider = FakeLocalVideoProvider()
        with self.assertRaises(LocalAISceneGenerationError):
            generate_scene_materials(self.task_id, provider=provider, scenes=list(self.plan.scenes))
        self.assertEqual(provider.generated_scene_ids, [])

    def test_stale_queued_trim_and_missing_captions_preserve_newer_version(self):
        asset = self.long_active_clip()
        (self.root / "final-1.mp4").write_bytes(b"previous")
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_scene_clip_replacement(
                self.task_id, 1, b"", start_seconds=1.5, expected_asset=asset, capture_logs=False,
            )
        manifest, candidate = clip_import.stage_clip_import(
            self.task_id, self.plan.scenes[0], self.upload(),
        )
        gm.save_manifest(self.task_id, manifest)
        before = gm.manifest_path(self.task_id).read_bytes()
        args, kwargs = queue.call_args
        self.assertIn("error", args[0](**kwargs))
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"previous")
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        (self.root / "subtitle.srt").unlink()
        with self.assertRaisesRegex(ValueError, "captions"):
            task.trim_local_ai_scene_clip(self.task_id, 1, 0.1, expected_asset=str(candidate.relative_to(self.root)))

    def test_trim_queue_worker_and_queue_failure_recover(self):
        asset = self.long_active_clip()
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_scene_clip_replacement(
                self.task_id, 1, b"", start_seconds=1.5, expected_asset=asset,
                capture_logs=False,
            )
        args, kwargs = queue.call_args
        result = args[0](**kwargs)
        self.assertNotIn("error", result)
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        new_asset = gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"]
        with patch.object(webui_task._task_manager, "add_task", side_effect=RuntimeError("queue")):
            with self.assertRaisesRegex(RuntimeError, "queue"):
                webui_task.submit_scene_clip_replacement(
                    self.task_id, 1, b"", start_seconds=0.1, expected_asset=new_asset,
                )
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"], new_asset)

    def replace_clip(self, content=None):
        return task.replace_local_ai_scene_clip(
            self.task_id, 1, self.upload() if content is None else content
        )

    def test_real_replacement_composes_without_ai_audio_caption_or_publishing_calls(
        self,
    ):
        before = gm.load_manifest(self.task_id)
        other = gm.scene_record(before, 2)
        plan_bytes = (self.root / "scene_plan.json").read_bytes()
        audio_bytes = (self.root / "audio.mp3").read_bytes()
        captions = (self.root / "subtitle.srt").read_bytes()
        script = json.loads((self.root / "script.json").read_text())
        with (
            patch.object(
                task.local_ai, "prepare_provider", side_effect=AssertionError("AI")
            ),
            patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
            patch.object(
                task, "generate_subtitle", side_effect=AssertionError("captions")
            ),
            patch.object(
                task.sonilo, "generate_bgm", side_effect=AssertionError("BGM")
            ),
            patch.object(
                task, "_schedule_cross_post", side_effect=AssertionError("publish")
            ),
        ):
            result = self.replace_clip()
        after = gm.load_manifest(self.task_id)
        first = gm.scene_record(after, 1)
        self.assertEqual(gm.scene_record(after, 2), other)
        self.assertEqual(first["asset_origin"], "imported")
        self.assertEqual(len(first["versions"]), 2)
        self.assertEqual((self.root / "scene_plan.json").read_bytes(), plan_bytes)
        self.assertEqual((self.root / "audio.mp3").read_bytes(), audio_bytes)
        self.assertEqual((self.root / "subtitle.srt").read_bytes(), captions)
        current_script = json.loads((self.root / "script.json").read_text())
        self.assertEqual(current_script["script"], script["script"])
        self.assertEqual(current_script["params"], script["params"])
        with av.open(result["scene_file"]) as media:
            self.assertFalse(media.streams.audio)
            self.assertLessEqual(
                float(media.duration / av.time_base),
                self.plan.scenes[0].target_duration + 0.05,
            )
            self.assertEqual(media.streams.video[0].codec_context.name, "h264")
        with av.open(result["videos"][0]) as media:
            self.assertTrue(media.streams.audio)
            self.assertEqual(
                (media.streams.video[0].width, media.streams.video[0].height),
                (1080, 1920),
            )
        provenance = gm.local_ai_material_records(self.task_id)[0]
        self.assertEqual(provenance["provider"], "manual_upload")
        self.assertIsNone(provenance["model_fingerprint"])
        self.assertIsNone(provenance["seed"])
        self.assertEqual(current_script["local_ai_materials"][0], provenance)
        package = task_artifacts.build_output_package(self.task_id)
        self.assertIn(first["active_asset"], package["scene_materials"])

    def test_replacement_reuses_saved_generated_bgm(self):
        self.params.bgm_type = "sonilo"
        self.params.bgm_volume = 0.1
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        bgm = self.root / "sonilo-bgm-1.m4a"
        subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-y",
                "-i",
                str(self.root / "audio.mp3"),
                "-c:a",
                "aac",
                str(bgm),
            ],
            capture_output=True,
            check=True,
        )
        saved_bgm = bgm.read_bytes()
        with patch.object(
            task.sonilo, "generate_bgm", side_effect=AssertionError("BGM")
        ):
            result = self.replace_clip()
        self.assertEqual(result["warnings"], [])
        self.assertEqual(bgm.read_bytes(), saved_bgm)

    def test_invalid_uploads_leave_manifest_and_old_outputs_unchanged(self):
        (self.root / "final-1.mp4").write_bytes(b"previous final")
        before = gm.manifest_path(self.task_id).read_bytes()
        for content in (
            b"",
            b"broken MP4",
            self.upload(size="160x90"),
            self.upload(duration=0.2),
        ):
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                self.replace_clip(content)
            self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
            self.assertEqual(
                (self.root / "final-1.mp4").read_bytes(), b"previous final"
            )
        self.assertFalse(list((self.root / "generated_ai").rglob("*.partial.mp4")))

    def test_render_failure_rolls_back_active_version_and_all_outputs(self):
        (self.root / "final-1.mp4").write_bytes(b"previous final")
        (self.root / "combined-1.mp4").write_bytes(b"previous combined")
        before = gm.manifest_path(self.task_id).read_bytes()
        script = (self.root / "script.json").read_bytes()

        def fail_render(*_args, **_kwargs):
            (self.root / "final-2.mp4").write_bytes(b"partial render")
            raise RuntimeError("synthetic render failure")

        with patch.object(task, "generate_final_videos", side_effect=fail_render):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                self.replace_clip()
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertEqual((self.root / "script.json").read_bytes(), script)
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"previous final")
        self.assertEqual(
            (self.root / "combined-1.mp4").read_bytes(), b"previous combined"
        )
        self.assertFalse((self.root / "final-2.mp4").exists())
        self.assertFalse((self.root / "generated_ai/scene-001/v002.mp4").exists())
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )

    def test_generated_and_imported_versions_restore_and_regenerate_with_correct_origin(
        self,
    ):
        self.replace_clip()
        uploaded = gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"]
        task.restore_local_ai_scene_version(
            self.task_id, 1, "generated_ai/scene-001/v001.mp4"
        )
        self.assertEqual(
            gm.scene_record(gm.load_manifest(self.task_id), 1)["asset_origin"],
            "generated",
        )
        task.restore_local_ai_scene_version(self.task_id, 1, uploaded)
        self.assertEqual(
            gm.local_ai_material_records(self.task_id)[0]["provider"], "manual_upload"
        )
        provider = FakeLocalVideoProvider()
        with patch.object(task.local_ai, "prepare_provider", return_value=provider):
            task.regenerate_local_ai_scene(self.task_id, 1, seed=97)
        self.assertEqual(provider.generated_scene_ids, [1])
        self.assertEqual(
            gm.scene_record(gm.load_manifest(self.task_id), 1)["asset_origin"],
            "generated",
        )
        self.assertEqual(
            self.state.get_task(self.task_id)["local_ai_materials"][0]["provider"],
            FAKE_SOURCE_ID,
        )

    def test_resume_after_restart_preserves_import_and_only_generates_missing_scene(
        self,
    ):
        self.replace_clip()
        original = gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"]
        gm.resolve_asset(self.task_id, "generated_ai/scene-002/v001.mp4").unlink()
        restarted = MemoryState()
        restarted.update_task(self.task_id, state=const.TASK_STATE_FAILED)
        self.public_patch.stop()
        with (
            patch.object(task.sm, "state", restarted),
            patch.dict("os.environ", {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"}),
            patch.object(task, "generate_script", side_effect=AssertionError("script")),
            patch.object(task, "generate_audio", side_effect=AssertionError("audio")),
            patch.object(
                task, "generate_subtitle", side_effect=AssertionError("captions")
            ),
        ):
            context = task.load_local_ai_resume_context(self.task_id)
            provider = FakeLocalVideoProvider()
            provider.model_fingerprint = "fake:new-revision"
            with patch.object(task.local_ai, "prepare_provider", return_value=provider):
                result = task.start(
                    self.task_id, context["params"], resume_context=context
                )
        self.assertTrue(result["videos"])
        self.assertEqual(provider.generated_scene_ids, [2])
        self.assertEqual(
            gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"], original
        )

    def test_damaged_import_blocks_resume_before_any_ai_scene_work(self):
        self.replace_clip()
        record = gm.scene_record(gm.load_manifest(self.task_id), 1)
        gm.resolve_asset(self.task_id, record["active_asset"]).write_bytes(b"damaged")
        provider = FakeLocalVideoProvider()
        with self.assertRaises(LocalAISceneGenerationError) as failure:
            generate_scene_materials(
                self.task_id, provider=provider, scenes=list(self.plan.scenes)
            )
        self.assertEqual(failure.exception.error_code, "imported_clip_invalid")
        self.assertEqual(provider.runtime_load_count, 0)
        self.assertEqual(provider.generated_scene_ids, [])
        self.assertEqual(
            task._local_ai_recovery_action(
                stage="materials", error_code="imported_clip_invalid"
            ),
            "replace_imported_clip_or_restore_version",
        )

    def test_import_cannot_silently_survive_changed_scene_timing(self):
        self.replace_clip()
        changed = [
            replace(self.plan.scenes[0], target_duration=0.5),
            self.plan.scenes[1],
        ]
        with self.assertRaises(LocalAISceneGenerationError):
            generate_scene_materials(
                self.task_id, provider=FakeLocalVideoProvider(), scenes=changed
            )

    def test_cached_import_uses_generic_validation_and_missing_import_can_be_restored(
        self,
    ):
        manifest, imported = clip_import.stage_clip_import(
            self.task_id, self.plan.scenes[0], self.upload()
        )
        gm.save_manifest(self.task_id, manifest)
        provider = FakeLocalVideoProvider()
        validate = provider.validate_output

        def generated_only(candidate, scene):
            self.assertNotEqual(Path(candidate), imported)
            return validate(candidate, scene)

        with patch.object(provider, "validate_output", side_effect=generated_only):
            materials = generate_scene_materials(
                self.task_id, provider=provider, scenes=list(self.plan.scenes)
            )
        self.assertIn(str(imported), materials)
        self.assertEqual(provider.runtime_load_count, 0)
        imported.unlink()
        with self.assertRaises(LocalAISceneGenerationError):
            generate_scene_materials(
                self.task_id, provider=provider, scenes=list(self.plan.scenes)
            )
        gm.restore_scene_version(self.task_id, 1, "generated_ai/scene-001/v001.mp4")
        self.assertEqual(len(gm.active_scene_paths(self.task_id)), 2)

    def test_normalization_timeout_and_unsafe_scene_directory_publish_nothing(self):
        before = gm.manifest_path(self.task_id).read_bytes()
        content = self.upload()
        with patch.object(
            clip_import.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("ffmpeg", 120),
        ):
            with self.assertRaisesRegex(ValueError, "timed out"):
                clip_import.stage_clip_import(
                    self.task_id, self.plan.scenes[0], content
                )
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertFalse(list((self.root / "generated_ai").rglob("*.partial.mp4")))
        scene_dir = self.root / "generated_ai/scene-001"
        scene_dir.rename(scene_dir.with_name("saved-scene"))
        outside = self.task_root / "outside"
        outside.mkdir()
        try:
            scene_dir.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "escapes"):
            clip_import.stage_clip_import(self.task_id, self.plan.scenes[0], content)
        self.assertFalse(list(outside.iterdir()))

    def test_queue_executes_real_replacement_and_restore_workers(self):
        content = self.upload()
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_scene_clip_replacement(
                self.task_id, 1, content, capture_logs=False
            )
        submission = add_task.call_args
        result = submission.args[0](**submission.kwargs)
        self.assertNotIn("error", result)
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_scene_version_restore(
                self.task_id,
                1,
                relative_path="generated_ai/scene-001/v001.mp4",
                capture_logs=False,
            )
        submission = add_task.call_args
        result = submission.args[0](**submission.kwargs)
        self.assertTrue(result["restored"])
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_local_ai_rerender(
                self.task_id, self.params, capture_logs=False
            )
        submission = add_task.call_args
        self.assertTrue(submission.args[0](**submission.kwargs)["render_only"])
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_scene_regeneration(
                self.task_id,
                1,
                prompt="A closer view of flowers.",
                seed=90,
                capture_logs=False,
            )
        submission = add_task.call_args
        provider = FakeLocalVideoProvider()
        with patch.object(task.local_ai, "prepare_provider", return_value=provider):
            self.assertNotIn("error", submission.args[0](**submission.kwargs))
        self.assertEqual(provider.generated_scene_ids, [1])

    def test_queue_failure_and_busy_task_do_not_change_assets(self):
        before = gm.manifest_path(self.task_id).read_bytes()
        self.state.update_task(
            self.task_id, state=const.TASK_STATE_COMPLETE, progress=100
        )
        with patch.object(
            webui_task._task_manager, "add_task", side_effect=RuntimeError("queue full")
        ):
            with self.assertRaisesRegex(RuntimeError, "queue full"):
                webui_task.submit_scene_clip_replacement(
                    self.task_id, 1, b"upload", capture_logs=False
                )
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.replace_clip(b"upload")
        with patch.object(clip_import, "MAX_CLIP_UPLOAD_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "100 MiB"):
                self.replace_clip(b"large")

    def test_missing_required_captions_rejects_replacement_without_changing_assets(self):
        (self.root / "subtitle.srt").unlink()
        before = gm.manifest_path(self.task_id).read_bytes()
        with self.assertRaisesRegex(ValueError, "captions are unavailable"):
            self.replace_clip(b"upload")
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        # After a process restart a completed task may exist only on disk.
        (self.root / "final-1.mp4").write_bytes(b"previous final")
        self.state.delete_task(self.task_id)
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_scene_clip_replacement(self.task_id, 1, b"upload", capture_logs=False)
        submission = add_task.call_args
        self.assertIn("error", submission.args[0](**submission.kwargs))
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"previous final")

    def test_scene_editor_upload_action_and_busy_controls(self):
        main = Path(__file__).parents[2] / "webui" / "Main.py"
        source = main.read_text(encoding="utf-8")
        function = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_scene_editor"
        )
        harness = """
import os
import streamlit as st
from app.services import generation_manifest, scene_planner, webui_task
from app.services import state as sm
from app.services import task as tm
from app.utils import utils
from app.services.local_ai.clip_import import MAX_CLIP_UPLOAD_BYTES
def tr(value):
    return value
st.session_state["scene_editor_task_id"] = "clip-edit"
"""
        harness += (
            ast.get_source_segment(source, function) + "\n_render_scene_editor()\n"
        )
        app = AppTest.from_string(harness, default_timeout=30).run()
        buttons = [
            b for b in app.button if str(b.key).startswith("replace_scene_clip_")
        ]
        self.assertEqual(len(buttons), 2)
        self.assertTrue(all(b.disabled for b in buttons))
        content = self.upload()
        with (
            patch("streamlit.file_uploader", return_value=BytesIO(content)),
            patch.object(webui_task, "submit_scene_clip_replacement") as submit,
            patch("streamlit.rerun"),
        ):
            app.run()
            app.button(key="replace_scene_clip_clip-edit_1").click().run()
            submit.assert_called_once_with("clip-edit", 1, content, start_seconds=0.0)
        trim_key = "scene_trim_start_clip-edit_1_generated_ai/scene-001/v001.mp4"
        self.assertTrue(app.button(key="trim_scene_clip_clip-edit_1").disabled)
        with patch.object(webui_task, "submit_scene_clip_replacement") as submit, patch("streamlit.rerun"):
            app.number_input(key=trim_key).set_value(0.5).run()
            app.button(key="trim_scene_clip_clip-edit_1").click().run()
            submit.assert_called_once_with(
                "clip-edit", 1, b"", start_seconds=0.5,
                expected_asset="generated_ai/scene-001/v001.mp4",
            )
        self.assertFalse(app.exception)
        manifest, _ = clip_import.stage_clip_import(self.task_id, self.plan.scenes[0], content)
        gm.save_manifest(self.task_id, manifest)
        app.run()
        self.assertEqual(
            app.selectbox(key="scene_version_clip-edit_1").value,
            gm.scene_record(manifest, 1)["active_asset"],
        )
        self.assertIn("Uploaded Clip", app.selectbox(key="scene_version_clip-edit_1").options[-1])
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        with patch("streamlit.file_uploader", return_value=BytesIO(content)):
            app.run()
        self.assertTrue(app.button(key="replace_scene_clip_clip-edit_1").disabled)
        self.assertTrue(app.button(key="trim_scene_clip_clip-edit_1").disabled)
