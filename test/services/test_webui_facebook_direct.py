from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import facebook_accounts as accounts, facebook_direct as studio
from app.services.facebook_graph import FacebookPage
from test.services import test_facebook_direct as fixtures
from test.services.test_webui_youtube_studio import by_key, by_label

SOURCE = "from webui.social_dashboard import render\nrender(lambda key: key)"


@pytest.fixture
def facebook_setup():
    yield from fixtures.facebook_setup.__wrapped__()


def app():
    value = AppTest.from_string(SOURCE, default_timeout=30)
    value.query_params["view"] = "social"
    value.query_params["platform"] = "facebook"
    return value.run()


def test_facebook_routing_render_reload_connect_never_publishes(facebook_setup):
    value = app()
    assert not value.exception
    assert by_key(value.radio, "social_platform").value == "Facebook"
    assert [t.label for t in value.tabs] == [
        "Accounts",
        "Content",
        "Create post",
        "Calendar / Queue",
        "Legacy publishing",
    ]
    by_key(value.button, "meta_connect").click().run()
    assert (
        "/social/facebook/oauth/start?ticket="
        in value.session_state["meta_connect_url"]
    )
    value.run()
    assert not value.exception and not studio.jobs()
    facebook_setup.fb_enqueue.assert_not_called()
    by_key(value.radio, "social_platform").set_value("YouTube").run()
    assert not value.exception
    assert by_key(value.button, "social_connect")


def test_facebook_prepare_review_and_restore_after_reload(facebook_setup):
    value = app()
    by_label(value.button, "Prepare for review").click().run()
    assert not value.exception
    job = studio.jobs()[0]
    assert job["state"] == "draft"
    assert by_key(value.button, "meta_compose:approve:" + job["id"]).disabled
    fresh = app()
    assert not fresh.exception
    by_key(fresh.checkbox, "meta_history:review:" + job["id"]).check().run()
    by_key(fresh.button, "meta_history:approve:" + job["id"]).click().run()
    assert not fresh.exception and studio.get(job["id"])["state"] == "queued"
    facebook_setup.fb_enqueue.assert_called()


def test_meta_setup_is_saved_encrypted_without_upload_post_or_network(facebook_setup):
    data = accounts.vault()
    data["settings"] = {}
    data["grants"] = {}
    data["connections"] = {}
    accounts.save(data)
    value = app()
    by_key(value.text_input, "meta_app_id").set_value("123456")
    by_key(value.text_input, "meta_app_secret").set_value("new-meta-secret")
    by_key(value.text_input, "meta_callback").set_value(
        "http://127.0.0.1:8501" + accounts.CALLBACK
    )
    by_label(value.button, "Save Meta application").click().run()
    assert not value.exception and accounts.configured()
    assert "new-meta-secret" not in (accounts.directory() / "accounts.enc").read_text()
    assert not studio.jobs()


def test_content_form_can_review_and_save_without_uploading(facebook_setup):
    value = app()
    row = fixtures.remote()
    with patch.object(
        FacebookPage, "content", return_value={"items": [row], "next": None}
    ):
        by_key(value.button, "meta_content_load").click().run()
    assert not value.exception
    by_key(
        value.text_input, "meta_edit_title:" + fixtures.VIDEO + "revision1"
    ).set_value("New title")
    by_key(value.checkbox, "meta_edit_check:" + fixtures.VIDEO).check()
    with patch.object(studio, "edit_video") as edit:
        by_label(value.button, "Save Facebook changes").click().run()
    assert not value.exception
    edit.assert_called_once_with(
        fixtures.CID, fixtures.VIDEO, "New title", row["description"], True, "revision1"
    )
    assert not studio.jobs()


def test_attach_page_is_explicit(facebook_setup):
    data = accounts.vault()
    data["connections"] = {}
    accounts.save(data)
    value = app()
    assert not value.exception and not accounts.connections()
    by_key(value.selectbox, "meta_attach_page").set_value(0).run()
    with patch.object(
        accounts,
        "refresh_pages",
        return_value=accounts.vault()["grants"][fixtures.GID]["pages"],
    ):
        by_key(value.button, "meta_attach").click().run()
    assert not value.exception and accounts.connections()[0]["page_id"] == fixtures.PAGE


def test_main_facebook_route_opens_direct_dashboard(facebook_setup):
    from pathlib import Path

    value = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "webui/Main.py"), default_timeout=60
    )
    value.query_params["view"] = "facebook"
    value.run()
    assert not value.exception
    assert by_key(value.radio, "social_platform").value == "Facebook"
    assert "Social Dashboard" in [t.value for t in value.title]
    assert by_key(value.button, "meta_connect")


def test_facebook_labels_have_english_chinese_translations():
    import ast
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/facebook_direct_dashboard.py").read_text())
    keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "tr"
        and n.args
        and isinstance(n.args[0], ast.Constant)
    }
    for locale in ("en", "zh"):
        assert (
            keys
            <= json.loads((root / "webui/i18n" / (locale + ".json")).read_text())[
                "Translation"
            ].keys()
        )
