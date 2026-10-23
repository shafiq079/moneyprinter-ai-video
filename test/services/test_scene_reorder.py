import ast
import json
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import av
from streamlit.testing.v1 import AppTest

from app.models import const
from app.models.schema import VideoParams
from app.services import generation_manifest as gm
from app.services import scene_planner, task, task_artifacts, webui_task
from app.services.local_ai import FAKE_SOURCE_ID
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.local_ai.orchestrator import generate_scene_materials
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestSceneReorder(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.state = MemoryState()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(task.sm, "state", self.state))
        self.stack.enter_context(
            patch.object(task.local_ai, "is_public_source", return_value=True)
        )
        self.task_id = "reorder"
        self.params = VideoParams(
            video_subject="Garden",
            video_script="Flowers open. Bees arrive. Night falls.",
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
            audio_duration=3,
            max_scene_duration=1,
            aspect="9:16",
            base_seed=42,
            use_llm=False,
        )
        self.assertEqual(len(self.plan.scenes), 3)
        generate_scene_materials(
            self.task_id,
            provider=FakeLocalVideoProvider(),
            scenes=list(self.plan.scenes),
        )
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.root = Path(utils.task_dir(self.task_id))
        self.make_audio(self.task_id, duration=3)
        (self.root / "subtitle.srt").write_text(
            "1\n00:00:00,000 --> 00:00:03,000\nFlowers open.\n\n",
            encoding="utf-8",
        )

    def save_order(self, order):
        manifest = gm.load_manifest(self.task_id)
        manifest["playback_order"] = order
        gm.save_manifest(self.task_id, manifest)
        return manifest

    def test_real_export_follows_order_without_generation_or_audio_changes(self):
        # Unequal clip lengths move their cut times, while the fixed voice track
        # and total video duration remain unchanged.
        self.plan = replace(
            self.plan,
            scenes=tuple(
                replace(scene, target_duration=duration)
                for scene, duration in zip(self.plan.scenes, (1.25, 0.75, 1.0))
            ),
        )
        scene_planner.save_scene_plan(self.task_id, self.plan)
        generate_scene_materials(
            self.task_id,
            provider=FakeLocalVideoProvider(),
            scenes=list(self.plan.scenes),
        )
        self.params.video_clip_duration = 2
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        before = gm.load_manifest(self.task_id)
        immutable = {
            name: (self.root / name).read_bytes()
            for name in ("scene_plan.json", "audio.mp3", "subtitle.srt")
        }
        clips = {p: Path(p).read_bytes() for p in gm.active_scene_paths(self.task_id)}
        script = json.loads((self.root / "script.json").read_text())
        with ExitStack() as stack:
            for module, name in (
                (task.local_ai, "prepare_provider"),
                (task.voice, "tts"),
                (task, "generate_subtitle"),
                (task.sonilo, "generate_bgm"),
                (task, "_schedule_cross_post"),
                (task, "generate_script"),
            ):
                stack.enter_context(
                    patch.object(module, name, side_effect=AssertionError(name))
                )
            result = task.reorder_local_ai_scenes(self.task_id, [3, 1, 2])
        after = gm.load_manifest(self.task_id)
        self.assertTrue(result["reordered"])
        self.assertEqual(after, {**before, "playback_order": [3, 1, 2]})
        for name, content in immutable.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        for name, content in clips.items():
            self.assertEqual(Path(name).read_bytes(), content)
        current_script = json.loads((self.root / "script.json").read_text())
        self.assertEqual(current_script["params"], script["params"])
        self.assertEqual(current_script["script"], script["script"])
        self.assertEqual(
            [r["scene_id"] for r in current_script["local_ai_materials"]], [3, 1, 2]
        )
        self.assertEqual(
            task_artifacts.build_output_package(self.task_id)["scene_materials"],
            [
                gm.scene_record(after, scene_id)["active_asset"]
                for scene_id in (3, 1, 2)
            ],
        )
        # Decode the actual delivery MP4. The fake provider's scenes are blue,
        # green and purple; sample away from caption text and visual boundaries.
        with av.open(result["videos"][0]) as media:
            self.assertTrue(media.streams.audio)
            self.assertAlmostEqual(float(media.duration / av.time_base), 3, delta=0.2)
            samples = []
            targets = iter((0.4, 1.4, 2.4))
            target = next(targets)
            for frame in media.decode(video=0):
                if frame.time >= target:
                    samples.append(frame.to_ndarray(format="rgb24")[50, 50].tolist())
                    target = next(targets, None)
                    if target is None:
                        break
        self.assertEqual(len(samples), 3)
        for actual, expected in zip(
            samples, ((73, 54, 100), (23, 50, 77), (39, 76, 60))
        ):
            self.assertTrue(
                all(abs(a - e) < 12 for a, e in zip(actual, expected)), samples
            )

    def test_cached_and_partial_resume_preserve_order_without_changing_generation_identity(
        self,
    ):
        before = self.save_order([2, 3, 1])
        self.state.update_task(self.task_id, state=const.TASK_STATE_FAILED)
        context = task.load_local_ai_resume_context(self.task_id)
        cached = FakeLocalVideoProvider()
        outputs = generate_scene_materials(
            self.task_id,
            provider=cached,
            scenes=list(context["scene_plan"].scenes),
        )
        self.assertEqual(cached.generated_scene_ids, [])
        self.assertEqual(cached.runtime_load_count, 0)
        self.assertEqual(outputs, gm.active_scene_paths(self.task_id))
        self.assertEqual(
            [Path(p).parent.name for p in outputs],
            ["scene-002", "scene-003", "scene-001"],
        )
        gm.resolve_asset(
            self.task_id, gm.scene_record(before, 3)["active_asset"]
        ).unlink()
        resumed = FakeLocalVideoProvider()
        with (
            patch.object(task.local_ai, "prepare_provider", return_value=resumed),
            patch.object(task.local_ai, "is_public_source", return_value=False),
            patch.object(task, "generate_audio", side_effect=AssertionError("audio")),
            patch.object(
                task, "generate_subtitle", side_effect=AssertionError("captions")
            ),
            patch.object(task, "generate_script", side_effect=AssertionError("script")),
            patch.object(
                task, "generate_final_videos", return_value=(["final"], [], [])
            ) as render,
            patch.object(
                task.upload_post.upload_post_service,
                "is_configured",
                return_value=False,
            ),
        ):
            result = task.start(self.task_id, context["params"], resume_context=context)
        self.assertEqual(resumed.generated_scene_ids, [3])
        self.assertEqual(result["materials"], gm.active_scene_paths(self.task_id))
        self.assertEqual(render.call_args.args[2], result["materials"])
        after = gm.load_manifest(self.task_id)
        self.assertEqual(after["playback_order"], [2, 3, 1])
        for scene_id in (1, 2):
            for key in (
                "fingerprint",
                "active_asset",
                "versions",
                "version_metadata",
                "target_duration",
            ):
                self.assertEqual(
                    gm.scene_record(after, scene_id)[key],
                    gm.scene_record(before, scene_id)[key],
                )
        changed_model = FakeLocalVideoProvider()
        changed_model.model_fingerprint = "fake:changed"
        generate_scene_materials(
            self.task_id, provider=changed_model, scenes=list(self.plan.scenes)
        )
        self.assertEqual(changed_model.generated_scene_ids, [1, 2, 3])
        self.assertEqual(gm.load_manifest(self.task_id)["playback_order"], [2, 3, 1])

    def test_legacy_order_and_invalid_orders_fail_before_render_or_generation(self):
        original = gm.manifest_path(self.task_id).read_bytes()
        self.assertEqual(
            gm.scene_playback_order(gm.load_manifest(self.task_id)), [1, 2, 3]
        )
        with patch.object(task, "generate_final_videos") as render:
            for invalid in (
                [1, 1, 2],
                [1, 2],
                [1, 2, 4],
                [True, 2, 3],
                ["1", 2, 3],
                None,
            ):
                with self.subTest(order=invalid), self.assertRaises(ValueError):
                    task.reorder_local_ai_scenes(self.task_id, invalid)
            render.assert_not_called()
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), original)
        self.save_order([1, 1, 2])
        invalid_bytes = gm.manifest_path(self.task_id).read_bytes()
        provider = FakeLocalVideoProvider()
        with self.assertRaisesRegex(ValueError, "exactly once"):
            generate_scene_materials(
                self.task_id, provider=provider, scenes=list(self.plan.scenes)
            )
        self.assertEqual(provider.runtime_load_count, 0)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), invalid_bytes)

    def test_stale_noop_and_busy_requests_do_not_mutate_assets(self):
        self.save_order([3, 1, 2])
        before = gm.manifest_path(self.task_id).read_bytes()
        with patch.object(task, "generate_final_videos") as render:
            self.assertFalse(
                task.reorder_local_ai_scenes(self.task_id, [3, 1, 2])["reordered"]
            )
            with self.assertRaisesRegex(ValueError, "has changed"):
                task.reorder_local_ai_scenes(
                    self.task_id, [2, 3, 1], expected_order=[1, 2, 3]
                )
            render.assert_not_called()
        for status in (
            {"state": const.TASK_STATE_PROCESSING},
            {
                "state": const.TASK_STATE_COMPLETE,
                "cross_post_state": const.CROSS_POST_STATE_PROCESSING,
            },
        ):
            self.state.update_task(self.task_id, **status)
            with self.assertRaisesRegex(RuntimeError, "busy"):
                task.reorder_local_ai_scenes(self.task_id, [2, 3, 1])
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)

    def test_render_failure_restores_manifest_and_all_outputs(self):
        self.save_order([2, 1, 3])
        before = gm.manifest_path(self.task_id).read_bytes()
        script = (self.root / "script.json").read_bytes()
        (self.root / "final-1.mp4").write_bytes(b"old final")
        (self.root / "combined-1.mp4").write_bytes(b"old combined")
        active = Path(gm.active_scene_paths(self.task_id)[0])
        clip_bytes = active.read_bytes()
        active.unlink()
        with self.assertRaisesRegex(ValueError, "active asset is missing"):
            task.reorder_local_ai_scenes(self.task_id, [3, 2, 1])
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"old final")
        active.write_bytes(clip_bytes)

        def fail_render(*args, **kwargs):
            (self.root / "final-2.mp4").write_bytes(b"partial output")
            raise RuntimeError("render fixture")

        with patch.object(task, "generate_final_videos", side_effect=fail_render):
            with self.assertRaisesRegex(RuntimeError, "render fixture"):
                task.reorder_local_ai_scenes(self.task_id, [3, 2, 1])
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        self.assertEqual((self.root / "script.json").read_bytes(), script)
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"old final")
        self.assertEqual((self.root / "combined-1.mp4").read_bytes(), b"old combined")
        self.assertFalse((self.root / "final-2.mp4").exists())
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )

    def test_queue_reservation_worker_failure_and_restart_recovery(self):
        before = gm.manifest_path(self.task_id).read_bytes()
        (self.root / "final-1.mp4").write_bytes(b"old final")
        with patch.object(
            webui_task._task_manager, "add_task", side_effect=RuntimeError("full")
        ):
            with self.assertRaisesRegex(RuntimeError, "full"):
                webui_task.submit_scene_reorder(
                    self.task_id, [3, 2, 1], capture_logs=False
                )
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), before)
        proposed = [3, 2, 1]
        with patch.object(webui_task._task_manager, "add_task") as add:
            webui_task.submit_scene_reorder(self.task_id, proposed, capture_logs=False)
        proposed.reverse()  # The queue owns an immutable snapshot of the request.

        def render_stub(*args, **kwargs):
            final = self.root / "final-1.mp4"
            final.write_bytes(b"new final")
            return [str(final)], [], []

        with patch.object(task, "generate_final_videos", side_effect=render_stub):
            result = add.call_args.args[0](**add.call_args.kwargs)
        self.assertTrue(result["reordered"])
        self.assertEqual(gm.load_manifest(self.task_id)["playback_order"], [3, 2, 1])
        with patch.object(webui_task._task_manager, "add_task") as add:
            webui_task.submit_scene_reorder(
                self.task_id,
                [2, 1, 3],
                capture_logs=False,
            )
        self.save_order([2, 3, 1])
        result = add.call_args.args[0](**add.call_args.kwargs)
        self.assertIn("has changed", result["error"])
        self.assertEqual(gm.load_manifest(self.task_id)["playback_order"], [2, 3, 1])
        with patch.object(webui_task._task_manager, "add_task") as add:
            webui_task.submit_scene_reorder(self.task_id, [2, 1, 3], capture_logs=False)
        # Inputs disappear after queueing, before the worker's transaction.
        (self.root / "audio.mp3").unlink()
        result = add.call_args.args[0](**add.call_args.kwargs)
        self.assertIn("error", result)
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )
        self.assertEqual((self.root / "final-1.mp4").read_bytes(), b"new final")

    def test_reorder_survives_replacement_restore_regeneration_and_rerender(self):
        self.save_order([2, 3, 1])
        audio = (self.root / "audio.mp3").read_bytes()
        captions = (self.root / "subtitle.srt").read_bytes()
        upload = gm.active_scene_paths(self.task_id)[0]
        provider = FakeLocalVideoProvider()
        with (
            patch.object(
                task, "generate_final_videos", return_value=(["final"], [], [])
            ) as render,
            patch.object(task.local_ai, "prepare_provider", return_value=provider),
        ):
            task.replace_local_ai_scene_clip(self.task_id, 1, Path(upload).read_bytes())
            imported = gm.scene_record(gm.load_manifest(self.task_id), 1)[
                "active_asset"
            ]
            self.assertEqual(
                gm.local_ai_material_records(self.task_id)[2]["provider"],
                "manual_upload",
            )
            task.restore_local_ai_scene_version(
                self.task_id, 1, "generated_ai/scene-001/v001.mp4"
            )
            task.restore_local_ai_scene_version(self.task_id, 1, imported)
            task.regenerate_local_ai_scene(self.task_id, 3, seed=88)
            task.rerender_local_ai_task(self.task_id)
        self.assertEqual(provider.generated_scene_ids, [3])
        self.assertEqual(gm.load_manifest(self.task_id)["playback_order"], [2, 3, 1])
        for call in render.call_args_list:
            self.assertTrue(call.kwargs["reuse_existing_generated_bgm"])
            self.assertEqual(
                [Path(p).parent.name for p in call.args[2]],
                ["scene-002", "scene-003", "scene-001"],
            )
        self.assertEqual((self.root / "audio.mp3").read_bytes(), audio)
        self.assertEqual((self.root / "subtitle.srt").read_bytes(), captions)

    def test_scene_editor_reopens_in_order_and_disables_boundaries_and_busy_controls(
        self,
    ):
        self.save_order([3, 1, 2])
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
st.session_state["scene_editor_task_id"] = "reorder"
"""
        harness += (
            ast.get_source_segment(source, function) + "\n_render_scene_editor()\n"
        )
        app = AppTest.from_string(harness, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertIn("1. Scene 3", app.expander[0].label)
        self.assertTrue(app.button(key="move_scene_-1_reorder_3").disabled)
        self.assertTrue(app.button(key="move_scene_1_reorder_2").disabled)
        with (
            patch.object(webui_task, "submit_scene_reorder") as submit,
            patch("streamlit.rerun"),
        ):
            app.button(key="move_scene_-1_reorder_1").click().run()
        submit.assert_called_once_with("reorder", [1, 3, 2], expected_order=[3, 1, 2])
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        app.run()
        self.assertTrue(
            all(
                button.disabled
                for button in app.button
                if str(button.key).startswith("move_scene_")
            )
        )
