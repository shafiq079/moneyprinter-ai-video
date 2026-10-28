from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import youtube_studio as studio
from app.services.youtube_publisher import YouTubePublisher
from test.services import test_youtube_studio as fixtures

SOURCE = """
from webui.youtube_studio import render
render(lambda key: key)
"""


@pytest.fixture
def setup_studio():
    fixture = fixtures.YouTubeStudioTest()
    fixture.setUp()
    try:
        with patch.object(YouTubePublisher, "profiles", return_value=[fixture.channel]):
            studio.refresh_channels()
        with patch(
            "app.services.youtube_publisher.requests.request",
            side_effect=AssertionError("unexpected live provider request"),
        ):
            yield fixture
    finally:
        fixture.doCleanups()


def by_key(elements, key):
    return next(e for e in elements if e.key == key)


def by_label(elements, label):
    return next(e for e in elements if e.label == label)


def test_youtube_page_does_not_connect_or_publish_on_render_or_reload(setup_studio):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert len(studio.jobs()) == 0
    assert "Connected YouTube channels" in [x.value for x in app.subheader]
    app.run()
    assert not app.exception
    assert len(studio.jobs()) == 0
    with patch.object(
        YouTubePublisher,
        "connect_url",
        return_value="https://app.upload-post.com/connect?token=transient",
    ) as connect:
        by_key(app.button, "yt_connect").click().run()
        connect.assert_called_once_with("garden")
        assert app.session_state["yt_connect_link"]["profile"] == "garden"
    assert not app.exception
    assert not list(studio.root().rglob("*transient*"))


def test_prepare_and_review_are_separate_and_both_tabs_use_unique_widget_keys(
    setup_studio,
):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    suffix = "test-video:final-1.mp4"
    by_key(app.selectbox, "yt_audience:" + suffix).set_value(False)
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    records = studio.jobs()
    assert len(records) == 1
    job = records[0]
    assert job["state"] == "draft"
    assert by_key(app.button, "yt_approve:compose:" + job["id"]).disabled
    assert by_key(app.button, "yt_approve:history:" + job["id"]).disabled
    by_key(app.checkbox, "yt_reviewed:compose:" + job["id"]).check().run()
    by_key(app.button, "yt_approve:compose:" + job["id"]).click().run()
    assert not app.exception
    assert studio.get(job["id"])["state"] == "queued"
    setup_studio.start.assert_called()


def test_existing_draft_is_recoverable_after_new_browser_session(setup_studio):
    job = setup_studio.draft()
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert by_key(app.checkbox, "yt_reviewed:history:" + job["id"])
    assert by_key(app.button, "yt_approve:history:" + job["id"]).disabled


def test_missing_provider_configuration_has_setup_and_no_network(setup_studio):
    from app.config import config

    with patch.object(config, "app", {**config.app, "upload_post_api_key": ""}):
        app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    assert not app.tabs
    assert any("Configure its API key" in x.value for x in app.info)


def test_main_application_routes_to_youtube_studio(setup_studio):
    from pathlib import Path

    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "webui" / "Main.py"),
        default_timeout=60,
    )
    app.query_params["view"] = "youtube-legacy"
    app.run()
    assert not app.exception
    assert "YouTube Studio" in [x.value for x in app.title]


def test_youtube_page_has_complete_english_and_chinese_labels():
    import ast
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui" / "youtube_studio.py").read_text())
    keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "tr"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
    }
    for locale in ("en", "zh"):
        translations = json.loads(
            (root / "webui" / "i18n" / (locale + ".json")).read_text()
        )["Translation"]
        assert keys <= set(translations)
