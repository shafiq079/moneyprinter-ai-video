import ast
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _video_source_groups():
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "VIDEO_SOURCE_GROUPS"
            for target in node.targets
        )
    )
    return ast.literal_eval(assignment.value)


def test_public_local_ai_sources_are_registered_as_distinct_video_sources():
    groups = _video_source_groups()
    assert groups["local_ai_video"] == ("wan22_local", "ltx25_local")
    assert "__local_ai_fake__" not in {
        source for group in groups.values() for source in group
    }


def test_ltx25_selection_shows_readiness_control_without_running_preflight():
    values = dict(
        config.app,
        llm_provider="openai",
        video_source="ltx25_local",
    )
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.local_ai.preflight_status") as preflight_status,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()

        buttons = [
            item
            for item in app.button
            if str(getattr(item, "key", "")).startswith(
                "ltx25_local_readiness_button"
            )
        ]
        assert len(buttons) == 1
        generation_modes = [
            item
            for item in app.selectbox
            if getattr(item, "label", "") == "Generation mode"
        ]
        assert len(generation_modes) == 1
        assert generation_modes[0].value == "fast"
        visual_style_inputs = [
            item
            for item in app.text_area
            if getattr(item, "label", "") == "Visual style / direction"
        ]
        assert len(visual_style_inputs) == 1
        assert not app.exception
        preflight_status.assert_not_called()


def test_wan22_selection_shows_readiness_control_without_running_preflight():
    values = dict(
        config.app,
        llm_provider="openai",
        video_source="wan22_local",
    )
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.local_ai.preflight_status") as preflight_status,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()

        buttons = [
            item
            for item in app.button
            if str(getattr(item, "key", "")).startswith(
                "wan22_local_readiness_button"
            )
        ]
        assert len(buttons) == 1
        assert not app.exception
        preflight_status.assert_not_called()
