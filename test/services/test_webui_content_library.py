from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.services import content_library as lib
from test.services import test_content_library as fixture
from test.services.test_webui_youtube_studio import by_key, by_label

SOURCE = 'from webui.publishing_planner import render_library, render_publishing\nimport streamlit as st\n(render_publishing if st.query_params.get("view")=="publishing" else render_library)(lambda key:key)'


@pytest.fixture
def setup_library():
    yield from fixture.setup_library.__wrapped__()


def app(view="library", bid=None):
    value = AppTest.from_string(SOURCE, default_timeout=30)
    value.query_params["view"] = view
    if bid:
        value.query_params["batch"] = bid
    return value.run()


def test_library_original_review_and_select_five_for_two_accounts(setup_library):
    f = setup_library
    value = app()
    assert not value.exception
    assert "Content Library" in [t.value for t in value.title]
    tid = f.tasks_ids[0]
    by_key(value.checkbox, "library_review:" + tid + ":final-1.mp4:0").check().run()
    by_key(value.button, "library_save:" + tid).click().run()
    assert not value.exception and lib.catalog()["finals"][tid]["ready"]
    for task in f.tasks_ids[1:]:
        lib.select_final(task, "final-1.mp4", True)
    value.run()
    by_key(value.multiselect, "library_batch_videos").set_value(f.tasks_ids)
    by_key(value.multiselect, "library_batch_accounts").set_value(
        [fixture.YT, fixture.FB]
    )
    by_key(value.button, "library_prepare").click().run()
    assert not value.exception
    assert value.query_params["view"] == ["publishing"]
    assert len(lib.batches()[0]["items"]) == 10
    assert not fixture.youtube.jobs() and not fixture.facebook.jobs()
    f.enqueue.assert_not_called()
    f.fb_enqueue.assert_not_called()


def test_batch_review_edit_and_approval_survive_reload(setup_library):
    value = fixture.prepare(setup_library, [fixture.YT])
    bid = value["id"]
    item = value["items"][0]
    page = app("publishing", bid)
    assert not page.exception
    assert by_key(page.button, "planner_approve:" + bid).disabled
    by_key(page.text_input, "planner_fields:" + item["id"] + ":title").set_value(
        "Reviewed title"
    )
    by_label(page.button, "Save draft changes").click().run()
    assert not page.exception
    current = lib.batch(bid)
    assert current["items"][0]["options"]["title"] == "Reviewed title"
    fresh = app("publishing", bid)
    by_key(
        fresh.checkbox, "planner_approve_check:" + bid + ":" + str(current["revision"])
    ).check().run()
    by_key(fresh.button, "planner_approve:" + bid).click().run()
    assert not fresh.exception
    assert all(j["state"] == "queued" for j in fixture.youtube.jobs())
    assert all(i["state"] == "submitted" for i in lib.batch(bid)["items"])


def test_account_defaults_and_automatic_preparation_are_explicit(setup_library):
    page = app("publishing")
    assert not page.exception
    key = fixture.YT
    by_key(page.text_input, "preset_times:" + key).set_value("10:30, 18:30")
    by_key(page.checkbox, "preset_review:" + key).check()
    by_label(page.button, "Save posting defaults").click().run()
    assert not page.exception
    assert lib.catalog()["presets"][key]["times"] == ["10:30", "18:30"]
    assert not lib.catalog()["auto_prepare"]
    by_key(page.checkbox, "planner_auto_prepare").check().run()
    by_key(page.button, "planner_save_auto").click().run()
    assert not page.exception and lib.catalog()["auto_prepare"]
    assert lib.catalog()["auto"] and not fixture.youtube.jobs()


def test_prepared_error_rows_can_be_excluded_without_affecting_other_platform(
    setup_library,
):
    value = fixture.prepare(setup_library)
    fb_item = next(i for i in value["items"] if i["destination"]["key"] == fixture.FB)
    page = app("publishing", value["id"])
    by_key(page.selectbox, "planner_item:" + value["id"]).set_value(fb_item["id"]).run()
    by_key(page.button, "planner_exclude:" + fb_item["id"]).click().run()
    assert not page.exception
    assert lib.batch(value["id"])["items"][5]["state"] == "excluded"
    assert fixture.facebook.get(fb_item["delivery_id"])["state"] == "cancelled"
    assert all(j["state"] == "draft" for j in fixture.youtube.jobs())


def test_main_routes_library_and_publishing(setup_library):
    root = Path(__file__).resolve().parents[2]
    for route, title in [("library", "Content Library"), ("publishing", "Publishing")]:
        value = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
        value.query_params["view"] = route
        value.run()
        assert not value.exception and title in [t.value for t in value.title]


def test_select_all_and_native_editor_handoff_are_available(setup_library):
    from unittest.mock import patch

    fixture.ready(setup_library)
    with patch.dict("os.environ", {"MPT_OPENCUT": "1"}):
        page = app()
        assert not page.exception
        urls = [element.proto.url for element in page.get("link_button")]
        assert any(url.startswith("/opencut/#token=") for url in urls)
        by_key(page.button, "library_select_all").click().run()
        assert set(by_key(page.multiselect, "library_batch_videos").value) == set(
            setup_library.tasks_ids
        )


def test_planner_labels_exist_in_english_and_chinese():
    import ast
    import json

    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/publishing_planner.py").read_text())
    keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "tr"
        and n.args
        and isinstance(n.args[0], ast.Constant)
    }
    for language in ["en", "zh"]:
        assert (
            keys
            <= json.loads((root / "webui/i18n" / f"{language}.json").read_text())[
                "Translation"
            ].keys()
        )
