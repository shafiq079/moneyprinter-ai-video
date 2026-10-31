import json
from unittest.mock import patch
import pytest

from app.services import campaigns as c
from test.services import test_content_library as f


@pytest.fixture
def setup():
    for fixture in f.setup_library.__wrapped__():
        with patch.object(c.worker._task_manager, "add_task") as queue:
            fixture.campaign_queue = queue
            with patch.object(c, "_inflight", set()):
                yield fixture


def make(fixture, count=3):
    return c.create(
        "Three practical gardening Shorts, 30 seconds each.",
        count,
        "English",
        fixture.opts
        | {
            "video_subject": "Garden",
            "video_source": "pexels",
            "voice_name": "en-US-AriaNeural-Female",
        },
        [f.YT, f.FB],
    )


def plan(fixture):
    v = make(fixture)
    with patch.object(
        c.llm,
        "generate_json_response",
        return_value={
            "items": [
                {
                    "title": "Garden " + str(i),
                    "script": "Distinct gardening story " + str(i),
                }
                for i in range(3)
            ]
        },
    ):
        c.plan(v["id"])
    return c.get(v["id"])


def approve(fixture):
    v = plan(fixture)
    c.approve(v["id"], True, v["revision"])
    return c.get(v["id"])


def finish(tid, params, *args, **kwargs):
    root = c.Path(c.utils.task_dir(tid))
    root.mkdir(exist_ok=True, parents=True)
    (root / "script.json").write_text(
        json.dumps(
            {"script": params.video_script, "params": params.model_dump(mode="json")}
        )
    )
    (root / "final-1.mp4").write_bytes(b"video-" + tid.encode())
    return {"state": 1}


def test_plan_is_explicit_distinct_encrypted_and_never_generates(setup):
    v = plan(setup)
    assert len(v["items"]) == 3 and all(i["state"] == "planned" for i in v["items"])
    assert b"Distinct gardening" not in c.path(v["id"]).read_bytes()
    setup.campaign_queue.assert_not_called()
    with pytest.raises(ValueError, match="Review"):
        c.approve(v["id"])


def test_stale_review_and_script_edits_require_new_approval(setup):
    v = plan(setup)
    i = v["items"][0]
    c.edit(
        v["id"], i["id"], "Changed topic", "Changed complete narration", v["revision"]
    )
    with pytest.raises(ValueError, match="changed"):
        c.approve(v["id"], True, v["revision"])
    current = c.get(v["id"])
    c.approve(v["id"], True, current["revision"])
    assert sum(i["state"] == "queued" for i in c.get(v["id"])["items"]) == 3
    setup.campaign_queue.assert_called_once()


def test_serial_production_preserves_task_ids_and_disables_legacy_upload(setup):
    v = approve(setup)
    with patch.object(c.worker, "_run_generation", side_effect=finish) as run:
        for item in v["items"]:
            c.run_item(v["id"], item["id"])
    assert all(i["state"] == "generated" for i in c.get(v["id"])["items"])
    assert all(
        call.kwargs["allow_auto_publish"] is False for call in run.call_args_list
    )
    assert len({i["task_id"] for i in c.get(v["id"])["items"]}) == 3
    assert not f.youtube.jobs() and not f.facebook.jobs()


def test_pause_cancel_and_retry_keep_completed_siblings(setup):
    v = approve(setup)
    one, two, three = v["items"]
    c.pause(v["id"], True)
    with patch.object(c.worker, "_run_generation") as run:
        c.run_item(v["id"], one["id"])
        run.assert_not_called()
    c.pause(v["id"], False)
    with patch.object(c.worker, "_run_generation", side_effect=finish):
        c.run_item(v["id"], one["id"])
    with patch.object(c.worker, "_run_generation", return_value={"state": -1}):
        c.run_item(v["id"], two["id"])
    assert c.get(v["id"])["items"][1]["state"] == "attention"
    with pytest.raises(ValueError, match="Stock"):
        c.retry(v["id"], two["id"], True, "resume")
    c.retry(v["id"], two["id"], True, "new")
    current = c.get(v["id"])
    assert current["items"][0]["state"] == "generated"
    assert current["items"][1]["task_id"] != two["task_id"] and current["items"][1][
        "attempts"
    ] == [two["task_id"]]


def test_recovery_never_blindly_restarts_interrupted_generation(setup):
    v = approve(setup)
    item = v["items"][0]
    v["items"][0]["state"] = "generating"
    c.save(v)
    c._inflight.clear()
    c.reconcile(v["id"])
    assert c.get(v["id"])["items"][0]["state"] == "attention"
    assert c.get(v["id"])["items"][0]["task_id"] == item["task_id"]


def test_ready_campaign_videos_feed_unapproved_publishing_batch(setup):
    v = approve(setup)
    with patch.object(c.worker, "_run_generation", side_effect=finish):
        for item in v["items"]:
            c.run_item(v["id"], item["id"])
            f.lib.select_final(item["task_id"], "final-1.mp4", True)
    batch = c.prepare_publishing(v["id"], "now")
    assert len(batch["items"]) == 6 and all(
        i["state"] == "queued" for i in batch["items"]
    )
    assert c.get(v["id"])["batches"] == [batch["id"]]
    setup.enqueue.assert_not_called()
    setup.fb_enqueue.assert_not_called()


def test_invalid_and_duplicate_plan_retains_previous_plan(setup):
    v = plan(setup)
    with patch.object(
        c.llm,
        "generate_json_response",
        return_value={"items": [{"title": "Same", "script": "Same"}] * 3},
    ):
        with pytest.raises(ValueError, match="distinct"):
            c.plan(v["id"])
    assert c.get(v["id"]) == v
    with pytest.raises(ValueError, match="Factual"):
        c.template(v["template"] | {"content_mode": "factual"})
    with pytest.raises(ValueError, match="uploaded"):
        c.template(v["template"] | {"custom_audio_file": "/tmp/reference.wav"})


def test_webui_generation_wrapper_forwards_no_publishing_flag(setup):
    from app.models.schema import VideoParams

    with patch.object(c.worker.tm, "start", return_value={"state": 1}) as start:
        c.worker._run_generation(
            "owned-task",
            VideoParams.model_validate(make(setup)["template"]),
            False,
            allow_auto_publish=False,
        )
    assert start.call_args.kwargs["allow_auto_publish"] is False


def test_failed_pipeline_is_not_success_just_because_a_video_exists(setup):
    v = approve(setup)
    item = v["items"][0]

    def failed(tid, params, *args, **kwargs):
        finish(tid, params)
        return {"state": -1}

    with patch.object(c.worker, "_run_generation", side_effect=failed):
        c.run_item(v["id"], item["id"])
    assert c.get(v["id"])["items"][0]["state"] == "attention"
    c.reconcile(v["id"])
    assert c.get(v["id"])["items"][0]["state"] == "attention"
    with pytest.raises(ValueError, match="Review"):
        c.adopt_final(v["id"], item["id"])
    c.adopt_final(v["id"], item["id"], True)
    assert c.get(v["id"])["items"][0]["state"] == "generated"


def test_completion_receipt_recovers_lost_parent_update(setup):
    v = approve(setup)
    item = v["items"][0]
    with patch.object(c.worker, "_run_generation", side_effect=finish):
        c.run_item(v["id"], item["id"])
    current = c.get(v["id"])
    current["items"][0]["state"] = "generating"
    c.save(current)
    c._inflight.clear()
    c.reconcile(v["id"])
    assert c.get(v["id"])["items"][0]["state"] == "generated"


def test_cancel_intent_is_retained_before_worker_calls_provider(setup):
    v = approve(setup)
    v["items"][0]["state"] = "generating"
    c.save(v)
    with patch.object(c.worker.tm, "request_task_cancellation") as cancel:
        c.cancel_active(v["id"])
    assert c.get(v["id"])["paused"] and c.get(v["id"])["items"][0]["cancel_requested"]
    cancel.assert_called_once_with(v["items"][0]["task_id"])


def test_failed_ai_planning_retains_reviewable_scripts(setup):
    v = plan(setup)
    with patch.object(
        c.llm, "generate_json_response", side_effect=RuntimeError("secret")
    ):
        with pytest.raises(ValueError, match="retained") as error:
            c.plan(v["id"])
    assert "secret" not in str(error.value) and c.get(v["id"]) == v


def test_real_pipeline_guard_blocks_legacy_publishing_even_when_enabled(setup):
    from contextlib import ExitStack
    from unittest.mock import PropertyMock
    from app.models.schema import VideoParams
    from app.services.state import MemoryState

    tm = c.worker.tm
    native = tm.upload_post.upload_post_service
    state = MemoryState()
    with ExitStack() as stack:
        for name, result in [
            ("generate_script", "Approved narration"),
            ("generate_terms", ["garden"]),
            ("save_script_data", None),
            ("generate_audio", ("audio.mp3", 5, object())),
            ("generate_subtitle", "subtitle.srt"),
            ("get_video_materials", ["clip.mp4"]),
            ("generate_final_videos", (["final.mp4"], ["combined.mp4"], [])),
        ]:
            stack.enter_context(patch.object(tm, name, return_value=result))
        stack.enter_context(patch.object(tm.sm, "state", state))
        stack.enter_context(patch.object(native, "is_configured", return_value=True))
        stack.enter_context(
            patch.object(
                type(native),
                "auto_upload",
                new_callable=PropertyMock,
                return_value=True,
            )
        )
        submit = stack.enter_context(patch.object(tm._cross_post_executor, "submit"))
        result = tm.start(
            "campaign-guard",
            VideoParams(video_subject="Garden", voice_name="en-US-AriaNeural-Female"),
            allow_auto_publish=False,
        )
    assert result["videos"] == ["final.mp4"] and result["cross_post_state"] is None
    assert state.get_task("campaign-guard")["state"] == 1
    submit.assert_not_called()


def test_local_resume_uses_saved_context_and_same_task(setup):
    v = plan(setup)
    current = c.get(v["id"])
    current["template"]["video_source"] = "wan22_local"
    c.save(current)
    c.approve(v["id"], True, c.get(v["id"])["revision"])
    v = c.get(v["id"])
    item = v["items"][0]
    current = c.get(v["id"])
    current["items"][0]["state"] = "attention"
    c.save(current)
    params = c.VideoParams.model_validate(
        current["template"]
        | {"video_subject": item["title"], "video_script": item["script"]}
    )
    context = {"params": params, "script": item["script"]}
    c.retry(v["id"], item["id"], True, "resume")
    with (
        patch.object(c.worker.tm, "load_local_ai_resume_context", return_value=context),
        patch.object(c.worker, "_run_generation", side_effect=finish) as run,
    ):
        c.run_item(v["id"], item["id"])
    assert (
        run.call_args.args[0] == item["task_id"]
        and run.call_args.kwargs["resume_context"] is context
    )
    assert c.get(v["id"])["items"][0]["state"] == "generated"


def test_existing_account_plans_are_not_duplicated_when_destinations_expand(setup):
    v = approve(setup)
    with patch.object(c.worker, "_run_generation", side_effect=finish):
        for item in v["items"]:
            c.run_item(v["id"], item["id"])
            f.lib.select_final(item["task_id"], "final-1.mp4", True)
    c.set_destinations(v["id"], [f.YT])
    first = c.prepare_publishing(v["id"], "now")
    c.set_destinations(v["id"], [f.YT, f.FB])
    second = c.prepare_publishing(v["id"], "now")
    assert len(first["items"]) == len(second["items"]) == 3
    assert {i["destination"]["key"] for i in first["items"]} == {f.YT}
    assert {i["destination"]["key"] for i in second["items"]} == {f.FB}


def test_other_worker_ownership_prevents_starting_another_item(setup):
    from filelock import FileLock

    v = approve(setup)
    iid = v["items"][0]["id"]
    current = c.get(v["id"])
    current["items"][0]["state"] = "generating"
    c.save(current)
    c._inflight.clear()
    with FileLock(str(c.path(v["id"])) + "." + iid + ".run.lock", timeout=0):
        c.reconcile(v["id"])
        c.enqueue_next(v["id"])
    assert c.get(v["id"])["items"][0]["state"] == "generating"
    setup.campaign_queue.assert_called_once()


def test_campaign_status_requires_all_current_destinations_to_be_published(setup):
    v = approve(setup)
    tid = v["items"][0]["task_id"]
    current = c.get(v["id"])
    current["items"][0]["state"] = "generated"
    c.save(current)

    def row(key, state):
        return {
            "task_id": tid,
            "state": "submitted",
            "destination": {
                "key": key,
                "platform": key.split(":")[0],
                "name": "Garden",
            },
            "delivery": {"state": state},
        }

    with (
        patch.object(
            c.library, "projects", return_value=[{"task_id": tid, "ready": True}]
        ),
        patch.object(
            c.library,
            "delivery_rows",
            return_value=[row(f.YT, "published"), row(f.YT, "published")],
        ),
    ):
        assert c.progress(v["id"])[0]["display_state"] != "published"
    with patch.object(
        c.library,
        "delivery_rows",
        return_value=[row(f.YT, "published"), row(f.FB, "failed")],
    ):
        assert c.progress(v["id"])[0]["display_state"] == "attention"
    with patch.object(
        c.library,
        "delivery_rows",
        return_value=[row(f.YT, "published"), row(f.FB, "published")],
    ):
        assert c.progress(v["id"])[0]["display_state"] == "published"
