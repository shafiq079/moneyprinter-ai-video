import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import (
    publishing_seo as seo,
    youtube_direct as youtube,
    facebook_direct as facebook,
)
from test.services import test_youtube_direct as fixtures, test_facebook_direct as fb
from test.services.test_publishing_seo import payload, script
from test.services.test_webui_youtube_studio import by_key, by_label

SOURCE = "from webui.social_dashboard import render\nrender(lambda key: key)"


@pytest.fixture
def direct_setup():
    yield from fixtures.direct_setup.__wrapped__()


@pytest.fixture
def facebook_setup():
    yield from fb.facebook_setup.__wrapped__()


def prefix(platform):
    return "publishing_ai:" + platform + ":test-video:final-1.mp4:"


def test_youtube_ai_prefills_copy_without_overriding_declarations_or_publishing(
    direct_setup,
):
    script(direct_setup)
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    by_key(app.selectbox, "social_new:test-videofinal-1.mp4audience").set_value(
        False
    ).run()
    with patch.object(
        seo.llm, "generate_json_response", return_value=payload()
    ) as call:
        by_key(app.button, prefix("youtube") + "generate").click().run()
        assert not app.exception
        app.run()
        call.assert_called_once()
    assert (
        by_key(app.text_input, "social_new:test-videofinal-1.mp4title").value
        == payload()["titles"][0]
    )
    assert (
        "#Gardening"
        in by_key(app.text_area, "social_new:test-videofinal-1.mp4description").value
    )
    assert (
        by_key(app.selectbox, "social_new:test-videofinal-1.mp4audience").value is False
    )
    assert (
        by_key(app.selectbox, "social_new:test-videofinal-1.mp4privacy").value
        == "private"
    )
    assert not youtube.jobs() and not direct_setup.enqueue.called
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    job = youtube.jobs()[0]
    assert job["state"] == "draft" and job["publishing_preparation"]
    assert job["options"]["tags"] == payload()["tags"]


def test_saved_ai_copy_restores_and_manual_edits_survive_reruns(direct_setup):
    script(direct_setup)
    with patch.object(seo.llm, "generate_json_response", return_value=payload()):
        package = seo.generate("test-video", "final-1.mp4", "youtube")
    with patch.object(
        seo.llm,
        "generate_json_response",
        side_effect=AssertionError("reload called model"),
    ):
        app = AppTest.from_string(SOURCE, default_timeout=30).run()
        by_key(app.text_input, "social_new:test-videofinal-1.mp4title").set_value(
            "My reviewed title"
        ).run()
        app.run()
        assert not app.exception
        assert (
            by_key(app.text_input, "social_new:test-videofinal-1.mp4title").value
            == "My reviewed title"
        )
        by_key(app.selectbox, prefix("youtube") + package["id"] + ":title").set_value(
            payload()["titles"][1]
        ).run()
        by_key(app.button, prefix("youtube") + "apply").click().run()
        assert (
            by_key(app.text_input, "social_new:test-videofinal-1.mp4title").value
            == payload()["titles"][1]
        )


def test_facebook_ai_prefills_description_hashtags_and_frozen_review(facebook_setup):
    script(facebook_setup)
    app = AppTest.from_string(SOURCE, default_timeout=30)
    app.query_params["platform"] = "facebook"
    app.run()
    with patch.object(
        seo.llm, "generate_json_response", return_value=payload()
    ) as call:
        by_key(app.button, prefix("facebook") + "generate").click().run()
    assert not app.exception and "facebook" in call.call_args.args[0]
    assert (
        "#HomeGarden"
        in by_key(app.text_area, "meta_description:test-videofinal-1.mp4").value
    )
    assert not facebook.jobs()
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    assert (
        facebook.jobs()[0]["state"] == "draft"
        and facebook.jobs()[0]["publishing_preparation"]["platform"] == "facebook"
    )
    facebook_setup.fb_enqueue.assert_not_called()


def test_generation_error_preserves_form_edits(direct_setup):
    script(direct_setup)
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    by_key(app.text_input, "social_new:test-videofinal-1.mp4title").set_value(
        "Keep me"
    ).run()
    with patch.object(
        seo.llm, "generate_json_response", side_effect=RuntimeError("private-token")
    ):
        by_key(app.button, prefix("youtube") + "generate").click().run()
    assert not app.exception
    assert (
        by_key(app.text_input, "social_new:test-videofinal-1.mp4title").value
        == "Keep me"
    )
    assert "private-token" not in str(app.error)
    assert not youtube.jobs()


def test_labels_exist_in_en_and_zh():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "webui/publishing_seo.py").read_text())
    keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "tr"
        and n.args
        and isinstance(n.args[0], ast.Constant)
    }
    for locale in ["en", "zh"]:
        assert (
            keys
            <= json.loads((root / "webui/i18n" / f"{locale}.json").read_text())[
                "Translation"
            ].keys()
        )


def test_thumbnail_preview_is_frozen_with_review_and_restored(direct_setup):
    import numpy as np
    from unittest.mock import Mock

    script(direct_setup)
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    with patch.object(seo.llm, "generate_json_response", return_value=payload()):
        by_key(app.button, prefix("youtube") + "generate").click().run()
    clip = Mock(
        duration=3, get_frame=Mock(return_value=np.zeros((360, 640, 3), dtype=np.uint8))
    )
    with patch.object(seo.legacy.video, "_open_video_clip_quietly", return_value=clip):
        by_key(app.button, prefix("youtube") + "build_thumbnail").click().run()
    assert not app.exception
    by_key(app.selectbox, "social_new:test-videofinal-1.mp4audience").set_value(
        False
    ).run()
    by_label(app.button, "Prepare for review").click().run()
    assert not app.exception
    job = youtube.jobs()[0]
    assert job["state"] == "draft" and job["thumbnail"]
    fresh = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not fresh.exception
    assert seo.thumbnail_file(job["thumbnail"]).exists()
    by_key(fresh.checkbox, "history:review:" + job["id"]).check().run()
    by_key(fresh.button, "history:approve:" + job["id"]).click().run()
    assert not fresh.exception and youtube.get(job["id"])["state"] == "queued"
