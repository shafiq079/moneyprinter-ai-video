import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import const
from app.services import generation_manifest
from app.services.local_ai import cleanup
from app.services.local_ai.base import SceneSpec
from app.services.state import MemoryState
from app.utils import utils


class LocalAICleanupTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tasks_root = Path(self.temp_dir.name)
        self.state = MemoryState()

        def fake_task_dir(sub_dir: str = "") -> str:
            target = self.tasks_root / sub_dir if sub_dir else self.tasks_root
            target.mkdir(parents=True, exist_ok=True)
            return str(target)

        self.task_dir_patch = patch.object(
            utils,
            "task_dir",
            side_effect=fake_task_dir,
        )
        self.state_patch = patch.object(cleanup.sm, "state", self.state)
        self.task_dir_patch.start()
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def make_manifest(self, task_id: str):
        scene = SceneSpec(
            scene_id=1,
            narration_segment="test",
            prompt="test prompt",
            target_duration=1.0,
            aspect="9:16",
            seed=42,
        )
        return generation_manifest.prepare_manifest(
            task_id,
            provider_id="wan22_local",
            model_fingerprint="test:model",
            scenes=[scene],
            provider_metadata={"model": "test"},
        )

    def write_scene_version(self, task_id: str, version: int) -> Path:
        path = (
            self.tasks_root
            / task_id
            / "generated_ai"
            / "scene-001"
            / f"v{version:03d}.mp4"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"version-{version}".encode("utf-8"))
        return path


class TestLocalAICleanup(LocalAICleanupTestCase):
    def test_cleanup_keeps_active_and_previous_scene_version(self):
        task_id = "cleanup-versions"
        manifest = self.make_manifest(task_id)
        record = generation_manifest.scene_record(manifest, 1)
        for version in (1, 2, 3):
            self.write_scene_version(task_id, version)

        record["versions"] = [
            "generated_ai/scene-001/v001.mp4",
            "generated_ai/scene-001/v002.mp4",
            "generated_ai/scene-001/v003.mp4",
        ]
        record["active_asset"] = "generated_ai/scene-001/v003.mp4"
        record["status"] = "ready"
        record["version_metadata"] = {
            relative: {"scene_id": 1, "seed": index}
            for index, relative in enumerate(record["versions"], start=1)
        }
        generation_manifest.save_manifest(task_id, manifest)

        report = cleanup.cleanup_task_assets(
            task_id,
            policy=cleanup.CleanupPolicy(
                keep_scene_versions=2,
                stale_temp_hours=24,
                completed_task_retention_days=0,
            ),
            dry_run=False,
        )

        self.assertFalse(
            (self.tasks_root / task_id / "generated_ai/scene-001/v001.mp4").exists()
        )
        self.assertTrue(
            (self.tasks_root / task_id / "generated_ai/scene-001/v002.mp4").exists()
        )
        self.assertTrue(
            (self.tasks_root / task_id / "generated_ai/scene-001/v003.mp4").exists()
        )

        after = generation_manifest.load_manifest(task_id)
        after_record = generation_manifest.scene_record(after, 1)
        self.assertEqual(
            after_record["versions"],
            [
                "generated_ai/scene-001/v002.mp4",
                "generated_ai/scene-001/v003.mp4",
            ],
        )
        self.assertEqual(
            after_record["active_asset"],
            "generated_ai/scene-001/v003.mp4",
        )
        self.assertNotIn(
            "generated_ai/scene-001/v001.mp4",
            after_record["version_metadata"],
        )
        self.assertEqual(
            [item.reason for item in report.removed],
            ["old_scene_version"],
        )

    def test_cleanup_never_deletes_restored_active_old_version(self):
        task_id = "cleanup-restored-active"
        manifest = self.make_manifest(task_id)
        record = generation_manifest.scene_record(manifest, 1)
        for version in (1, 2, 3):
            self.write_scene_version(task_id, version)

        record["versions"] = [
            "generated_ai/scene-001/v001.mp4",
            "generated_ai/scene-001/v002.mp4",
            "generated_ai/scene-001/v003.mp4",
        ]
        record["active_asset"] = "generated_ai/scene-001/v001.mp4"
        record["status"] = "ready"
        generation_manifest.save_manifest(task_id, manifest)

        cleanup.cleanup_task_assets(
            task_id,
            policy=cleanup.CleanupPolicy(
                keep_scene_versions=2,
                stale_temp_hours=24,
                completed_task_retention_days=0,
            ),
            dry_run=False,
        )

        self.assertTrue(
            (self.tasks_root / task_id / "generated_ai/scene-001/v001.mp4").exists()
        )
        self.assertTrue(
            (self.tasks_root / task_id / "generated_ai/scene-001/v003.mp4").exists()
        )
        self.assertFalse(
            (self.tasks_root / task_id / "generated_ai/scene-001/v002.mp4").exists()
        )
        after = generation_manifest.load_manifest(task_id)
        record = generation_manifest.scene_record(after, 1)
        self.assertEqual(
            record["active_asset"],
            "generated_ai/scene-001/v001.mp4",
        )

    def test_busy_task_is_skipped_without_touching_temp_files(self):
        task_id = "cleanup-busy"
        temp_file = (
            self.tasks_root
            / task_id
            / "generated_ai"
            / "scene-001"
            / ".v002.partial.mp4"
        )
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_bytes(b"partial")
        old = time.time() - 48 * 3600
        os.utime(temp_file, (old, old))
        self.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=40,
        )

        report = cleanup.cleanup_task_assets(
            task_id,
            policy=cleanup.CleanupPolicy(
                keep_scene_versions=2,
                stale_temp_hours=1,
                completed_task_retention_days=0,
            ),
            dry_run=False,
            now=time.time(),
        )

        self.assertTrue(temp_file.exists())
        self.assertEqual(
            report.skipped_tasks,
            [{"task_id": task_id, "reason": "task_is_busy"}],
        )

    def test_stale_temp_and_unreferenced_scene_files_are_removed(self):
        task_id = "cleanup-stale"
        task_root = self.tasks_root / task_id
        scene_root = task_root / "generated_ai" / "scene-001"
        scene_root.mkdir(parents=True)

        stale_partial = scene_root / ".v004.partial.mp4"
        stale_wan = scene_root / ".v004.wan-raw.mp4"
        stale_ltx = scene_root / ".v004.ltx-raw.mp4"
        unreferenced = scene_root / "v999.mp4"
        fresh_partial = scene_root / ".v005.partial.mp4"
        for candidate in (
            stale_partial,
            stale_wan,
            stale_ltx,
            unreferenced,
            fresh_partial,
        ):
            candidate.write_bytes(b"x")

        now = time.time()
        old = now - 3 * 3600
        for candidate in (stale_partial, stale_wan, stale_ltx, unreferenced):
            os.utime(candidate, (old, old))

        cleanup.cleanup_task_assets(
            task_id,
            policy=cleanup.CleanupPolicy(
                keep_scene_versions=2,
                stale_temp_hours=1,
                completed_task_retention_days=0,
            ),
            dry_run=False,
            now=now,
        )

        for candidate in (stale_partial, stale_wan, stale_ltx, unreferenced):
            self.assertFalse(candidate.exists(), candidate)
        self.assertTrue(fresh_partial.exists())

    def test_completed_task_retention_is_opt_in_and_dry_run_safe(self):
        task_id = "cleanup-completed"
        task_root = self.tasks_root / task_id
        task_root.mkdir()
        final_file = task_root / "final-1.mp4"
        final_file.write_bytes(b"final")
        self.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[str(final_file)],
        )

        now = time.time()
        old = now - 10 * 86400
        os.utime(task_root, (old, old))
        policy = cleanup.CleanupPolicy(
            keep_scene_versions=2,
            stale_temp_hours=24,
            completed_task_retention_days=7,
        )

        dry_report = cleanup.cleanup_local_ai_storage(
            policy=policy,
            dry_run=True,
            task_id=task_id,
            now=now,
        )
        self.assertTrue(task_root.exists())
        self.assertEqual(dry_report.removed_task_count, 1)
        self.assertEqual(
            dry_report.removed[0].reason,
            "expired_completed_task",
        )

        applied = cleanup.cleanup_local_ai_storage(
            policy=policy,
            dry_run=False,
            task_id=task_id,
            now=now,
        )
        self.assertFalse(task_root.exists())
        self.assertIsNone(self.state.get_task(task_id))
        self.assertEqual(applied.removed_task_count, 1)

    def test_zero_task_retention_never_deletes_completed_task(self):
        task_id = "cleanup-retention-disabled"
        task_root = self.tasks_root / task_id
        task_root.mkdir()
        (task_root / "final-1.mp4").write_bytes(b"final")
        old = time.time() - 365 * 86400
        os.utime(task_root, (old, old))

        cleanup.cleanup_local_ai_storage(
            policy=cleanup.CleanupPolicy(
                keep_scene_versions=2,
                stale_temp_hours=24,
                completed_task_retention_days=0,
            ),
            dry_run=False,
            task_id=task_id,
            now=time.time(),
        )

        self.assertTrue(task_root.exists())


if __name__ == "__main__":
    unittest.main()
