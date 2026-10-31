import copy
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams, MaterialInfo
from app.services import campaigns as c, campaign_production as p
from test.services import test_campaigns as f
from test.services.test_webui_youtube_studio import by_key, by_label


@pytest.fixture
def setup():
    yield from f.setup.__wrapped__()


def test_shared_overrides_reset_stale_review_and_immutable_approved_snapshot(setup):
    v = f.plan(setup)
    cid, iid = v["id"], v["items"][0]["id"]
    shared = {
        "params": v["template"]
        | {"font_size": 80, "voice_rate": 1.2, "video_source": "coverr"}
    }
    c.set_settings(cid, shared, v["revision"])
    current = c.get(cid)
    one = current["items"][0]
    assert c.effective(current, one)[1].font_size == 80
    override = {
        "params": c.effective(current, one)[1].model_dump(mode="json")
        | {"font_size": 50, "video_source": "ltx25_hf"}
    }
    c.set_settings(cid, override, current["revision"], iid)
    current = c.get(cid)
    assert c.effective(current, current["items"][0])[1].video_source == "ltx25_hf"
    assert c.effective(current, current["items"][1])[1].video_source == "coverr"
    with pytest.raises(ValueError, match="changed"):
        c.approve(cid, True, v["revision"])
    c.set_settings(cid, None, current["revision"], iid)
    current = c.get(cid)
    assert c.effective(current, current["items"][0])[1].font_size == 80
    c.approve(cid, True, current["revision"])
    approved = c.get(cid)
    assert approved["items"][0]["approved_production"]["params"]["font_size"] == 80
    with pytest.raises(ValueError, match="locked"):
        c.set_settings(cid, shared, approved["revision"])
    with patch.object(c.worker, "_run_generation", side_effect=f.finish) as run:
        c.run_item(cid, iid)
    assert run.call_args.args[1].font_size == 80
    assert run.call_args.args[1].video_source == "coverr"
    assert run.call_args.kwargs["allow_auto_publish"] is False


def test_paid_production_requires_separate_revision_bound_charge_review(setup):
    v = f.plan(setup)
    c.set_settings(
        v["id"],
        {"params": v["template"] | {"video_source": "wavespeed"}},
        v["revision"],
    )
    v = c.get(v["id"])
    with pytest.raises(ValueError, match="charges"):
        c.approve(v["id"], True, v["revision"])
    assert all(i["state"] == "planned" for i in c.get(v["id"])["items"])
    c.approve(v["id"], True, v["revision"], charges_reviewed=True)
    assert (
        c.get(v["id"])["items"][0]["approved_production"]["params"]["video_source"]
        == "wavespeed"
    )


def test_quote_cannot_be_shared_or_used_after_script_change(setup):
    v = f.plan(setup)
    c.set_settings(
        v["id"],
        {
            "params": v["template"] | {"video_source": "loomloom"},
            "quote": {"client_request_id": "shared"},
        },
        v["revision"],
    )
    v = c.get(v["id"])
    assert "quote" not in v["production"]
    with pytest.raises(ValueError, match="own current"):
        c.approve(v["id"], True, v["revision"], charges_reviewed=True)
    package, params = c.effective(v, v["items"][0])
    package["params"] = params.model_dump(mode="json")
    package["quote"] = {"binding": p.script_binding(params), "client_request_id": "one"}
    c.set_settings(v["id"], package, v["revision"], v["items"][0]["id"])
    v = c.get(v["id"])
    c.edit(v["id"], v["items"][0]["id"], "New title", "New script", v["revision"])
    with pytest.raises(ValueError, match="own current"):
        c.approve(v["id"], True, c.get(v["id"])["revision"], charges_reviewed=True)


def test_uploaded_narration_and_reference_are_retained_copied_and_checked(setup):
    tid = "settings-staging"
    source = Path(c.utils.task_dir(tid)) / "custom-audio.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"original narration")
    params = VideoParams(
        video_subject="Garden",
        voice_name="en-US-AriaNeural-Female",
        custom_audio_file=str(source),
    )
    package = p.capture(
        params,
        tid,
        reference=b"reference-wav",
        prompt_audio=b"prompt-wav",
        prompt_text="Example words",
    )
    stored = VideoParams.model_validate(package["params"])
    source.unlink()
    assert p.asset(package["inputs"]["audio"]).read_bytes() == b"original narration"
    prepared = p.worker_inputs(package, stored, "actual-video")
    assert Path(stored.custom_audio_file).parent == Path(
        c.utils.task_dir("actual-video")
    )
    assert Path(stored.custom_audio_file).read_bytes() == b"original narration"
    assert prepared["voxcpm_reference_audio"] == b"reference-wav"
    assert prepared["voxcpm_prompt_text"] == "Example words"
    p.asset(package["inputs"]["audio"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="missing or changed"):
        p.validate_inputs(package, VideoParams.model_validate(package["params"]))


def test_arbitrary_server_files_and_unbound_inputs_are_rejected(setup, tmp_path):
    source = tmp_path / "private.wav"
    source.write_bytes(b"private")
    params = VideoParams(
        video_subject="Garden",
        voice_name="en-US-AriaNeural-Female",
        custom_audio_file=str(source),
    )
    with pytest.raises(ValueError, match="current settings upload"):
        p.capture(params, "settings-staging")
    with pytest.raises(ValueError, match="not been retained"):
        c.create("Garden", 1, "English", {"params": params.model_dump(mode="json")}, [])


def test_local_materials_are_snapshotted_and_not_lost_with_browser(setup):
    source = Path(c.utils.storage_dir("local_videos", create=True)) / "plant.mp4"
    source.write_bytes(b"video-input")
    params = VideoParams(
        video_subject="Garden",
        video_source="local",
        voice_name="no-voice",
        video_materials=[MaterialInfo(provider="local", url=str(source))],
    )
    package = p.capture(params, "staging")
    source.unlink()
    saved = c.create("Garden", 1, "English", package, [])
    assert (
        p.asset(saved["production"]["inputs"]["materials"][0]).read_bytes()
        == b"video-input"
    )


def test_worker_applies_scoped_model_and_encoder_then_restores_operator_config(setup):
    params = VideoParams(video_subject="Garden", voice_name="en-US-AriaNeural-Female")
    package = {
        "params": params.model_dump(mode="json"),
        "runtime": {
            "elevenlabs": {"model_id": "saved-model"},
            "app": {"video_codec": "libx264"},
        },
    }
    before = copy.deepcopy(config.elevenlabs)

    def start(**kwargs):
        assert config.elevenlabs["model_id"] == "saved-model"
        assert config.app["video_codec"] == "libx264"
        assert kwargs["allow_auto_publish"] is False
        return {"state": 1}

    with patch.object(c.worker.tm, "start", side_effect=start):
        c.worker._run_generation(
            "scoped",
            params,
            False,
            allow_auto_publish=False,
            production_package=package,
        )
    assert dict(config.elevenlabs) == before
    with pytest.raises(ValueError, match="runtime option"):
        with p.runtime_options({"runtime": {"app": {"upload_post_auto_upload": True}}}):
            pass


def test_planning_receives_script_requirements_and_language(setup):
    v = f.make(setup, 1)
    c.set_settings(
        v["id"],
        {
            "params": v["template"]
            | {
                "video_script_prompt": "Use short sentences",
                "paragraph_number": 3,
                "video_language": "ur",
            }
        },
        v["revision"],
    )
    with patch.object(
        c.llm,
        "generate_json_response",
        return_value={"items": [{"title": "Garden", "script": "A full script"}]},
    ) as model:
        c.plan(v["id"])
    prompt = model.call_args.args[0]
    assert (
        "Use short sentences" in prompt
        and '"paragraph_number": 3' in prompt
        and '"language": "ur"' in prompt
    )


def test_main_shared_settings_uses_real_controls_and_save_never_generates(setup):
    v = f.make(setup)
    root = Path(__file__).resolve().parents[2]
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.dict(config.app, {"pexels_api_keys": ["test-key"]}),
        patch.object(c.worker.tm, "start") as start,
        patch.object(c.worker, "submit_generation") as submit,
    ):
        app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.query_params.update(view="campaign-settings", campaign=v["id"])
        app.run()
        assert not app.exception
        assert len(app.tabs) >= 4
        voice_widgets = [
            i for i in app.selectbox if str(i.key).startswith("speech_synthesis_select")
        ]
        assert voice_widgets
        by_key(app.slider, "font_size_slider").set_value(80).run()
        by_label(app.button, "Save campaign production settings").click().run()
        assert not app.exception
        assert c.get(v["id"])["template"]["font_size"] == 80
        assert c.get(v["id"])["template"]["video_count"] == 1
        assert c.get(v["id"])["items"] == []
        start.assert_not_called()
        submit.assert_not_called()
        setup.campaign_queue.assert_not_called()


def test_item_settings_round_trip_and_reset_in_real_main_route(setup):
    v = f.plan(setup)
    iid = v["items"][0]["id"]
    root = Path(__file__).resolve().parents[2]
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.dict(config.app, {"pexels_api_keys": ["test-key"]}),
        patch.object(c.worker, "submit_generation") as submit,
    ):
        app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.query_params.update(view="campaign-settings", campaign=v["id"], item=iid)
        app.run()
        assert not app.exception
        by_key(app.slider, "font_size_slider").set_value(90).run()
        by_label(app.button, "Save campaign production settings").click().run()
        assert not app.exception
        current = c.get(v["id"])
        assert current["items"][0]["production"]["params"]["font_size"] == 90
        assert current["template"]["font_size"] != 90
        # Cold editor session restores the exact override; no AI calls or queue work.
        fresh = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        fresh.session_state["ui_language"] = "en"
        fresh.query_params.update(view="campaign-settings", campaign=v["id"], item=iid)
        fresh.run()
        assert not fresh.exception
        assert by_key(fresh.slider, "font_size_slider").value == 90
        by_label(fresh.button, "Back to campaign").click().run()
        assert not fresh.exception
        by_key(fresh.button, "campaign_reset_settings:" + iid).click().run()
        assert not fresh.exception
        assert "production" not in c.get(v["id"])["items"][0]
        submit.assert_not_called()
        setup.campaign_queue.assert_not_called()


def test_individual_quotes_freeze_without_credentials_and_reconstruct_in_worker(setup):
    from app.services import loomloom

    v = f.plan(setup)
    settings = loomloom.LoomLoomSettings(
        base_url="https://example.org",
        api_token="private-test-token",
        market_listing_id="video-listing",
    )
    for n in range(len(v["items"])):
        v = c.get(v["id"])
        item = v["items"][n]
        params = c.effective(v, item)[1].model_copy(
            update={"video_source": "loomloom", "video_language": "en"}
        )
        request = loomloom.LoomLoomConfirmedVideoRequest(
            settings=settings,
            batch=loomloom.LoomLoomVideoBatch(({"prompt": item["script"]},)),
            listing_version_id="quoted-version",
            client_request_id="quote-" + str(n),
        )
        request.validate()
        package = p.capture(params, "quote-staging", request=request)
        import json

        assert "private-test-token" not in json.dumps(package)
        c.set_settings(v["id"], package, v["revision"], item["id"])
    v = c.get(v["id"])
    c.approve(v["id"], True, v["revision"], charges_reviewed=True)
    approved = c.get(v["id"])["items"][0]["approved_production"]
    params = VideoParams.model_validate(approved["params"])
    with patch.object(loomloom, "video_settings_from_mapping", return_value=settings):
        inputs = p.worker_inputs(approved, params, "quoted-video")
    assert inputs["loomloom_video_request"].client_request_id == "quote-0"
    assert inputs["loomloom_video_request"].settings.api_token == "private-test-token"


def test_campaign_model_settings_do_not_mutate_single_generator_defaults(setup):
    v = f.make(setup)
    root = Path(__file__).resolve().parents[2]
    before_ui = copy.deepcopy(config.ui)
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.dict(config.app, {"pexels_api_keys": ["test-key"]}),
    ):
        app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.query_params.update(view="campaign-settings", campaign=v["id"])
        app.run()
        by_key(app.slider, "font_size_slider").set_value(95).run()
        by_label(app.button, "Save campaign production settings").click().run()
        assert not app.exception
        assert config.ui.get("font_size") == before_ui.get("font_size")
        assert c.get(v["id"])["template"]["font_size"] == 95
        # Recreate the generator render with the preserved session backup.
        # AppTest retains stale nodes after a route-changing mid-render rerun.
        home = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        home.session_state["ui_language"] = "en"
        home.session_state["campaign_generator_backup"] = app.session_state[
            "campaign_generator_backup"
        ]
        home.session_state["campaign_generator_widget_backup"] = app.session_state[
            "campaign_generator_widget_backup"
        ]
        home.run()
        assert not home.exception
        assert by_key(home.slider, "font_size_slider").value != 95
        assert config.ui.get("font_size") != 95


def test_retained_uploaded_voice_saves_and_switching_to_tts_removes_it(setup):
    import wave

    source = Path(c.utils.task_dir("upload-settings")) / "recording.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 3200)
    params = VideoParams(
        video_subject="Garden", custom_audio_file=str(source), voice_name=""
    )
    package = p.capture(params, "upload-settings")
    v = c.create("Gardening", 1, "en", package, [])
    root = Path(__file__).resolve().parents[2]
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.dict(config.app, {"pexels_api_keys": ["test-key"]}),
        patch.object(c.worker.tm, "start") as start,
    ):
        app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.query_params.update(view="campaign-settings", campaign=v["id"])
        app.run()
        assert not app.exception
        by_label(app.button, "Save campaign production settings").click().run()
        assert not app.exception
        assert c.get(v["id"])["template"]["custom_audio_file"]
        fresh = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        fresh.session_state["ui_language"] = "en"
        fresh.query_params.update(view="campaign-settings", campaign=v["id"])
        fresh.run()
        assert not fresh.exception
        mode = next(
            x
            for x in fresh.segmented_control
            if str(x.key).startswith("voice_mode_control")
        )
        mode.set_value("tts").run()
        by_label(fresh.button, "Save campaign production settings").click().run()
        assert not fresh.exception
        assert not c.get(v["id"])["template"]["custom_audio_file"]
        start.assert_not_called()


def test_campaign_source_allowlist_covers_the_generator_inventory():
    import ast

    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/Main.py").read_text())
    assignment = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "VIDEO_SOURCE_GROUPS" for t in n.targets
        )
    )
    groups = ast.literal_eval(assignment.value)
    assert p.SOURCES == {source for group in groups.values() for source in group}


def test_oversized_snapshot_does_not_replace_readable_campaign(setup):
    v = f.make(setup)
    changed = copy.deepcopy(v)
    changed["oversized"] = "x" * 1_500_000
    with pytest.raises(ValueError, match="too large"):
        c.save(changed)
    assert c.get(v["id"]) == v


def test_replanning_cannot_silently_drop_individual_settings_or_quotes(setup):
    v = f.plan(setup)
    package, params = c.effective(v, v["items"][0])
    package["params"] = params.model_dump(mode="json")
    c.set_settings(v["id"], package, v["revision"], v["items"][0]["id"])
    current = c.get(v["id"])
    with patch.object(c.llm, "generate_json_response") as model:
        with pytest.raises(ValueError, match="Reset per-video overrides"):
            c.plan(v["id"])
        model.assert_not_called()
    assert c.get(v["id"]) == current
