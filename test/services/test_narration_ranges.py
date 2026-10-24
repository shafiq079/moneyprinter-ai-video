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
                "content": upload.getvalue()})
        self.save_draft(self.draft_audio())
        app.run()
        app.button(key="play_narration_draft_narration_1").click().run()
        self.assertEqual(len(app.get("audio")), 1)
        self.assertTrue(any("Narration Draft Saved" in c.value for c in app.caption))
        with patch.object(webui_task, "submit_narration_ranges") as submit, patch("streamlit.rerun"):
            app.button(key="remove_narration_draft_narration_1").click().run()
            submit.assert_called_once_with(self.task_id, edit_request={
                "operation": "replacement", "scene_id": 1, "expected_revision": nr.revision(self.task_id)})
        self.audio.write_bytes(self.audio.read_bytes() + b"changed")
        app.run()
        self.assertEqual(len(app.get("audio")), 0)
        self.assertFalse(app.exception)
