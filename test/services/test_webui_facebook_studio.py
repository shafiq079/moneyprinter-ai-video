import ast
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import facebook_studio as studio, youtube_studio as delivery
from app.services.facebook_publisher import FacebookPublisher
from test.services import test_facebook_studio as fixtures
from test.services.test_webui_youtube_studio import by_key, by_label


@pytest.fixture
def setup_facebook():
    yield from fixtures.setup_facebook.__wrapped__()


SOURCE = "from webui.facebook_studio import render\nrender(lambda key: key)"
SUFFIX = "test-video:final-1.mp4"


def test_render_reload_and_hosted_connection_do_not_publish(setup_facebook):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert "Connected Facebook Pages" in [x.value for x in app.subheader]
    assert by_key(app.selectbox, "fb_destination").value is None
    app.run()
    assert not app.exception and not studio.jobs()
    with patch.object(
        FacebookPublisher,
        "connect_url",
        return_value="https://app.upload-post.com/connect?token=transient",
    ) as connect:
        by_key(app.button, "fb_connect").click().run()
        connect.assert_called_once_with("garden")
        assert app.session_state["fb_connect_link"]["profile"] == "garden"
    assert not app.exception and not studio.jobs()
    assert "transient" not in (delivery.root() / "facebook_channels.json").read_text()


def test_page_selection_and_separate_review_required_and_recoverable(setup_facebook):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception and not studio.jobs()
    assert "Choose a Page" in [e.value for e in app.error]
    by_key(app.selectbox, "fb_destination").select(0)
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    job = studio.jobs()[0]
    assert job["state"] == "draft" and job["channel"]["channel_id"] == "123456"
    assert by_key(app.button, "fb_approve:compose:" + job["id"]).disabled
    assert by_key(app.button, "fb_approve:history:" + job["id"]).disabled
    fresh = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not fresh.exception
    by_key(fresh.checkbox, "fb_reviewed:history:" + job["id"]).check().run()
    by_key(fresh.button, "fb_approve:history:" + job["id"]).click().run()
    assert not fresh.exception
    assert studio.get(job["id"])["state"] == "queued"
    setup_facebook.start.assert_called()


def test_pinned_page_filter_and_schedule_review_keeps_timezone(setup_facebook):
    f = setup_facebook
    profile = {**f.facebook_profile, "selected_page_id": "123456"}
    with patch.object(FacebookPublisher, "profiles", return_value=[profile]):
        studio.refresh_channels()
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert len(by_key(app.selectbox, "fb_destination").options) == 1
    by_key(app.selectbox, "fb_destination").select(0)
    by_key(app.radio, "fb_mode:" + SUFFIX).set_value("Schedule").run()
    by_key(app.text_input, "fb_zone:" + SUFFIX).set_value("Asia/Karachi")
    by_key(app.date_input, "fb_date:" + SUFFIX).set_value(
        datetime.now().date() + timedelta(days=1)
    )
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    settings = studio.jobs()[0]["options"]
    assert (
        settings["timezone"] == "Asia/Karachi"
        and "07:00:00+00:00" in settings["scheduled_at"]
    )
    assert studio.jobs()[0]["state"] == "draft"


def test_facebook_disconnect_does_not_disconnect_youtube(setup_facebook):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    by_key(app.checkbox, "fb_disconnect_confirm:garden").check().run()
    with (
        patch.object(FacebookPublisher, "disconnect") as disconnect,
        patch.object(FacebookPublisher, "profiles", return_value=[]),
    ):
        by_key(app.button, "fb_disconnect").click().run()
        disconnect.assert_called_once_with("garden")
    assert not app.exception
    assert not studio.cached_channels()["channels"]


def test_missing_config_and_main_route(setup_facebook):
    with patch.object(config, "app", {**config.app, "upload_post_api_key": ""}):
        app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception and not app.tabs
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "webui" / "Main.py"),
        default_timeout=60,
    )
    app.query_params["view"] = "facebook-legacy"
    app.run()
    assert not app.exception
    assert "Facebook Studio" in [e.value for e in app.title]


def test_facebook_labels_exist_in_english_and_chinese():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/facebook_studio.py").read_text())
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
        translations = json.loads(
            (root / "webui/i18n" / (locale + ".json")).read_text()
        )["Translation"]
        assert keys <= translations.keys()
