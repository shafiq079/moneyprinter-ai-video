"""Automatic selection reuses the narration-aware planner and saved scene cuts."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import cli
from app.models.schema import VideoAspect, VideoParams
from app.services import generation_manifest as gm, local_ai, scene_planner, task
from app.services.local_ai.fake import FakeLocalVideoProvider
from app.services.state import MemoryState
from test.services.test_local_ai import LocalAITestCase


def test_automatic_uses_model_and_configured_bounds_with_legacy_manual_default():
    for source, maximum in (("wan22_local", 5), ("ltx25_local", 8), ("ltx25_hf", 5)):
        provider = SimpleNamespace(provider_id=source, max_scene_duration=maximum)
        assert local_ai.scene_duration_limit(provider, 2, automatic=True) == maximum
        provider.max_scene_duration = 2.7
        assert local_ai.scene_duration_limit(provider, 2, automatic=True) == 2.7
        assert local_ai.scene_duration_limit(provider, 2) == 2
        local_ai.validate_generation_request(source, generation_mode="fast", aspect="9:16",
                                             clip_duration=999, seed=42, duration_mode="auto")
    params = VideoParams(video_subject="A story")
    assert params.local_ai_duration_mode == "manual"
    with pytest.raises(ValidationError):
        VideoParams(video_subject="A story", local_ai_duration_mode="expert")
    with pytest.raises(local_ai.LocalAICapabilityError, match="duration mode"):
        local_ai.validate_generation_request("ltx25_hf", generation_mode="fast", aspect="9:16",
                                             clip_duration=2, seed=42, duration_mode="expert")
    params = cli.build_video_params(cli.parse_args([
        "--video-subject", "A story", "--video-source", "ltx25_hf",
        "--local-ai-duration-mode", "auto", "--video-clip-duration", "2"]))
    assert params.local_ai_duration_mode == "auto"
    assert VideoParams.model_validate_json(params.model_dump_json()).local_ai_duration_mode == "auto"


def test_automatic_rejects_speed_changes_before_any_provider_or_speech_call():
    params = VideoParams(video_subject="A story", video_source="ltx25_hf",
                         local_ai_duration_mode="auto", video_clip_duration=2, video_clip_speed=1.5)
    with (patch.object(task.sm, "state", MemoryState()),
          patch.object(local_ai, "prepare_provider") as provider,
          patch.object(task.voice, "tts") as speech):
        result = task.start("automatic-invalid-speed", params)
    assert result["failed_stage"] == "preflight"
    provider.assert_not_called()
    speech.assert_not_called()


class TestAutomaticPipeline(LocalAITestCase):
    def test_real_export_and_restart_resume_keep_variable_planned_cuts(self):
        task_id = "automatic-scenes"
        state = MemoryState()
        provider = FakeLocalVideoProvider(fail_scene_ids={2})
        provider.max_scene_duration = 3
        params = VideoParams(video_subject="A garden", video_script="Flowers open. Bees gather pollen. Evening arrives.",
                             video_source=local_ai.FAKE_SOURCE_ID, video_clip_duration=1,
                             local_ai_duration_mode="auto", voice_name="en-US-AriaNeural-Female",
                             subtitle_enabled=False, bgm_type="", n_threads=1)
        def speech(**kwargs):
            assert str(self.make_audio(task_id, 4.2)) == kwargs["voice_file"]
            return object()
        with (patch.dict("os.environ", {"MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER": "1"}),
              patch.object(task.sm, "state", state),
              patch.object(local_ai, "prepare_provider", return_value=provider),
              patch.object(task.voice, "tts", side_effect=speech) as tts,
              patch.object(VideoAspect, "to_resolution", return_value=(90, 160)),
              patch.object(task.material, "download_videos", side_effect=AssertionError("stock")),
              patch.object(task, "_schedule_cross_post", side_effect=AssertionError("publishing"))):
            failed = task.start(task_id, params)
            assert failed["state"] == task.const.TASK_STATE_FAILED
            plan = scene_planner.load_scene_plan(task_id)
            assert len(plan.scenes) == 2  # Manual 1s would require five scenes.
            assert plan.scenes[0].target_duration != plan.scenes[1].target_duration
            assert all(1 < s.target_duration <= 3 for s in plan.scenes)
            assert sum(s.target_duration for s in plan.scenes) == 5
            first_asset = gm.resolve_asset(
                task_id, gm.scene_record(gm.load_manifest(task_id), 1)["active_asset"])
            original = first_asset.read_bytes()
            provider.fail_scene_ids.clear()
            restarted = MemoryState()
            with (patch.object(task.sm, "state", restarted),
                  patch.object(task, "generate_script", side_effect=AssertionError("script")),
                  patch.object(task, "generate_audio", side_effect=AssertionError("TTS")),
                  patch.object(task, "generate_subtitle", side_effect=AssertionError("captions")),
                  patch.object(scene_planner, "get_or_create_scene_plan", side_effect=AssertionError("planner")),
                  patch.object(task.video, "combine_videos", wraps=task.video.combine_videos) as combine):
                context = task.load_local_ai_resume_context(task_id)
                assert context["params"].local_ai_duration_mode == "auto"
                result = task.start(task_id, context["params"], resume_context=context)
            assert restarted.get_task(task_id)["state"] == task.const.TASK_STATE_COMPLETE
            assert provider.generated_scene_ids == [1, 2]
            assert first_asset.read_bytes() == original
            assert combine.call_args.kwargs["scene_durations"] == [s.target_duration for s in plan.scenes]
            assert abs(task.voice.get_audio_duration(result["videos"][0]) - 4.2) < 0.1
            stored = json.loads((self.task_root / task_id / "script.json").read_text())
            assert stored["params"]["local_ai_duration_mode"] == "auto"
            tts.assert_called_once()
            # Render-only reuses exactly the same plan/media and numeric cap 1
            # cannot trim automatically planned scenes back to one second.
            with (patch.object(local_ai, "is_public_source", return_value=True),
                  patch.object(local_ai, "prepare_provider", side_effect=AssertionError("GPU")),
                  patch.object(task.sm, "state", restarted)):
                rerendered = task.rerender_local_ai_task(task_id)
            assert abs(task.voice.get_audio_duration(rerendered["videos"][0]) - 4.2) < 0.1
