import ast
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from streamlit.testing.v1 import AppTest
from app.services import campaigns as c
from test.services import test_campaigns as f
from test.services.test_webui_youtube_studio import by_key, by_label

SOURCE = "from webui.campaigns import render\nrender(lambda key:key)"


@pytest.fixture
def setup():
    yield from f.setup.__wrapped__()


def test_create_plan_edit_and_approve_are_separate(setup):
    app = AppTest.from_string(SOURCE, default_timeout=30).run()
    assert not app.exception
    by_key(app.text_area, "campaign_brief").set_value(
        "Five garden videos, each 30 seconds"
    )
    by_key(app.number_input, "campaign_count").set_value(2)
    by_label(app.button, "Create campaign").click().run()
    assert not app.exception and len(c.all_campaigns()) == 1
    value = c.all_campaigns()[0]
    cid = value["id"]
    assert not value["items"]
    with patch.object(
        c.llm,
        "generate_json_response",
        return_value={
            "items": [
                {"title": "Garden " + str(i), "script": "Narration " + str(i)}
                for i in range(2)
            ]
        },
    ):
        by_key(app.button, "campaign_plan:" + cid).click().run()
    assert not app.exception
    value = c.get(cid)
    item = value["items"][0]
    assert by_key(app.button, "campaign_approve:" + cid).disabled
    by_key(app.text_area, "campaign_script:" + item["id"]).set_value(
        "Reviewed edited narration"
    )
    by_label(app.button, "Save campaign script").click().run()
    current = c.get(cid)
    by_key(
        app.checkbox, "campaign_review:" + cid + ":" + str(current["revision"])
    ).check().run()
    by_key(app.button, "campaign_approve:" + cid).click().run()
    assert not app.exception and all(
        i["state"] == "queued" for i in c.get(cid)["items"]
    )
    setup.campaign_queue.assert_called_once()


def test_reload_does_not_plan_or_approve_again(setup):
    value = f.plan(setup)
    app = AppTest.from_string(SOURCE, default_timeout=30)
    app.query_params["campaign"] = value["id"]
    with patch.object(
        c.llm,
        "generate_json_response",
        side_effect=AssertionError("unexpected AI call"),
    ):
        app.run()
        app.run()
    assert not app.exception
    assert all(i["state"] == "planned" for i in c.get(value["id"])["items"])
    setup.campaign_queue.assert_not_called()


def test_main_campaign_route_and_labels(setup):
    root = Path(__file__).resolve().parents[2]
    app = AppTest.from_file(str(root / "webui/Main.py"), default_timeout=60)
    app.query_params["view"] = "campaigns"
    app.run()
    assert not app.exception and "Campaigns" in [t.value for t in app.title]
    tree = ast.parse((root / "webui/campaigns.py").read_text())
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
