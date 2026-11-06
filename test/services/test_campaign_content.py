"""Offline contracts for pre-creation content and stable browser-session cards."""

import copy
import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import campaign_content as content, campaigns as c
from test.services import test_campaigns as f
from test.services.test_webui_youtube_studio import by_key
from webui import campaign_composer as ui


@pytest.fixture
def setup():
    yield from f.setup.__wrapped__()


def row(i=1, **kwargs):
    return dict(id=f"{i:032x}", title="", script="", keywords=[]) | kwargs


def generated(i=1):
    return row(
        i, title=f"Garden {i}", script=f"Plant garden {i}", keywords=[f"plant {i}"]
    )


def test_partial_fill_preserves_manual_content_and_supplies_writing_context():
    original = [
        row(title="My subject", script="My exact narration", keywords=[]),
        row(2),
    ]
    before = copy.deepcopy(original)
    with patch.object(
        content.llm,
        "generate_json_response",
        return_value={"items": [generated(), generated(2)]},
    ) as model:
        result = content.generate(
            "Garden campaign", "Urdu", {"paragraph_number": 3}, original
        )
    assert original == before
    assert (
        result[0]["title"] == "My subject"
        and result[0]["script"] == "My exact narration"
    )
    assert result[0]["keywords"] == ["plant 1"]
    data = json.loads(model.call_args.args[0].split("CAMPAIGN_DATA:\n")[1])
    assert data["targets"][original[0]["id"]] == ["keywords"]
    assert (
        data["writing_defaults"]["paragraph_number"] == 3 and data["language"] == "Urdu"
    )


def test_complete_cards_do_not_call_model_and_selected_replace_is_scoped():
    values = [generated(), generated(2)]
    with patch.object(content.llm, "generate_json_response") as model:
        assert content.generate("Garden", "English", {}, values) == values
        model.assert_not_called()
    replacement = generated() | {"title": "Replacement", "script": "New narration"}
    with patch.object(
        content.llm, "generate_json_response", return_value={"items": [replacement]}
    ):
        result = content.generate(
            "Garden", "English", {}, values, replace=True, selected=[values[0]["id"]]
        )
    assert result == [replacement, values[1]] and values[0]["title"] == "Garden 1"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": [{"id": []}, generated(2)]},
        {"items": []},
        {"items": [generated(3)]},
        {"items": [generated(), generated()]},
        {"items": [generated() | {"script": ""}, generated(2)]},
        {"items": [generated(), generated(2) | {"title": "Garden 1"}]},
        {"items": [generated(), generated(2) | {"keywords": [42]}]},
    ],
)
def test_malformed_ai_is_atomic(payload):
    values = [row(), row(2)]
    before = copy.deepcopy(values)
    with (
        patch.object(content.llm, "generate_json_response", return_value=payload),
        pytest.raises(ValueError),
    ):
        content.generate("Garden", "English", {}, values)
    assert values == before


def test_provider_failure_retains_original():
    values = [row()]
    with (
        patch.object(
            content.llm, "generate_json_response", side_effect=RuntimeError("secret")
        ),
        pytest.raises(ValueError, match="retained") as error,
    ):
        content.generate("Garden", "English", {}, values)
    assert "secret" not in str(error.value) and values == [row()]


def test_create_is_atomic_and_keywords_are_individual_and_frozen(setup):
    settings = setup.opts | {
        "video_subject": "Campaign",
        "voice_name": "en-US-AriaNeural-Female",
        "video_source": "pexels",
        "video_terms": ["shared wrong"],
    }
    with patch.object(
        content.llm,
        "generate_json_response",
        side_effect=AssertionError("unexpected AI"),
    ):
        with pytest.raises(ValueError):
            c.create("Garden", 2, "English", settings, [], items=[generated(), row(2)])
        assert not c.all_campaigns()
        value = c.create(
            "Garden", 2, "English", settings, [], items=[generated(), generated(2)]
        )
    assert value["template"]["video_terms"] is None
    assert c.effective(value, value["items"][0])[1].video_terms == ["plant 1"]
    assert c.effective(value, value["items"][1])[1].video_terms == ["plant 2"]
    setup.campaign_queue.assert_not_called()
    c.approve(value["id"], True, value["revision"])
    approved = c.get(value["id"])
    assert approved["items"][0]["approved_production"]["params"]["video_terms"] == [
        "plant 1"
    ]
    with pytest.raises(ValueError):
        c.edit(
            value["id"],
            value["items"][0]["id"],
            "Edit",
            "changed",
            approved["revision"],
            keywords="other",
        )


def test_legacy_shared_keywords_do_not_leak_but_approved_snapshot_survives(setup):
    value = f.plan(setup)
    value["template"]["video_terms"] = ["legacy shared"]
    item = value["items"][0]
    assert c.effective(value, item)[1].video_terms == []
    item["approved_production"] = {
        "params": value["template"] | {"video_terms": ["old approved"]}
    }
    assert c.effective(value, item)[1].video_terms == ["old approved"]


SOURCE = """from webui.campaign_composer import render, render_count
render_count(lambda s:s)
render(lambda s:s, "Garden", "English", {})"""


def test_cards_keep_ids_and_edits_through_add_remove_and_resize():
    app = AppTest.from_string(SOURCE).run()
    first = app.session_state[ui.STATE][0]
    by_key(app.text_input, ui.key(first, "title")).set_value("Keep my subject").run()
    by_key(app.button, "campaign_add_video").click().run()
    second = app.session_state[ui.STATE][1]
    by_key(app.text_input, ui.key(second, "title")).set_value("Second subject").run()
    by_key(app.number_input, "campaign_count").set_value(1).run()
    assert len(app.session_state[ui.STATE]) == 2
    by_key(app.checkbox, "campaign_confirm_resize").check().run()
    by_key(app.button, "campaign_apply_count").click().run()
    assert app.session_state[ui.STATE][0]["id"] == first["id"]
    assert by_key(app.text_input, ui.key(first, "title")).value == "Keep my subject"
    by_key(app.button, "campaign_add_video").click().run()
    second = app.session_state[ui.STATE][1]
    by_key(app.checkbox, "campaign_confirm_remove:" + first["id"]).check().run()
    by_key(app.button, "campaign_card_remove:" + first["id"]).click().run()
    assert not app.exception
    assert app.session_state[ui.STATE][0]["id"] == second["id"]


def test_per_card_ai_never_mutates_previous_rendered_widgets():
    app = AppTest.from_string(SOURCE).run()
    by_key(app.button, "campaign_add_video").click().run()
    first, second = app.session_state[ui.STATE]
    by_key(app.text_input, ui.key(first, "title")).set_value("Manual").run()
    by_key(app.text_area, ui.key(first, "keywords")).set_value("my, keywords").run()
    with patch.object(
        content.llm,
        "generate_json_response",
        return_value={"items": [generated() | {"id": second["id"]}]},
    ):
        by_key(app.button, "campaign_card_generate:" + second["id"]).click().run()
    assert not app.exception
    assert by_key(app.text_input, ui.key(first, "title")).value == "Manual"
    assert by_key(app.text_area, ui.key(first, "keywords")).value == "my, keywords"
    assert by_key(app.button, "campaign_card_regenerate:" + second["id"]).disabled


@pytest.mark.parametrize(
    ("error_kind", "expected"),
    [("rate", "HTTP 429"), ("timeout", "timed out"), ("json", "invalid JSON")],
)
def test_bulk_request_explains_failures_without_leaking_provider_body(
    error_kind, expected
):
    import httpx
    from openai import APITimeoutError, RateLimitError

    request = httpx.Request("POST", "https://example.invalid")
    errors = {
        "rate": RateLimitError(
            "private provider body",
            response=httpx.Response(429, request=request),
            body=None,
        ),
        "timeout": APITimeoutError(request),
        "json": content.llm.InvalidJSONResponse("private provider body"),
    }
    values = [row(), row(2)]
    before = copy.deepcopy(values)
    with (
        patch.object(
            content.llm, "generate_json_response", side_effect=errors[error_kind]
        ) as model,
        pytest.raises(ValueError, match=expected) as failure,
    ):
        content.generate("Garden", "English", {}, values)
    model.assert_called_once()
    assert model.call_args.kwargs["raise_provider_errors"] is True
    assert model.call_args.kwargs["stream_response"] is True
    assert model.call_args.kwargs["max_retries"] == 0
    assert "private provider body" not in str(failure.value)
    assert values == before
