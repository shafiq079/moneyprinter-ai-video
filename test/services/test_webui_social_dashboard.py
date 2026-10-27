from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import youtube_accounts as accounts, youtube_direct as studio
from app.services.youtube_google import GoogleYouTube
from test.services import test_youtube_direct as fixtures
from test.services.test_webui_youtube_studio import by_key, by_label

SOURCE = "from webui.social_dashboard import render\nrender(lambda key: key)"


@pytest.fixture
def direct_setup():
    yield from fixtures.direct_setup.__wrapped__()


def test_dashboard_render_reload_and_connect_do_not_upload(direct_setup):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert "Social Dashboard" in [t.value for t in app.title]
    assert [t.label for t in app.tabs] == [
        "Accounts",
        "Content",
        "Create post",
        "Calendar / Queue",
        "Legacy publishing",
    ]
    assert not studio.jobs()
    by_key(app.button, "social_connect").click().run()
    assert not app.exception
    assert (
        "/social/youtube/oauth/start?ticket=" in app.session_state["social_connect_url"]
    )
    app.run()
    assert not app.exception and not studio.jobs()
    assert not direct_setup.enqueue.called


def test_prepare_separate_approval_and_fresh_session_draft_restore(direct_setup):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    by_key(app.selectbox, "social_new:test-videofinal-1.mp4audience").set_value(False)
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    job = studio.jobs()[0]
    assert job["state"] == "draft"
    assert by_key(app.button, "compose:approve:" + job["id"]).disabled
    assert by_key(app.button, "history:approve:" + job["id"]).disabled
    fresh = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not fresh.exception
    by_key(fresh.checkbox, "history:review:" + job["id"]).check().run()
    by_key(fresh.button, "history:approve:" + job["id"]).click().run()
    assert not fresh.exception
    assert studio.get(job["id"])["state"] == "queued"
    direct_setup.enqueue.assert_called()


def test_google_setup_missing_and_save_without_upload_post_or_network(direct_setup):
    value = accounts.vault()
    value["settings"] = {}
    value["connections"] = {}
    accounts.save_vault(value)
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    by_key(app.text_input, "social_client_id").set_value(
        "new.apps.googleusercontent.com"
    )
    by_key(app.text_input, "social_client_secret").set_value("new-secret")
    by_key(app.text_input, "social_callback").set_value(
        "http://127.0.0.1:8501" + accounts.CALLBACK
    )
    by_label(app.button, "Save Google application").click().run()
    assert not app.exception
    assert accounts.configured()
    assert "new-secret" not in (accounts.directory() / "accounts.enc").read_text()
    assert not studio.jobs()


def test_remote_content_form_accepts_review_and_saves_without_upload(direct_setup):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    row = fixtures.remote()
    with patch.object(
        GoogleYouTube, "content", return_value={"items": [row], "next": None}
    ):
        by_key(app.button, "social_content_load").click().run()
    assert not app.exception
    by_key(
        app.text_input, "social_edit:" + fixtures.VIDEO + ":etag-original:title"
    ).set_value("Edited title")
    by_key(app.checkbox, "social_edit_review:" + fixtures.VIDEO).check()
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(GoogleYouTube, "update", return_value=row) as update,
        patch.object(GoogleYouTube, "initiate") as upload,
    ):
        by_label(app.button, "Save YouTube changes").click().run()
        assert not app.exception
        assert update.call_args.kwargs["snippet"]["title"] == "Edited title"
        upload.assert_not_called()
    assert not studio.jobs()


def test_main_youtube_alias_and_social_route_show_direct_dashboard(direct_setup):
    path = str(Path(__file__).resolve().parents[2] / "webui/Main.py")
    for route in ("youtube", "social"):
        app = AppTest.from_file(path, default_timeout=60)
        app.query_params["view"] = route
        app.run()
        assert not app.exception
        assert "Social Dashboard" in [e.value for e in app.title]


def test_direct_dashboard_labels_have_english_and_chinese_translations():
    import ast
    import json

    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/social_dashboard.py").read_text())
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
