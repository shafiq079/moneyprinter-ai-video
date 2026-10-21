import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task_artifacts


class TestTaskArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temp_dir.name)
        self.task_dir_patch = patch(
            "app.services.task_artifacts.utils.task_dir",
            return_value=str(self.task_dir),
        )
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_patch_preserves_existing_script_fields(self):
        """补充素材来源时不能覆盖历史任务恢复依赖的文案、关键词和参数。"""
        original = {
            "script": "existing script",
            "search_terms": ["nature"],
            "params": {"video_source": "pixabay"},
        }
        task_artifacts.write_script_data("task-1", original)

        updated = task_artifacts.patch_script_data(
            "task-1",
            material_sources=[
                {
                    "provider": "pixabay",
                    "asset_id": "123",
                    "local_file": "vid-123.mp4",
                }
            ],
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertTrue(updated)
        self.assertEqual(payload["script"], original["script"])
        self.assertEqual(payload["search_terms"], original["search_terms"])
        self.assertEqual(payload["params"], original["params"])
        self.assertEqual(payload["material_sources"][0]["asset_id"], "123")
        self.assertEqual(list(self.task_dir.glob(".script.json.*.tmp")), [])

    def test_write_script_data_serializes_video_params(self):
        """原子写入替换旧实现后，仍需完整兼容任务主流程传入的 Pydantic 参数。"""
        params = VideoParams(
            video_subject="test subject",
            video_terms=["city", "night"],
        )

        task_artifacts.write_script_data(
            "task-params",
            {
                "script": "test script",
                "search_terms": ["city"],
                "params": params,
            },
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertEqual(payload["params"]["video_subject"], "test subject")
        self.assertEqual(payload["params"]["video_terms"], ["city", "night"])
        self.assertEqual(payload["params"]["video_source"], "pexels")

    def test_output_package_uses_task_relative_current_artifacts(self):
        (self.task_dir / "generated_ai" / "scene-001").mkdir(parents=True)
        for relative, payload in (
            ("script.json", b"{}"),
            ("subtitle.srt", b"subtitle"),
            ("audio.mp3", b"audio"),
            ("scene_plan.json", b"{}"),
            ("generated_ai/generation_manifest.json", b"{}"),
            ("generated_ai/scene-001/v002.mp4", b"scene"),
            ("final-1.mp4", b"final"),
            ("combined-1.mp4", b"combined"),
        ):
            target = self.task_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        task_state = {
            "videos": [str(self.task_dir / "final-1.mp4")],
            "combined_videos": [str(self.task_dir / "combined-1.mp4")],
            "subtitle_path": str(self.task_dir / "subtitle.srt"),
            "audio_file": str(self.task_dir / "audio.mp3"),
        }
        with patch(
            "app.services.generation_manifest.local_ai_material_records",
            return_value=[
                {
                    "scene_id": 1,
                    "asset": "generated_ai/scene-001/v002.mp4",
                }
            ],
        ):
            package = task_artifacts.build_output_package(
                "task-package",
                task_state=task_state,
            )

        self.assertEqual(package["schema_version"], 1)
        self.assertEqual(package["task_id"], "task-package")
        self.assertEqual(package["final_videos"], ["final-1.mp4"])
        self.assertEqual(package["combined_videos"], ["combined-1.mp4"])
        self.assertEqual(package["script"], "script.json")
        self.assertEqual(package["captions"], "subtitle.srt")
        self.assertEqual(package["audio"], "audio.mp3")
        self.assertEqual(package["scene_plan"], "scene_plan.json")
        self.assertEqual(
            package["generation_manifest"],
            "generated_ai/generation_manifest.json",
        )
        self.assertEqual(
            package["scene_materials"],
            ["generated_ai/scene-001/v002.mp4"],
        )
        self.assertNotIn(
            str(self.task_dir),
            json.dumps(package),
        )

    def test_output_package_drops_outside_paths_and_discovers_final_video(self):
        (self.task_dir / "final-1.mp4").write_bytes(b"final")
        outside = (
            Path(self.temp_dir.name).parent
            / f"{self.task_dir.name}-outside-final.mp4"
        )
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink, missing_ok=True)

        package = task_artifacts.build_output_package(
            "task-safe-package",
            task_state={"videos": [str(outside)]},
        )

        self.assertEqual(package["final_videos"], ["final-1.mp4"])
        self.assertIsNone(package["captions"])
        self.assertIsNone(package["scene_plan"])
        self.assertEqual(package["scene_materials"], [])

    def test_local_ai_output_package_requires_plan_and_manifest(self):
        (self.task_dir / "scene_plan.json").write_text("{}", encoding="utf-8")
        self.assertFalse(
            task_artifacts.has_local_ai_output_package("task-package")
        )

        manifest = self.task_dir / "generated_ai" / "generation_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}", encoding="utf-8")
        self.assertTrue(
            task_artifacts.has_local_ai_output_package("task-package")
        )

    def test_patch_missing_script_is_non_blocking(self):
        """独立调用素材下载时没有任务清单，应静默跳过而不是创建残缺 JSON。"""
        updated = task_artifacts.patch_script_data(
            "standalone",
            material_sources=[],
        )

        self.assertFalse(updated)
        self.assertFalse((self.task_dir / "script.json").exists())

    def test_patch_invalid_script_returns_false_without_overwrite(self):
        """历史 JSON 损坏时必须保留原文件、记录错误，并允许视频主流程继续。"""
        target = self.task_dir / "script.json"
        target.write_text("{invalid-json", encoding="utf-8")

        with patch.object(task_artifacts.logger, "warning") as warning:
            updated = task_artifacts.patch_script_data(
                "task-1",
                material_sources=[],
            )

        self.assertFalse(updated)
        self.assertEqual(target.read_text(encoding="utf-8"), "{invalid-json")
        self.assertTrue(warning.called)


if __name__ == "__main__":
    unittest.main()
