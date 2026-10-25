import ast
import json
import subprocess
import wave
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
from streamlit.testing.v1 import AppTest

from app.models import const
from app.models.schema import TaskArtifactPackageData, VideoParams
from app.services import generation_manifest as gm
from app.services import narration_ranges as nr
from app.services import scene_planner, task, task_artifacts, webui_task
from app.services.local_ai import FAKE_SOURCE_ID
from app.services.state import MemoryState
from app.utils import utils
from test.services.test_local_ai import LocalAITestCase


class TestNarrationRanges(LocalAITestCase):
    def setUp(self):
        super().setUp()
        self.task_id = "narration"
        self.root = Path(utils.task_dir(self.task_id))
        self.state = MemoryState()
        self.state_patch = patch.object(task.sm, "state", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.public_patch = patch.object(
            task.local_ai, "is_public_source", return_value=True
        )
        self.public_patch.start()
        self.addCleanup(self.public_patch.stop)
        self.params = VideoParams(
            video_subject="Garden",
            video_script="Flowers. Bees.",
            video_source=FAKE_SOURCE_ID,
            voice_name="en-US-AriaNeural",
            subtitle_enabled=False,
        )
        self.plan = scene_planner.get_or_create_scene_plan(
            self.task_id,
            self.params.video_script,
            audio_duration=3,
            max_scene_duration=2,
            aspect="9:16",
            base_seed=42,
            use_llm=False,
        )
        self.plan = replace(
            self.plan,
            scenes=tuple(
                replace(s, target_duration=d)
                for s, d in zip(self.plan.scenes, [1.0, 2.0])
            ),
        )
        scene_planner.save_scene_plan(self.task_id, self.plan)
        gm.prepare_manifest(
            self.task_id,
            provider_id=FAKE_SOURCE_ID,
            model_fingerprint="fake",
            scenes=list(self.plan.scenes),
        )
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.audio = self.root / "narration.wav"
        subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1:sample_rate=16000",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=2:sample_rate=16000",
                "-filter_complex",
                "[0:a][1:a]concat=n=2:v=0:a=1[out]",
                "-map",
                "[out]",
                "-c:a",
                "pcm_s16le",
                str(self.audio),
            ],
            capture_output=True,
            check=True,
        )
        self.state.update_task(
            self.task_id,
            state=const.TASK_STATE_COMPLETE,
            audio_file=str(self.audio),
            audio_duration=3,
            progress=100,
        )

    def prepare(self):
        return task.prepare_local_ai_narration_ranges(self.task_id)

    def test_real_previews_match_saved_ranges_without_generation(self):
        protected = {
            name: (self.root / name).read_bytes()
            for name in ("script.json", "scene_plan.json")
        }
        manifest = gm.manifest_path(self.task_id).read_bytes()
        audio = self.audio.read_bytes()
        with (
            patch.object(
                task.local_ai, "prepare_provider", side_effect=AssertionError("AI")
            ),
            patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
            patch.object(
                task, "generate_final_videos", side_effect=AssertionError("render")
            ),
            patch.object(
                task, "generate_subtitle", side_effect=AssertionError("caption")
            ),
        ):
            data = self.prepare()
        self.assertFalse(data["speech_aligned"])
        self.assertEqual(data["basis"], "estimated_scene_weights")
        self.assertEqual(
            [(i["start"], i["end"]) for i in data["ranges"]], [(0, 1), (1, 3)]
        )
        for scene_id, frequency, duration in ((1, 440, 1), (2, 880, 2)):
            payload = task.local_ai_narration_preview(self.task_id, scene_id)
            self.assertTrue(nr.preview_is_current(self.task_id, payload))
            with wave.open(BytesIO(payload["audio"])) as clip:
                self.assertAlmostEqual(
                    clip.getnframes() / clip.getframerate(), duration, delta=0.001
                )
                samples = np.frombuffer(clip.readframes(clip.getnframes()), dtype="<i2")
                measured = np.fft.rfftfreq(len(samples), 1 / 16000)[
                    np.abs(np.fft.rfft(samples)).argmax()
                ]
                self.assertAlmostEqual(measured, frequency, delta=2)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(self.audio.read_bytes(), audio)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        self.assertEqual(
            task_artifacts.build_output_package(self.task_id)["narration_ranges"],
            "narration_ranges.json",
        )
        self.assertNotIn(
            str(self.root), (self.root / "narration_ranges.json").read_text()
        )
        package = TaskArtifactPackageData.model_validate(
            task_artifacts.build_output_package(self.task_id)
        )
        self.assertEqual(
            package.model_dump()["narration_ranges"], "narration_ranges.json"
        )

    def test_reopen_and_visual_changes_keep_ranges_and_cached_files(self):
        data = self.prepare()
        original = (self.root / "narration_ranges.json").read_bytes()
        manifest = gm.load_manifest(self.task_id)
        manifest.update(playback_order=[2, 1], playback_durations={"1": 1.5, "2": 1.5})
        gm.save_manifest(self.task_id, manifest)
        changed = replace(
            self.plan,
            scenes=tuple(
                replace(s, prompt="new visual", target_duration=1.5)
                for s in self.plan.scenes
            ),
        )
        scene_planner.save_scene_plan(self.task_id, changed)
        orphan = self.root / "narration_previews" / ("a" * 32)
        orphan.mkdir()
        (orphan / ".decoded.wav").write_bytes(b"interrupted extraction")
        with patch.object(
            nr.subprocess, "run", side_effect=AssertionError("unnecessary extraction")
        ):
            self.assertEqual(nr.prepare(self.task_id, changed, str(self.audio)), data)
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), original)
        self.assertFalse(orphan.exists())
        # A fresh loader uses persisted ranges, independent of process state.
        self.assertEqual(
            nr.load_validated(
                self.task_id,
                scene_planner.load_scene_plan(self.task_id),
                str(self.audio),
            ),
            data,
        )

    def test_source_changes_block_preview_and_explicit_prepare_rebinds(self):
        self.prepare()
        cached = task.local_ai_narration_preview(self.task_id, 1)
        self.audio.write_bytes(self.audio.read_bytes() + b"changed")
        self.assertFalse(nr.preview_is_current(self.task_id, cached))
        with self.assertRaisesRegex(ValueError, "changed"):
            task.local_ai_narration_preview(self.task_id, 1)
        self.prepare()
        script_file = self.root / "script.json"
        script = json.loads(script_file.read_text())
        script["script"] += " Changed."
        script_file.write_text(json.dumps(script))
        with self.assertRaisesRegex(ValueError, "changed"):
            task.local_ai_narration_preview(self.task_id, 1)

    def test_corrupt_preview_recovers_saved_boundaries_and_failed_write_preserves_previous(
        self,
    ):
        data = self.prepare()
        candidate = gm.resolve_asset(self.task_id, data["ranges"][0]["preview_asset"])
        candidate.write_bytes(b"bad")
        original = (self.root / "narration_ranges.json").read_bytes()
        with patch.object(
            nr.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 120)
        ):
            with self.assertRaisesRegex(ValueError, "timed out"):
                self.prepare()
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), original)
        self.assertEqual(len(list((self.root / "narration_previews").iterdir())), 1)
        recovered = self.prepare()
        self.assertEqual(
            [(i["start"], i["end"]) for i in recovered["ranges"]], [(0, 1), (1, 3)]
        )
        self.assertEqual(len(list((self.root / "narration_previews").iterdir())), 1)
        # Rebinding is transactional as well.
        self.audio.write_bytes(self.audio.read_bytes() + b"new")
        before = (self.root / "narration_ranges.json").read_bytes()
        with patch.object(
            nr.scene_planner, "_atomic_write_json", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)

    def test_source_edit_during_decode_does_not_publish_stale_ranges(self):
        self.prepare()
        previous = (self.root / "narration_ranges.json").read_bytes()
        self.audio.write_bytes(self.audio.read_bytes() + b"new version")
        extract = nr._extract

        def changed_during_decode(*args, **kwargs):
            extract(*args, **kwargs)
            self.audio.write_bytes(self.audio.read_bytes() + b"changed again")

        with patch.object(nr, "_extract", side_effect=changed_during_decode):
            with self.assertRaisesRegex(ValueError, "changed during"):
                self.prepare()
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), previous)
        self.assertEqual(len(list((self.root / "narration_previews").iterdir())), 1)

    def test_operator_adjustment_recuts_audio_and_invalidates_both_reviews(self):
        self.prepare()
        protected = {
            name: (self.root / name).read_bytes()
            for name in ("script.json", "scene_plan.json", "narration.wav")
        }
        manifest = gm.manifest_path(self.task_id).read_bytes()
        for scene_id in (1, 2):
            task.edit_local_ai_narration_range(
                self.task_id,
                scene_id,
                expected_revision=nr.revision(self.task_id),
                reviewed=True,
            )
        self.assertEqual(
            nr.read_ranges(self.task_id)["operator_reviewed_scene_ids"], [1, 2]
        )
        with (
            patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
            patch.object(
                task, "generate_final_videos", side_effect=AssertionError("render")
            ),
        ):
            data = task.edit_local_ai_narration_range(
                self.task_id, 1, expected_revision=nr.revision(self.task_id), end=0.75
            )
        self.assertEqual(data["basis"], "operator_adjusted")
        self.assertFalse(data["speech_aligned"])
        self.assertEqual(data["operator_reviewed_scene_ids"], [])
        self.assertEqual(
            [(r["start"], r["end"]) for r in data["ranges"]], [(0, 0.75), (0.75, 3)]
        )
        for scene_id, duration in ((1, 0.75), (2, 2.25)):
            payload = task.local_ai_narration_preview(self.task_id, scene_id)
            with wave.open(BytesIO(payload["audio"])) as audio:
                self.assertEqual(audio.getnframes(), round(duration * 16000))
        self.assertEqual(nr.prepare(self.task_id, self.plan, str(self.audio)), data)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        # Rebinding changed audio must discard review claims from the old source.
        self.audio.write_bytes(self.audio.read_bytes() + b"new source")
        rebuilt = self.prepare()
        self.assertEqual(rebuilt["basis"], "estimated_scene_weights")
        self.assertEqual(rebuilt.get("operator_reviewed_scene_ids", []), [])

    def test_boundary_guards_stale_requests_and_publication_failure_preserve_map(self):
        self.prepare()
        before = (self.root / "narration_ranges.json").read_bytes()
        expected = nr.revision(self.task_id)
        for end in (-1, 3, float("nan"), float("inf"), True, "1"):
            with self.subTest(end=end), self.assertRaises(ValueError):
                task.edit_local_ai_narration_range(
                    self.task_id, 1, expected_revision=expected, end=end
                )
        with self.assertRaises(ValueError):
            task.edit_local_ai_narration_range(
                self.task_id, 2, expected_revision=expected, end=2.5
            )
        with self.assertRaisesRegex(ValueError, "changed"):
            task.edit_local_ai_narration_range(
                self.task_id, 1, expected_revision="stale", end=0.5
            )
        task.edit_local_ai_narration_range(
            self.task_id, 1, expected_revision=expected, end=1
        )
        with patch.object(
            nr.scene_planner, "_atomic_write_json", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                task.edit_local_ai_narration_range(
                    self.task_id, 1, expected_revision=expected, end=0.8
                )
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertEqual(len(list((self.root / "narration_previews").iterdir())), 1)

    def test_range_edit_queue_snapshot_and_stale_worker_restore_status(self):
        self.prepare()
        request = {
            "scene_id": 1,
            "expected_revision": nr.revision(self.task_id),
            "end": 0.8,
        }
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request=request)
        request["end"] = 0.5
        call = queue.call_args
        self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertEqual(nr.read_ranges(self.task_id)["ranges"][0]["end"], 0.8)
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(
                self.task_id,
                edit_request={
                    "scene_id": 1,
                    "expected_revision": nr.revision(self.task_id),
                    "reviewed": True,
                },
            )
        # Simulate an external metadata update after the request was queued.
        data = nr.read_ranges(self.task_id)
        data["operator_reviewed_scene_ids"] = [2]
        (self.root / "narration_ranges.json").write_text(json.dumps(data))
        before = (self.root / "narration_ranges.json").read_bytes()
        call = queue.call_args
        self.assertIn("error", call.args[0](**call.kwargs))
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE
        )

    def test_invalid_boundaries_paths_no_voice_and_busy_fail_safely(self):
        data = self.prepare()
        bad = {**data, "ranges": [dict(item) for item in data["ranges"]]}
        bad["ranges"][0]["end"] = float("nan")
        (self.root / "narration_ranges.json").write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            nr.read_ranges(self.task_id)
        outside = self.task_root / "outside.wav"
        outside.write_bytes(self.audio.read_bytes())
        with self.assertRaisesRegex(ValueError, "task-local"):
            nr.prepare(self.task_id, self.plan, str(outside))
        self.params.voice_name = "no-voice"
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with self.assertRaisesRegex(ValueError, "No Voice"):
            self.prepare()
        self.params.custom_audio_file = "narration.wav"
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        self.prepare()  # Custom recorded audio takes precedence over No Voice.
        self.state.update_task(self.task_id, state=const.TASK_STATE_PROCESSING)
        with self.assertRaises(RuntimeError):
            webui_task.submit_narration_ranges(self.task_id)

    def test_queue_restores_failed_status_and_recovers_scheduling_errors(self):
        self.state.update_task(
            self.task_id,
            state=const.TASK_STATE_FAILED,
            progress=50,
            failed_stage="video",
        )
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id)
        call = queue.call_args
        self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_FAILED
        )
        self.assertEqual(self.state.get_task(self.task_id)["failed_stage"], "video")
        with patch.object(
            webui_task._task_manager, "add_task", side_effect=RuntimeError("queue")
        ):
            with self.assertRaises(RuntimeError):
                webui_task.submit_narration_ranges(self.task_id)
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_FAILED
        )
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id)
        with patch.object(
            task, "prepare_local_ai_narration_ranges", side_effect=ValueError("decode")
        ):
            call = queue.call_args
            self.assertIn("error", call.args[0](**call.kwargs))
        self.assertEqual(
            self.state.get_task(self.task_id)["state"], const.TASK_STATE_FAILED
        )

    def draft_audio(self, seconds=1, frequency=220):
        content = BytesIO()
        with wave.open(content, "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            samples = (np.sin(np.arange(round(seconds * 16000)) * 2 * np.pi * frequency / 16000) * 4000).astype("<i2")
            stream.writeframes(samples.tobytes())
        return content.getvalue()

    def review(self, scene_id=1):
        return task.edit_local_ai_narration_range(
            self.task_id, scene_id, expected_revision=nr.revision(self.task_id), reviewed=True
        )

    def save_draft(self, content=None, scene_id=1):
        return task.replace_local_ai_narration_draft(
            self.task_id, scene_id, expected_revision=nr.revision(self.task_id), content=content
        )

    def test_replacement_draft_audition_persistence_and_original_restore(self):
        self.prepare()
        self.review()
        names = ("script.json", "scene_plan.json", "narration.wav")
        protected = {name: (self.root / name).read_bytes() for name in names}
        manifest = gm.manifest_path(self.task_id).read_bytes()
        original = task.local_ai_narration_preview(self.task_id, 1)
        with (
            patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
            patch.object(task, "generate_final_videos", side_effect=AssertionError("render")),
            patch.object(task, "generate_subtitle", side_effect=AssertionError("caption")),
        ):
            data = self.save_draft(self.draft_audio())
        self.assertEqual(data["operator_reviewed_scene_ids"], [1])
        draft_path = gm.resolve_asset(self.task_id, data["ranges"][0]["replacement"]["preview_asset"])
        self.assertFalse((draft_path.parent / "upload.audio").exists())
        payload = task.local_ai_narration_preview(self.task_id, 1, replacement=True)
        self.assertTrue(payload["replacement"])
        self.assertFalse(nr.preview_is_current(self.task_id, original))
        with wave.open(BytesIO(payload["audio"])) as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
            frequency = np.fft.rfftfreq(len(samples), 1 / 16000)[np.abs(np.fft.rfft(samples)).argmax()]
        self.assertAlmostEqual(frequency, 220, delta=2)
        self.assertEqual(task.local_ai_narration_preview(self.task_id, 1)["audio"], original["audio"])
        # Reopen/reprepare and rebuild a corrupt original preview without losing the draft.
        self.assertEqual(self.prepare(), data)
        gm.resolve_asset(self.task_id, data["ranges"][0]["preview_asset"]).unlink()
        repaired = self.prepare()
        self.assertEqual(repaired["ranges"][0]["replacement"], data["ranges"][0]["replacement"])
        self.assertEqual(task.local_ai_narration_preview(self.task_id, 1, replacement=True)["audio"], payload["audio"])
        self.save_draft(self.draft_audio(frequency=330))
        self.assertFalse(draft_path.exists())
        self.assertEqual(len(list((self.root / "narration_replacements").iterdir())), 1)
        self.save_draft()  # Explicit restore-original removes only the draft.
        self.assertEqual(list((self.root / "narration_replacements").iterdir()), [])
        with self.assertRaisesRegex(ValueError, "no replacement"):
            task.local_ai_narration_preview(self.task_id, 1, replacement=True)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)

    def test_replacement_normalizes_stereo_and_rejects_playlists_before_decode(self):
        self.prepare()
        self.review()
        content = BytesIO()
        with wave.open(content, "wb") as stream:
            stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(48000 * 4))
        self.save_draft(content.getvalue())
        payload = task.local_ai_narration_preview(self.task_id, 1, replacement=True)
        with wave.open(BytesIO(payload["audio"])) as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()), (1, 2, 16000, 16000))
        with patch.object(nr, "_extract", side_effect=AssertionError("untrusted playlist decoder")):
            with self.assertRaisesRegex(ValueError, "audio file"):
                self.save_draft(b"ffconcat version 1.0\nfile '/private/audio.wav'\n")

    def test_replacement_guards_review_duration_staleness_and_atomic_failure(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "review"):
            self.save_draft(self.draft_audio())
        self.review()
        self.save_draft(self.draft_audio())
        before = (self.root / "narration_ranges.json").read_bytes()
        for content in (b"broken", b"", self.draft_audio(0.5), self.draft_audio(1.1), self.draft_audio(1.3), bytearray(b"bad")):
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                self.save_draft(content)
            self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        with patch.object(nr.scene_planner, "_atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.save_draft(self.draft_audio(frequency=330))
            with self.assertRaises(OSError):
                self.save_draft()
        with self.assertRaisesRegex(ValueError, "changed"):
            task.replace_local_ai_narration_draft(self.task_id, 1, expected_revision="old", content=self.draft_audio())
        with self.assertRaisesRegex(ValueError, "remove adjacent"):
            task.edit_local_ai_narration_range(self.task_id, 1, expected_revision=nr.revision(self.task_id), end=0.8)
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertEqual(len(list((self.root / "narration_replacements").iterdir())), 1)
        data = nr.read_ranges(self.task_id)
        gm.resolve_asset(self.task_id, data["ranges"][0]["replacement"]["preview_asset"]).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            task.local_ai_narration_preview(self.task_id, 1, replacement=True)
        task.local_ai_narration_preview(self.task_id, 1)  # Original is still listenable.
        self.save_draft()
        task.edit_local_ai_narration_range(self.task_id, 1, expected_revision=nr.revision(self.task_id), end=0.8)

    def test_replacement_rechecks_revision_after_decode_and_rejects_unsafe_metadata(self):
        self.prepare()
        self.review()
        self.save_draft(self.draft_audio())
        sidecar = self.root / "narration_ranges.json"
        before = sidecar.read_bytes()
        extract = nr._extract
        def change_revision(*args):
            extract(*args)
            sidecar.write_bytes(before + b" ")
        with patch.object(nr, "_extract", side_effect=change_revision):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.save_draft(self.draft_audio())
        self.assertEqual(sidecar.read_bytes(), before + b" ")
        self.assertEqual(len(list((self.root / "narration_replacements").iterdir())), 1)
        with patch.object(nr, "MAX_REPLACEMENT_BYTES", 1):
            with self.assertRaises(ValueError):
                webui_task.submit_narration_ranges(self.task_id, edit_request={
                    "operation": "replacement", "scene_id": 1,
                    "expected_revision": nr.revision(self.task_id), "content": b"large"})
        for asset in ("../outside.wav", "narration.wav", "narration_replacements/" + "a" * 32 + "/scene-002.wav"):
            data = json.loads(before)
            data["ranges"][0]["replacement"]["preview_asset"] = asset
            sidecar.write_text(json.dumps(data))
            with self.subTest(asset=asset), self.assertRaises(ValueError):
                nr.read_ranges(self.task_id)
        sidecar.write_bytes(before)
        task.local_ai_narration_preview(self.task_id, 1, replacement=True)

    def test_replacement_queue_snapshot_status_and_source_change(self):
        self.prepare()
        self.review()
        request = {"operation": "replacement", "scene_id": 1,
                   "expected_revision": nr.revision(self.task_id), "content": self.draft_audio()}
        self.state.update_task(self.task_id, state=const.TASK_STATE_FAILED, progress=50)
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request=request)
        request["content"] = b"mutated"
        call = queue.call_args
        self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_FAILED)
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request={
                "operation": "replacement", "scene_id": 1, "expected_revision": nr.revision(self.task_id)})
        self.audio.write_bytes(self.audio.read_bytes() + b"changed source")
        before = (self.root / "narration_ranges.json").read_bytes()
        call = queue.call_args
        self.assertIn("error", call.args[0](**call.kwargs))
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_FAILED)
        rebuilt = self.prepare()
        self.assertNotIn("replacement", rebuilt["ranges"][0])
        self.assertEqual(list((self.root / "narration_replacements").iterdir()), [])

    def setup_mix(self):
        from app.services.local_ai.fake import FakeLocalVideoProvider
        from app.services.local_ai.orchestrator import generate_scene_materials
        self.prepare()
        self.review()
        self.save_draft(self.draft_audio())
        generate_scene_materials(self.task_id, provider=FakeLocalVideoProvider(), scenes=list(self.plan.scenes))
        self.params.subtitle_enabled = True
        self.params.custom_audio_file = "narration.wav"
        self.params.bgm_type = ""
        self.params.bgm_volume = 0
        self.params.n_threads = 1
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        (self.root / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:03,000\nFlowers. Bees.\n\n")
        return gm.scene_timing_snapshot(gm.load_manifest(self.task_id))

    def apply_mix(self, reset=False):
        return task.apply_local_ai_narration_drafts(self.task_id,
            expected_revision=nr.revision(self.task_id),
            expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)),
            reset=reset, omit_captions=True)

    def test_mix_real_export_uses_replacement_and_preserves_originals(self):
        self.setup_mix()
        protected = {name: (self.root / name).read_bytes() for name in (
            "script.json", "scene_plan.json", "narration.wav", "subtitle.srt")}
        manifest = gm.manifest_path(self.task_id).read_bytes()
        with (patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
              patch.object(task, "generate_subtitle", side_effect=AssertionError("captions")),
              patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("GPU")),
              patch.object(task, "_schedule_cross_post", side_effect=AssertionError("publishing"))):
            result = self.apply_mix()
        self.assertTrue(result["applied"])
        output = self.root / "exported-audio.wav"
        nr._extract(Path(result["videos"][0]), output, 0, 3)
        with wave.open(str(output), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        for start, end, expected in ((0.2, 0.8, 220), (1.2, 2.8, 880)):
            chunk = samples[round(start * 16000):round(end * 16000)]
            frequency = np.fft.rfftfreq(len(chunk), 1 / 16000)[np.abs(np.fft.rfft(chunk)).argmax()]
            self.assertAlmostEqual(frequency, expected, delta=3)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        active = task.narration_mix.resolve(self.task_id, str(self.audio))
        package = task_artifacts.build_output_package(self.task_id)
        self.assertEqual(package["edited_audio"], Path(active).relative_to(self.root).as_posix())
        self.assertTrue(TaskArtifactPackageData.model_validate(package).captions_omitted)
        self.assertIn({"code": "edited_narration_captions_omitted"}, self.state.get_task(self.task_id)["warnings"])
        with self.assertRaisesRegex(ValueError, "restore original"):
            self.save_draft()
        # Restore uses the original source/caption path through the same composer.
        with patch.object(task, "generate_final_videos", return_value=(result["videos"], [], [])) as render:
            self.apply_mix(reset=True)
        self.assertEqual(render.call_args.args[3], str(self.audio))
        self.assertTrue(render.call_args.args[4].endswith("subtitle.srt"))
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        self.assertFalse(Path(active).exists())

    def test_mix_render_and_publication_failures_roll_back_outputs_and_state(self):
        self.setup_mix()
        final = self.root / "final-1.mp4"
        final.write_bytes(b"original final")
        before = nr.revision(self.task_id)
        def failure(*args, **kwargs):
            final.write_bytes(b"partial render")
            raise RuntimeError("render failed")
        with patch.object(task, "generate_final_videos", side_effect=failure):
            with self.assertRaises(RuntimeError):
                self.apply_mix()
        self.assertEqual(final.read_bytes(), b"original final")
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        self.assertEqual(list((self.root / "narration_mixes").iterdir()), [])
        self.assertEqual(nr.revision(self.task_id), before)
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        with patch.object(task.scene_planner, "_atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.apply_mix()
        self.assertEqual(final.read_bytes(), b"original final")
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        with patch.object(task, "generate_final_videos", return_value=([str(final)], [], [])):
            self.apply_mix()
        old = task.narration_mix.file(self.task_id).read_bytes()
        final.write_bytes(b"edited final")
        with patch.object(task, "generate_final_videos", side_effect=failure):
            with self.assertRaises(RuntimeError):
                self.apply_mix(reset=True)
        self.assertEqual(task.narration_mix.file(self.task_id).read_bytes(), old)
        self.assertEqual(final.read_bytes(), b"edited final")
        task.narration_mix.resolve(self.task_id, str(self.audio))
        # A reset can recover invalid active metadata without trusting its paths.
        task.narration_mix.file(self.task_id).write_text("invalid JSON")
        with patch.object(task, "generate_final_videos", return_value=([str(final)], [], [])):
            self.apply_mix(reset=True)
        self.assertFalse(task.narration_mix.file(self.task_id).exists())

    def test_mix_queue_snapshot_captions_guard_and_stale_input_rejection(self):
        snapshot = self.setup_mix()
        request = {"operation": "apply", "expected_revision": nr.revision(self.task_id),
                   "expected_snapshot": snapshot, "omit_captions": True}
        with self.assertRaisesRegex(ValueError, "caption omission"):
            task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id), expected_snapshot=snapshot)
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request=request)
        request["expected_snapshot"]["order"] = [99]
        with patch.object(task, "generate_final_videos", return_value=([], [], [])):
            call = queue.call_args
            self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertTrue(task.narration_mix.file(self.task_id).exists())
        active_data = task.narration_mix.file(self.task_id).read_bytes()
        invalid = json.loads(active_data)
        invalid["audio_asset"] = "../outside.wav"
        task.narration_mix.file(self.task_id).write_text(json.dumps(invalid))
        with self.assertRaisesRegex(ValueError, "invalid edited narration"):
            task.narration_mix.resolve(self.task_id, str(self.audio))
        task.narration_mix.file(self.task_id).write_bytes(active_data)
        self.audio.write_bytes(self.audio.read_bytes() + b"new source")
        with self.assertRaisesRegex(ValueError, "sources changed"):
            task.narration_mix.resolve(self.task_id, str(self.audio))
        with patch.object(task, "generate_final_videos", return_value=([], [], [])):
            self.apply_mix(reset=True)
        self.params.content_mode = "factual"
        self.params.factual_sources = [{"url": "https://example.org", "title": "Source", "excerpt": "Flowers grow in the garden with bees."}]
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with self.assertRaisesRegex(ValueError, "creative"):
            self.apply_mix()

    def transcript(self, text="New flowers."):
        return task.edit_local_ai_draft_transcript(self.task_id, 1,
            expected_revision=nr.revision(self.task_id), text=text)

    def apply_captions(self):
        return task.apply_local_ai_narration_drafts(self.task_id,
            expected_revision=nr.revision(self.task_id),
            expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)),
            rebuild_captions=True, confirm_transcripts=True)

    def test_complete_text_tts_captions_export_and_real_restore(self):
        import av
        self.setup_mix()
        self.review(2)
        self.params.font_name = "MicrosoftYaHeiBold.ttc"
        self.params.font_size = 32
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        protected = {name: (self.root / name).read_bytes() for name in (
            "script.json", "scene_plan.json", "narration.wav", "subtitle.srt")}
        manifest = gm.manifest_path(self.task_id).read_bytes()
        def speech(**kwargs):
            self.assertEqual(kwargs["text"], "New flowers.")
            self.assertEqual(kwargs["voice_volume"], 1)
            Path(kwargs["voice_file"]).write_bytes(self.draft_audio(1.5))
            return object()
        with patch.object(task.voice, "tts", side_effect=speech) as tts:
            data = task.generate_local_ai_narration_draft(self.task_id, 1,
                expected_revision=nr.revision(self.task_id), text="New flowers.", fit_duration=True)
        self.assertEqual(tts.call_count, 1)
        draft = data["ranges"][0]["replacement"]
        self.assertEqual(draft["origin"], "tts")
        self.assertAlmostEqual(draft["fit_ratio"], 1.5)
        self.assertEqual(draft["text"], "New flowers.")
        with wave.open(str(gm.resolve_asset(self.task_id, draft["preview_asset"])), "rb") as audio:
            self.assertEqual(audio.getnframes(), 16000)
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
            frequency = np.fft.rfftfreq(len(samples), 1 / 16000)[np.abs(np.fft.rfft(samples)).argmax()]
            self.assertAlmostEqual(frequency, 220, delta=3)
        self.assertFalse(list(self.root.glob(".narration-tts-*")))
        with (patch.object(task.voice, "tts", side_effect=AssertionError("new TTS")),
              patch.object(task, "generate_subtitle", side_effect=AssertionError("Whisper")),
              patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("GPU")),
              patch.object(task, "_schedule_cross_post", side_effect=AssertionError("publishing")),
              patch.object(task.video, "generate_video", wraps=task.video.generate_video) as render):
            result = self.apply_captions()
        self.assertTrue(render.call_args.kwargs["params"].subtitle_enabled)
        package = task_artifacts.build_output_package(self.task_id)
        package_model = TaskArtifactPackageData.model_validate(package)
        self.assertFalse(package_model.captions_omitted)
        caption_file = self.root / package["edited_captions"]
        self.assertIn("00:00:00,000 --> 00:00:01,000\nNew flowers.", caption_file.read_text())
        self.assertIn("00:00:01,000 --> 00:00:03,000\nBees.", caption_file.read_text())
        edited_script = json.loads((self.root / package["edited_script"]).read_text())
        self.assertEqual(edited_script["script"], "New flowers. Bees.")
        self.assertFalse(edited_script["speech_aligned"])
        # Real output contains visible captions over synthetic colored footage.
        with av.open(result["videos"][0]) as video:
            frame = next(f for f in video.decode(video=0) if f.time >= 0.5)
            pixels = frame.to_ndarray(format="rgb24")
            self.assertGreater(np.all(pixels > 220, axis=2).sum(), 50)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        # Artifact UI offers the actual edited assets as validated downloads.
        ui_source = (Path(__file__).parents[2] / "webui/Main.py").read_text()
        function = next(n for n in ast.parse(ui_source).body if isinstance(n, ast.FunctionDef) and n.name == "_render_artifact_package_view")
        harness = """
import json, hashlib
import streamlit as st
from app.services import generation_manifest, task_artifacts
from app.services import state as sm
from app.utils import utils
def tr(value): return value
st.session_state['artifact_package_task_id'] = 'narration'
"""
        downloads = {}
        def capture(label, data, **kwargs):
            downloads[kwargs["file_name"]] = data
        with patch("streamlit.download_button", side_effect=capture):
            app = AppTest.from_string(harness + ast.get_source_segment(ui_source, function) + "\n_render_artifact_package_view()\n").run()
        self.assertFalse(app.exception)
        self.assertEqual(set(downloads), {"edited-script.json", "edited-captions.srt", "edited-narration.wav"})
        self.assertIn(b"New flowers.", downloads["edited-captions.srt"])
        # Real restore exports original captions/settings and source audio again.
        with patch.object(task.voice, "tts", side_effect=AssertionError("TTS")):
            restored = self.apply_mix(reset=True)
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        extracted = self.root / "restored.wav"
        nr._extract(Path(restored["videos"][0]), extracted, 0, 1)
        with wave.open(str(extracted), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        frequency = np.fft.rfftfreq(len(samples), 1 / 16000)[np.abs(np.fft.rfft(samples)).argmax()]
        self.assertAlmostEqual(frequency, 440, delta=3)
        self.assertNotIn("edited_captions", task_artifacts.build_output_package(self.task_id))
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_complete_caption_review_text_guards_and_publication_rollback(self):
        snapshot = self.setup_mix()
        old_map = (self.root / "narration_ranges.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "confirm"):
            task.apply_local_ai_narration_drafts(self.task_id, expected_revision=nr.revision(self.task_id),
                expected_snapshot=snapshot, rebuild_captions=True)
        with self.assertRaisesRegex(ValueError, "every narration range"):
            self.apply_captions()
        self.review(2)
        with self.assertRaisesRegex(ValueError, "scene narration text"):
            self.apply_captions()
        self.transcript("New flowers.")
        for text in ("", "x" * 2001, "bad\x00text", 1):
            with self.subTest(text=str(text)[:15]), self.assertRaises(ValueError):
                self.transcript(text)
        before = (self.root / "narration_ranges.json").read_bytes()
        with patch.object(task.scene_planner, "_atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.transcript("Another phrase.")
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertNotEqual(old_map, before)
        final = self.root / "final-1.mp4"
        final.write_bytes(b"previous output")
        with patch.object(task, "generate_final_videos", side_effect=RuntimeError("render failed")):
            with self.assertRaises(RuntimeError):
                self.apply_captions()
        self.assertEqual(final.read_bytes(), b"previous output")
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        self.assertEqual(list((self.root / "narration_mixes").iterdir()), [])
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)

    def test_complete_fitting_and_transcripts_preserve_prior_drafts_on_failure(self):
        self.setup_mix()
        before = (self.root / "narration_ranges.json").read_bytes()
        for seconds in (0.4, 2.2):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "tempo fitting"):
                task.replace_local_ai_narration_draft(self.task_id, 1,
                    expected_revision=nr.revision(self.task_id), content=self.draft_audio(seconds),
                    text="New flowers.", fit_duration=True)
            self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        with patch.object(nr, "_fit_audio", side_effect=ValueError("filter failed")):
            with self.assertRaises(ValueError):
                task.replace_local_ai_narration_draft(self.task_id, 1,
                    expected_revision=nr.revision(self.task_id), content=self.draft_audio(1.5),
                    text="New flowers.", fit_duration=True)
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
        self.assertEqual(len(list((self.root / "narration_replacements").iterdir())), 1)
        data = self.transcript("  New\nflowers.  ")
        self.assertEqual(data["ranges"][0]["replacement"]["text"], "New flowers.")
        original = nr.read_ranges(self.task_id)["ranges"][0]["replacement"]["preview_sha256"]
        self.transcript("Fresh [pause: 1s] flowers.")
        self.review(2)
        metadata, directory = task.narration_mix.build(self.task_id, self.plan, str(self.audio), nr.revision(self.task_id), rebuild_captions=True)
        self.assertNotIn("[pause:", (directory / "captions.srt").read_text())
        self.assertIn("[pause:", (directory / "script.json").read_text())
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(nr.read_ranges(self.task_id)["ranges"][0]["replacement"]["preview_sha256"], original)

    def test_complete_tts_queue_stale_requests_failure_and_cleanup(self):
        self.setup_mix()
        request = {"operation": "tts", "scene_id": 1, "expected_revision": nr.revision(self.task_id),
                   "text": "Queued phrase.", "fit_duration": True}
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request=request)
        request["text"] = "Mutated phrase."
        def speech(**kwargs):
            self.assertEqual(kwargs["text"], "Queued phrase.")
            Path(kwargs["voice_file"]).write_bytes(self.draft_audio(1.2))
            return object()
        with patch.object(task.voice, "tts", side_effect=speech):
            call = queue.call_args
            self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertEqual(nr.read_ranges(self.task_id)["ranges"][0]["replacement"]["text"], "Queued phrase.")
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        before = (self.root / "narration_ranges.json").read_bytes()
        for failure in (None, ValueError("private-token")):
            kwargs = {"return_value": None} if failure is None else {"side_effect": failure}
            with patch.object(task.voice, "tts", **kwargs):
                with self.assertRaises(ValueError) as error:
                    task.generate_local_ai_narration_draft(self.task_id, 1,
                        expected_revision=nr.revision(self.task_id), text="New words.")
            self.assertNotIn("private-token", str(error.exception))
            self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before)
            self.assertFalse(list(self.root.glob(".narration-tts-*")))
        def changed(**kwargs):
            Path(kwargs["voice_file"]).write_bytes(self.draft_audio())
            (self.root / "narration_ranges.json").write_bytes(before + b" ")
            return object()
        with patch.object(task.voice, "tts", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                task.generate_local_ai_narration_draft(self.task_id, 1,
                    expected_revision=nr.revision(self.task_id), text="New words.")
        self.assertEqual((self.root / "narration_ranges.json").read_bytes(), before + b" ")
        self.assertFalse(list(self.root.glob(".narration-tts-*")))

    def test_complete_caption_integrity_and_text_snapshot_are_enforced(self):
        self.setup_mix()
        self.review(2)
        self.transcript()
        with patch.object(task, "generate_final_videos", return_value=([], [], [])):
            self.apply_captions()
        sidecar = task.narration_mix.file(self.task_id)
        before = sidecar.read_bytes()
        data = json.loads(before)
        candidate = gm.resolve_asset(self.task_id, data["captions_asset"])
        original_caption = candidate.read_bytes()
        candidate.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "caption/script changed"):
            task.narration_mix.resolve(self.task_id, str(self.audio))
        candidate.write_bytes(original_caption)
        data["script_asset"] = "../outside.json"
        sidecar.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "invalid edited caption/script"):
            task.narration_mix.resolve(self.task_id, str(self.audio))
        sidecar.write_bytes(before)
        ranges = nr.read_ranges(self.task_id)
        ranges["ranges"][0]["replacement"]["text"] = "Changed words."
        (self.root / "narration_ranges.json").write_text(json.dumps(ranges))
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            task.narration_mix.resolve(self.task_id, str(self.audio))

    def natural_draft(self, seconds=0.5, scene_id=1, frequency=220):
        return task.replace_local_ai_narration_draft(self.task_id, scene_id,
            expected_revision=nr.revision(self.task_id), content=self.draft_audio(seconds, frequency),
            text="Natural recording.", natural_duration=True)

    def timeline_preview(self):
        return task.preview_local_ai_narration_timeline(self.task_id, expected_revision=nr.revision(self.task_id))

    def apply_natural(self, preview):
        return task.apply_local_ai_narration_drafts(self.task_id,
            expected_revision=nr.revision(self.task_id),
            expected_snapshot=gm.scene_timing_snapshot(gm.load_manifest(self.task_id)),
            expected_timeline=preview["signature"], rebuild_captions=True, confirm_transcripts=True)

    def test_variable_full_preview_coverage_upload_export_and_restore(self):
        self.setup_mix()
        self.review(2)
        self.natural_draft(1.5)
        def speech(**kwargs):
            Path(kwargs["voice_file"]).write_bytes(self.draft_audio(0.5, 660))
            return object()
        with patch.object(task.voice, "tts", side_effect=speech):
            task.generate_local_ai_narration_draft(self.task_id, 2, expected_revision=nr.revision(self.task_id),
                text="Short bees.", natural_duration=True, fit_duration=False)
        with wave.open(BytesIO(task.local_ai_narration_preview(self.task_id, 1, replacement=True)["audio"])) as clip:
            self.assertEqual(clip.getnframes(), 24000)
        with self.assertRaisesRegex(ValueError, "preview"):
            self.apply_captions()
        preview = self.timeline_preview()
        self.assertEqual(preview["timeline"]["audio_duration"], 2)
        self.assertEqual([(i["start"], i["end"]) for i in preview["timeline"]["segments"]], [(0, 1.5), (1.5, 2)])
        self.assertFalse(preview["covered"])
        self.assertTrue(preview["rows"][0]["needs_footage"])
        with self.assertRaisesRegex(ValueError, "longer valid footage"):
            self.apply_natural(preview)
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        longer = self.root / "longer.mp4"
        subprocess.run([utils.get_ffmpeg_binary(), "-y", "-f", "lavfi", "-i", "color=c=blue:s=90x160:r=30:d=2",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(longer)], capture_output=True, check=True)
        self.params.font_name = "MicrosoftYaHeiBold.ttc"
        self.params.font_size = 32
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("GPU")):
            task.replace_local_ai_scene_clip(self.task_id, 1, longer.read_bytes())
        record = gm.scene_record(gm.load_manifest(self.task_id), 1)
        self.assertGreaterEqual(record["actual_duration"], 1.5)
        self.assertIsNone(task.narration_timeline.load_preview(self.task_id))
        preview = self.timeline_preview()
        self.assertTrue(preview["covered"])
        protected = {name: (self.root / name).read_bytes() for name in ("script.json", "narration.wav", "subtitle.srt", "scene_plan.json")}
        manifest = gm.manifest_path(self.task_id).read_bytes()
        with (patch.object(task.voice, "tts", side_effect=AssertionError("TTS")),
              patch.object(task, "generate_subtitle", side_effect=AssertionError("Whisper")),
              patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("GPU")),
              patch.object(task, "_schedule_cross_post", side_effect=AssertionError("publishing"))):
            result = self.apply_natural(preview)
        self.assertAlmostEqual(task.voice.get_audio_duration(result["videos"][0]), 2, delta=0.05)
        metadata = json.loads(task.narration_mix.file(self.task_id).read_text())
        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["timeline"], preview["timeline"])
        package = task_artifacts.build_output_package(self.task_id)
        self.assertEqual(TaskArtifactPackageData.model_validate(package).edited_audio_duration, 2)
        self.assertIn("00:00:01,500 --> 00:00:02,000\nShort bees.", (self.root / package["edited_captions"]).read_text())
        decoded = self.root / "retimed.wav"
        nr._extract(Path(result["videos"][0]), decoded, 0, 3)
        with wave.open(str(decoded), "rb") as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
        for start, end, expected in ((0.2, 1, 220), (1.6, 1.9, 660)):
            chunk = samples[round(start * 16000):round(end * 16000)]
            frequency = np.fft.rfftfreq(len(chunk), 1 / 16000)[np.abs(np.fft.rfft(chunk)).argmax()]
            self.assertAlmostEqual(frequency, expected, delta=5)
        with patch.object(task.voice, "tts", side_effect=AssertionError("TTS")):
            restored = self.apply_mix(reset=True)
        self.assertAlmostEqual(task.voice.get_audio_duration(restored["videos"][0]), 3, delta=0.05)
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        self.assertEqual(gm.manifest_path(self.task_id).read_bytes(), manifest)
        for name, content in protected.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_variable_longer_total_real_export(self):
        self.setup_mix()
        self.review(2)
        self.transcript()
        self.natural_draft(3, scene_id=2)
        preview = self.timeline_preview()
        self.assertEqual(preview["timeline"]["audio_duration"], 4)
        self.assertFalse(preview["covered"])
        longer = self.root / "longer.mp4"
        subprocess.run([utils.get_ffmpeg_binary(), "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=90x160:r=30:d=3.5", "-c:v", "libx264",
                        "-threads", "1", "-pix_fmt", "yuv420p", str(longer)],
                       capture_output=True, check=True)
        self.params.font_name = "MicrosoftYaHeiBold.ttc"
        self.params.font_size = 32
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with patch.object(task.local_ai, "prepare_provider", side_effect=AssertionError("GPU")):
            task.replace_local_ai_scene_clip(self.task_id, 2, longer.read_bytes())
            preview = self.timeline_preview()
            self.assertTrue(preview["covered"])
            result = self.apply_natural(preview)
        self.assertAlmostEqual(task.voice.get_audio_duration(result["videos"][0]), 4, delta=0.05)
        self.assertEqual(task_artifacts.build_output_package(self.task_id)["edited_audio_duration"], 4)
        # Cached previews are advisory and cannot be edited into a valid lease.
        path = self.root / task.narration_timeline.NAME
        cached = json.loads(path.read_text())
        cached["timeline"]["audio_duration"] = 99
        path.write_text(json.dumps(cached))
        self.assertIsNone(task.narration_timeline.load_preview(self.task_id))

    def test_variable_timewarp_reordered_visuals_and_balanced_timings(self):
        self.prepare()
        self.review()
        self.natural_draft(0.5)
        data = nr.read_ranges(self.task_id)
        manifest = gm.load_manifest(self.task_id)
        manifest.update(playback_order=[2, 1], playback_durations={"1": 1.5, "2": 1.5})
        timeline, durations = task.narration_timeline.visual_durations(data, manifest)
        self.assertEqual(timeline["audio_duration"], 2.5)
        # The original cut at 1.5s is halfway into the second narration segment.
        # After shortening segment one by 0.5s, that cut moves to 1.0s.
        self.assertEqual(durations, {"2": 1, "1": 1.5})
        self.assertEqual(gm.scene_playback_order(manifest), [2, 1])
        self.assertTrue(task.video._scene_duration_covered(31 / 30, 1.03))
        self.assertFalse(task.video._scene_duration_covered(31 / 30, 1.0))
        self.assertFalse(task.video._scene_duration_covered(1.5, 1.4))
        bad = json.loads((self.root / "narration_ranges.json").read_text())
        bad["ranges"][0]["replacement"]["audio_duration"] = float("nan")
        (self.root / "narration_ranges.json").write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            nr.read_ranges(self.task_id)

    def test_variable_stale_media_queue_and_transaction_rollback(self):
        self.setup_mix()
        self.review(2)
        self.natural_draft(0.5)
        request = {"operation": "timeline", "expected_revision": nr.revision(self.task_id)}
        with patch.object(webui_task._task_manager, "add_task") as queue:
            webui_task.submit_narration_ranges(self.task_id, edit_request=request)
        request["expected_revision"] = "mutated"
        call = queue.call_args
        self.assertTrue(call.args[0](**call.kwargs)["prepared"])
        self.assertEqual(self.state.get_task(self.task_id)["state"], const.TASK_STATE_COMPLETE)
        preview = task.narration_timeline.load_preview(self.task_id)
        asset = gm.resolve_asset(self.task_id, gm.scene_record(gm.load_manifest(self.task_id), 1)["active_asset"])
        content = asset.read_bytes()
        asset.write_bytes(content + b"changed media")
        with self.assertRaisesRegex(ValueError, "footage changed"):
            self.apply_natural(preview)
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        asset.write_bytes(content)
        final = self.root / "final-1.mp4"
        final.write_bytes(b"previous final")
        with patch.object(task, "generate_final_videos", side_effect=RuntimeError("render failed")):
            with self.assertRaises(RuntimeError):
                self.apply_natural(preview)
        self.assertEqual(final.read_bytes(), b"previous final")
        self.assertFalse(task.narration_mix.file(self.task_id).exists())
        before = nr.revision(self.task_id)
        with self.assertRaises(ValueError):
            task.replace_local_ai_narration_draft(self.task_id, 1, expected_revision=before,
                content=self.draft_audio(), natural_duration=True, fit_duration=True)
        self.assertEqual(nr.revision(self.task_id), before)
        self.params.video_clip_speed = 1.5
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        with self.assertRaisesRegex(ValueError, "normal visual"):
            self.timeline_preview()

    def test_variable_restart_resume_reuses_audio_caps_and_only_missing_footage(self):
        from app.services.local_ai.fake import FakeLocalVideoProvider
        self.setup_mix()
        self.review(2)
        self.natural_draft(0.5)
        self.params.font_name = "MicrosoftYaHeiBold.ttc"
        self.params.font_size = 32
        task.save_script_data(self.task_id, self.params.video_script, [], self.params)
        preview = self.timeline_preview()
        with patch.object(task, "generate_final_videos", return_value=([], [], [])):
            self.apply_natural(preview)
        old_mix = task.narration_mix.file(self.task_id).read_bytes()
        gm.resolve_asset(self.task_id, gm.scene_record(gm.load_manifest(self.task_id), 2)["active_asset"]).unlink()
        restarted = MemoryState()
        restarted.update_task(self.task_id, state=const.TASK_STATE_FAILED)
        provider = FakeLocalVideoProvider()
        self.public_patch.stop()
        with (patch.object(task.sm, "state", restarted),
              patch.object(task.local_ai, "prepare_provider", return_value=provider),
              patch.object(task, "generate_script", side_effect=AssertionError("script")),
              patch.object(task, "generate_audio", side_effect=AssertionError("TTS")),
              patch.object(task, "generate_subtitle", side_effect=AssertionError("captions")),
              patch.dict("os.environ", {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"})):
            context = task.load_local_ai_resume_context(self.task_id)
            result = task.start(self.task_id, context["params"], resume_context=context)
        self.assertEqual(provider.generated_scene_ids, [2])
        self.assertAlmostEqual(task.voice.get_audio_duration(result["videos"][0]), 2.5, delta=0.05)
        self.assertEqual(task.narration_mix.file(self.task_id).read_bytes(), old_mix)

    def test_variable_scene_editor_preview_and_apply_controls(self):
        self.setup_mix()
        self.review(2)
        self.natural_draft()
        preview = self.timeline_preview()
        source = (Path(__file__).parents[2] / "webui/Main.py").read_text(encoding="utf-8")
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == "_render_scene_editor")
        harness = """
import os
import streamlit as st
from app.services import generation_manifest, scene_planner, webui_task
from app.services import state as sm
from app.services import task as tm
from app.utils import utils
from app.services.local_ai.clip_import import MAX_CLIP_UPLOAD_BYTES
def tr(value): return value
st.session_state['scene_editor_task_id'] = 'narration'
"""
        app = AppTest.from_string(harness + ast.get_source_segment(source, node)
                                  + "\n_render_scene_editor()\n", default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 2)
        self.assertTrue(app.checkbox(key="draft_natural_narration_1").value)
        self.assertTrue(app.checkbox(key="draft_fit_narration_1").disabled)
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="preview_narration_timeline_narration").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "timeline", "expected_revision": nr.revision(self.task_id)})
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="tts_draft_narration_1").click().run()
            request = submit.call_args.kwargs["edit_request"]
            self.assertTrue(request["natural_duration"])
            self.assertFalse(request["fit_duration"])
        app.checkbox(key="mix_confirm_narration").check().run()
        self.assertFalse(app.button(key="apply_narration_mix_narration").disabled)
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="apply_narration_mix_narration").click().run()
            request = submit.call_args.kwargs["edit_request"]
            self.assertEqual(request["expected_timeline"], preview["signature"])
            self.assertTrue(request["rebuild_captions"])
        self.natural_draft(seconds=0.6)
        app.run()
        self.assertTrue(app.button(key="apply_narration_mix_narration").disabled)
        self.assertTrue(any("Timeline Preview Required" in i.value for i in app.info))
        self.assertFalse(app.exception)

    def test_scene_editor_labels_estimates_and_plays_validated_clip(self):
        self.prepare()
        source = (Path(__file__).parents[2] / "webui/Main.py").read_text(
            encoding="utf-8"
        )
        node = next(
            n
            for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name == "_render_scene_editor"
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
    if value == 'Estimated Narration Range': return 'Saved estimated narration {start:.2f}-{end:.2f}'
    return value
st.session_state['scene_editor_task_id'] = 'narration'
"""
        app = AppTest.from_string(
            harness
            + ast.get_source_segment(source, node)
            + "\n_render_scene_editor()\n",
            default_timeout=30,
        ).run()
        self.assertFalse(app.exception)
        self.assertTrue(
            any("Saved estimated narration 0.00-1.00" in c.value for c in app.caption)
        )
        self.assertTrue(app.button(key="apply_narration_boundary_narration_2").disabled)
        self.assertTrue(app.button(key="save_narration_draft_narration_1").disabled)
        self.assertTrue(app.button(key="play_narration_draft_narration_1").disabled)
        with (
            patch.object(webui_task, "submit_narration_ranges") as submit,
            patch("streamlit.rerun"),
        ):
            field = f"narration_end_narration_1_{nr.revision(self.task_id)}"
            app.number_input(key=field).set_value(0.75).run()
            app.button(key="apply_narration_boundary_narration_1").click().run()
            submit.assert_called_once_with(
                self.task_id,
                edit_request={
                    "scene_id": 1,
                    "expected_revision": nr.revision(self.task_id),
                    "end": 0.75,
                },
            )
        app.button(key="play_narration_narration_1").click().run()
        self.assertEqual(len(app.get("audio")), 1)
        app.run()  # Fragment polling must not remove a playing preview.
        self.assertEqual(len(app.get("audio")), 1)
        self.review()
        upload = BytesIO(self.draft_audio())
        upload.size = len(upload.getvalue())
        with (patch("streamlit.file_uploader", side_effect=lambda label, **kwargs: upload
                    if kwargs.get("key", "").startswith("narration_upload_narration_1_") else None),
              patch.object(webui_task, "submit_narration_ranges") as submit,
              patch("streamlit.rerun")):
            app.run()
            app.button(key="save_narration_draft_narration_1").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "replacement", "scene_id": 1, "expected_revision": nr.revision(self.task_id),
                "content": upload.getvalue(), "text": "Flowers.", "fit_duration": True})
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="tts_draft_narration_1").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "tts", "scene_id": 1, "expected_revision": nr.revision(self.task_id),
                "text": "Flowers.", "fit_duration": True})
        self.save_draft(self.draft_audio())
        app.run()
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            key = f"draft_text_narration_1_{nr.revision(self.task_id)}"
            app.text_area(key=key).input("New flowers.").run()
            app.button(key="draft_transcript_narration_1").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "transcript", "scene_id": 1, "expected_revision": nr.revision(self.task_id), "text": "New flowers."})
        app.button(key="play_narration_draft_narration_1").click().run()
        self.assertEqual(len(app.get("audio")), 1)
        self.assertTrue(any("Narration Draft Saved" in c.value for c in app.caption))
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="remove_narration_draft_narration_1").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "replacement", "scene_id": 1, "expected_revision": nr.revision(self.task_id)})
        app.checkbox(key="mix_confirm_narration").check().run()
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="apply_narration_mix_narration").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "apply", "expected_revision": nr.revision(self.task_id),
                "expected_snapshot": gm.scene_timing_snapshot(gm.load_manifest(self.task_id)),
                "reset": False, "omit_captions": False, "rebuild_captions": True,
                "confirm_transcripts": True})
        task.narration_mix.file(self.task_id).write_text("{}")
        app.run()
        self.assertTrue(app.button(key="save_narration_draft_narration_1").disabled)
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="reset_narration_mix_narration").click().run()
            self.assertTrue(submit.call_args.kwargs["edit_request"]["reset"])
        task.narration_mix.file(self.task_id).unlink()
        self.audio.write_bytes(self.audio.read_bytes() + b"changed")
        app.run()
        self.assertEqual(len(app.get("audio")), 0)
        self.assertFalse(app.exception)
