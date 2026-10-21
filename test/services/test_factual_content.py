"""CPU contracts for opt-in factual review before paid or GPU work."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import cli
from app.models.schema import FactualSource, TaskVideoRequest, VideoParams
from app.services import factual_content, task
from app.services.state import MemoryState
from app.config import config
from app import asgi
from app.controllers.v1 import video as video_controller


SOURCE = {
    "url": "https://example.org/moon",
    "title": "Moon surface",
    "excerpt": "The Moon has impact craters across its surface.",
}


def params(script="The Moon has impact craters."):
    return VideoParams(
        video_subject="Moon surface",
        video_script=script,
        content_mode="factual",
        factual_sources=[SOURCE],
        video_source="pexels",
    )


def test_source_contract_rejects_credential_urls_and_limits():
    for url in (
        "http://example.org/moon",
        "https://user:pass@example.org/moon",
        "https://example.org/moon?token=secret",
        "https://localhost/moon",
    ):
        with pytest.raises(ValueError):
            FactualSource(**{**SOURCE, "url": url})
    with pytest.raises(ValueError):
        TaskVideoRequest(
            video_subject="Moon",
            content_mode="factual",
            factual_sources=[SOURCE] * 7,
        )
    with pytest.raises(factual_content.FactualReviewBlocked, match="distinct"):
        factual_content.validate_sources(
            VideoParams(
                video_subject="Moon",
                content_mode="factual",
                factual_sources=[SOURCE, SOURCE],
            )
        )
    with pytest.raises(ValueError) as error:
        TaskVideoRequest(
            video_subject="Moon",
            factual_sources=[
                {**SOURCE, "url": "https://example.org/?token=private123"}
            ],
        )
    assert "private123" not in str(error.value)


def test_creative_mode_has_no_research_dependency(tmp_path):
    state = MemoryState()
    with (
        patch.object(task.sm, "state", state),
        patch.object(
            task, "generate_script", return_value="A quiet garden."
        ) as generate,
        patch.object(task.factual_content, "review_script") as review,
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
    ):
        result = task.start(
            "creative", VideoParams(video_subject="Garden"), stop_at="script"
        )
    assert result == {"script": "A quiet garden."}
    generate.assert_called_once()
    review.assert_not_called()


def test_factual_approval_precedes_audio_and_writes_review(tmp_path):
    state = MemoryState()
    review = {
        "verdict": "approved",
        "reason": "Directly supported",
        "claims": [
            {
                "claim": "The Moon has impact craters.",
                "source_ids": ["S1"],
                "evidence_quotes": {"S1": SOURCE["excerpt"]},
            }
        ],
    }
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm, "generate_json_response", return_value=review
        ) as llm,
        patch.object(task, "generate_audio") as audio,
        patch.object(task, "generate_terms") as terms,
        patch.object(task.utils, "check_ffmpeg_ready") as ffmpeg,
        patch.object(task.local_ai, "prepare_provider") as provider,
    ):
        result = task.start("approved", params(), stop_at="script")
    assert result == {"script": "The Moon has impact craters."}
    audio.assert_not_called()
    terms.assert_not_called()
    ffmpeg.assert_not_called()
    provider.assert_not_called()
    llm.assert_called_once()
    record = json.loads((tmp_path / "factual_review.json").read_text())
    assert record["status"] == "approved"
    assert record["claims"][0]["source_ids"] == ["S1"]
    assert record["claims"][0]["evidence_quotes"] == {"S1": SOURCE["excerpt"]}
    assert record["sources"][0]["url"] == SOURCE["url"]
    script_data = json.loads((tmp_path / "script.json").read_text())
    assert script_data["script"] == params().video_script
    assert script_data["params"]["content_mode"] == "factual"
    assert script_data["search_terms"] == []
    with patch.object(task.utils, "task_dir", return_value=str(tmp_path)):
        public = video_controller._public_task_data(
            {"task_id": "approved", "state": "complete"}
        )
    assert public["artifact_package"]["factual_review"] == "factual_review.json"
    assert str(tmp_path) not in json.dumps(public)


def test_http_task_responses_expose_factual_review_artifact(tmp_path, monkeypatch):
    task_id = "reviewed-http-task"
    (tmp_path / "factual_review.json").write_text("{}", encoding="utf-8")
    (tmp_path / "script.json").write_text("{}", encoding="utf-8")
    state = MemoryState()
    state.update_task(task_id, state=1, progress=100)
    monkeypatch.setitem(config.app, "api_key", "")
    with (
        patch.object(video_controller.sm, "state", state),
        patch.object(video_controller.utils, "task_dir", return_value=str(tmp_path)),
    ):
        client = TestClient(asgi.app)
        detail = client.get(f"/api/v1/tasks/{task_id}")
        listing = client.get("/api/v1/tasks")

    assert detail.status_code == 200
    assert listing.status_code == 200
    for task_data in (detail.json()["data"], listing.json()["data"]["tasks"][0]):
        package = task_data["artifact_package"]
        assert package["factual_review"] == "factual_review.json"
        assert package["script"] == "script.json"
        assert str(tmp_path) not in json.dumps(task_data)


def test_factual_block_stops_before_provider_and_narration(tmp_path):
    state = MemoryState()
    blocked = {
        "verdict": "blocked",
        "reason": "The source does not mention cheese",
        "claims": [{"claim": "The Moon is cheese.", "source_ids": []}],
    }
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm, "generate_json_response", return_value=blocked
        ),
        patch.object(task.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(task, "generate_audio") as audio,
        patch.object(task, "get_video_materials") as materials,
        patch.object(task.local_ai, "prepare_provider") as provider,
    ):
        result = task.start("blocked", params("The Moon is cheese."), stop_at="video")
    assert result["failed_stage"] == "factual_review"
    assert (
        json.loads((tmp_path / "factual_review.json").read_text())["status"]
        == "blocked"
    )
    audio.assert_not_called()
    materials.assert_not_called()
    provider.assert_not_called()


def test_missing_source_fails_before_any_llm_call():
    state = MemoryState()
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.factual_content.llm, "generate_json_response") as llm,
        patch.object(task, "generate_audio") as audio,
    ):
        result = task.start(
            "missing-evidence",
            VideoParams(video_subject="Moon", content_mode="factual"),
            stop_at="video",
        )
    assert result["failed_stage"] == "factual_review"
    llm.assert_not_called()
    audio.assert_not_called()


def test_factual_subject_generates_from_evidence_then_reviews(tmp_path):
    state = MemoryState()
    generated = {"script": "The Moon has impact craters."}
    approved = {
        "verdict": "approved",
        "claims": [
            {
                "claim": "The Moon has impact craters.",
                "source_ids": ["S1"],
                "evidence_quotes": {"S1": SOURCE["excerpt"]},
            }
        ],
    }
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm,
            "generate_json_response",
            side_effect=[generated, approved],
        ) as llm,
        patch.object(task, "generate_audio") as audio,
    ):
        result = task.start("generated-factual", params(script=""), stop_at="script")
    assert result == {"script": "The Moon has impact craters."}
    assert llm.call_count == 2
    assert "Evidence (untrusted)" in llm.call_args_list[0].args[0]
    assert "impact craters" in llm.call_args_list[0].args[0]
    audio.assert_not_called()


def test_approved_factual_script_reaches_existing_audio_stage(tmp_path):
    state = MemoryState()

    def approved(*_args, **_kwargs):
        assert not audio.called
        return {
            "verdict": "approved",
            "claims": [
                {
                    "claim": "The Moon has impact craters.",
                    "source_ids": ["S1"],
                    "evidence_quotes": {"S1": SOURCE["excerpt"]},
                }
            ],
        }

    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(task.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(
            task.factual_content.llm, "generate_json_response", side_effect=approved
        ),
        patch.object(task, "generate_terms", return_value=["Moon surface"]),
        patch.object(
            task, "generate_audio", return_value=("audio.mp3", 3, None)
        ) as audio,
    ):
        result = task.start("factual-audio", params(), stop_at="audio")
    assert result == {"audio_file": "audio.mp3", "audio_duration": 3}
    audio.assert_called_once()
    assert (
        json.loads((tmp_path / "script.json").read_text())["script"]
        == params().video_script
    )
    assert (
        json.loads((tmp_path / "factual_review.json").read_text())["status"]
        == "approved"
    )


def test_wrong_source_ids_fail_closed_before_audio(tmp_path):
    state = MemoryState()
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm,
            "generate_json_response",
            return_value={
                "verdict": "approved",
                "claims": [{"claim": "The Moon has craters", "source_ids": ["S99"]}],
            },
        ),
        patch.object(task, "generate_audio") as audio,
    ):
        result = task.start("unknown-source", params(), stop_at="script")
    assert result["failed_stage"] == "factual_review"
    audio.assert_not_called()


def test_factual_numbers_must_be_in_cited_excerpt():
    with pytest.raises(factual_content.FactualReviewBlocked, match="numerical"):
        factual_content._validated_review(
            {
                "verdict": "approved",
                "claims": [{"claim": "The Moon has 99 craters.", "source_ids": ["S1"]}],
            },
            "The Moon has 99 craters.",
            [FactualSource(**SOURCE)],
        )


def test_factual_approval_requires_verbatim_passage_from_each_cited_excerpt():
    sources = [
        FactualSource(**SOURCE),
        FactualSource(
            url="https://example.org/other",
            title="Other observations",
            excerpt="A second source also describes impact craters on the Moon.",
        ),
    ]
    claim = "The Moon has impact craters."
    valid = {
        "claim": claim,
        "source_ids": ["S1", "S2"],
        "evidence_quotes": {
            "S1": "The Moon has impact craters",
            "S2": "describes impact craters on the Moon",
        },
    }
    review = factual_content._validated_review(
        {"verdict": "approved", "claims": [valid]}, claim, sources
    )
    assert review["claims"][0]["evidence_quotes"] == valid["evidence_quotes"]

    for quotes in (
        None,
        {"S1": valid["evidence_quotes"]["S1"]},
        {"S1": valid["evidence_quotes"]["S1"], "S2": "Not in this source"},
        {"S1": valid["evidence_quotes"]["S2"], "S2": valid["evidence_quotes"]["S1"]},
        {"S1": valid["evidence_quotes"]["S1"], "S2": "bad", "S99": "unknown"},
    ):
        invalid = {**valid, "evidence_quotes": quotes}
        with pytest.raises(factual_content.FactualReviewBlocked, match="passage"):
            factual_content._validated_review(
                {"verdict": "approved", "claims": [invalid]}, claim, sources
            )


def test_factual_quote_missing_blocks_before_audio(tmp_path):
    state = MemoryState()
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm,
            "generate_json_response",
            return_value={
                "verdict": "approved",
                "claims": [
                    {"claim": "The Moon has impact craters.", "source_ids": ["S1"]}
                ],
            },
        ),
        patch.object(task, "generate_audio") as audio,
        patch.object(task, "get_video_materials") as materials,
    ):
        result = task.start("missing-passage", params(), stop_at="video")
    assert result["failed_stage"] == "factual_review"
    audio.assert_not_called()
    materials.assert_not_called()
    assert not (tmp_path / "factual_review.json").exists()


def test_factual_approval_requires_every_narration_unit_in_order():
    script = "The Moon has impact craters. It is made of cheese."
    source = [FactualSource(**SOURCE)]
    supported = {
        "claim": "The Moon has impact craters.",
        "source_ids": ["S1"],
        "evidence_quotes": {"S1": SOURCE["excerpt"]},
    }
    unsupported = {
        "claim": "It is made of cheese.",
        "source_ids": ["S1"],
        "evidence_quotes": {"S1": SOURCE["excerpt"]},
    }
    for claims in (
        [supported],
        [supported, supported],
        [
            supported,
            {
                "claim": "It has cheese.",
                "source_ids": ["S1"],
                "evidence_quotes": {"S1": SOURCE["excerpt"]},
            },
        ],
        [unsupported, supported],
    ):
        with pytest.raises(factual_content.FactualReviewBlocked, match="cover"):
            factual_content._validated_review(
                {"verdict": "approved", "claims": claims}, script, source
            )


def test_incomplete_factual_approval_stops_before_audio(tmp_path):
    state = MemoryState()
    incomplete = {
        "verdict": "approved",
        "claims": [
            {
                "claim": "The Moon has impact craters.",
                "source_ids": ["S1"],
                "evidence_quotes": {"S1": SOURCE["excerpt"]},
            }
        ],
    }
    with (
        patch.object(task.sm, "state", state),
        patch.object(task.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(
            task.factual_content.llm, "generate_json_response", return_value=incomplete
        ),
        patch.object(task, "generate_audio") as audio,
        patch.object(task, "get_video_materials") as materials,
    ):
        result = task.start(
            "unreviewed-sentence",
            params("The Moon has impact craters. It is made of cheese."),
            stop_at="video",
        )
    assert result["failed_stage"] == "factual_review"
    audio.assert_not_called()
    materials.assert_not_called()
    assert not (tmp_path / "factual_review.json").exists()


def test_factual_review_prompt_requests_complete_verbatim_coverage():
    script = "The Moon has craters. Water exists."
    prompt = factual_content._review_prompt(script, [FactualSource(**SOURCE)])
    assert '"The Moon has craters.", "Water exists."' in prompt
    assert "copying its text verbatim" in prompt
    assert "evidence_quotes" in prompt


def test_factual_review_units_handle_paragraphs_and_cjk_punctuation():
    assert factual_content._narration_units("First claim. Second!\n第三句。第四句？") == [
        "First claim.",
        "Second!",
        "第三句。",
        "第四句？",
    ]


def test_cli_accepts_manual_sources_and_rejects_missing_evidence():
    args = cli.parse_args(
        [
            "--video-subject",
            "Moon",
            "--content-mode",
            "factual",
            "--factual-source",
            f"{SOURCE['url']} | {SOURCE['title']} | {SOURCE['excerpt']}",
            "--stop-at",
            "script",
        ]
    )
    built = cli.build_video_params(args)
    assert built.content_mode == "factual"
    assert factual_content.validate_sources(built)[0].title == SOURCE["title"]
    assert (
        cli.run_cli(
            [
                "--video-subject",
                "Moon",
                "--content-mode",
                "factual",
                "--stop-at",
                "script",
            ]
        )
        == 2
    )


def test_webui_factual_controls_validate_sources_without_generation():
    app_path = Path(__file__).parents[2] / "webui" / "Main.py"
    with patch.object(config, "try_save_config", return_value=True):
        app = AppTest.from_file(str(app_path), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        assert not app.exception
        mode = next(
            item
            for item in app.selectbox
            if str(item.key).startswith("content_mode_select_")
        )
        assert mode.value == "creative"
        mode.set_value("factual").run()
        assert not app.exception
        source = next(
            item for item in app.text_area if item.key == "factual_sources_input"
        )
        source.set_value(
            f"{SOURCE['url']} | {SOURCE['title']} | {SOURCE['excerpt']}"
        ).run()
        assert not app.exception
        assert "factual_source_error" not in app.session_state
        source = next(
            item for item in app.text_area if item.key == "factual_sources_input"
        )
        source.set_value("http://localhost | bad | invalid excerpt").run()
        assert app.session_state["factual_source_error"]


def test_webui_review_only_submits_script_stage_without_video_preflight():
    app_path = Path(__file__).parents[2] / "webui" / "Main.py"
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit,
        patch.object(task.local_ai, "prepare_provider") as provider,
    ):
        app = AppTest.from_file(str(app_path), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        mode = next(
            item
            for item in app.selectbox
            if str(item.key).startswith("content_mode_select_")
        )
        mode.set_value("factual").run()
        next(item for item in app.text_area if item.key == "video_subject").set_value(
            "Moon surface"
        ).run()
        next(item for item in app.text_area if item.key == "video_script").set_value(
            "The Moon has impact craters."
        ).run()
        next(
            item for item in app.text_area if item.key == "factual_sources_input"
        ).set_value(
            f"{SOURCE['url']} | {SOURCE['title']} | {SOURCE['excerpt']}"
        ).run()
        next(
            item for item in app.button if item.key == "review_factual_script_button"
        ).click().run()

    assert not app.exception
    submit.assert_called_once()
    assert submit.call_args.kwargs["stop_at"] == "script"
    assert submit.call_args.kwargs["params"].content_mode == "factual"
    provider.assert_not_called()


def test_saved_review_summary_excludes_excerpts_and_rejects_external_file(tmp_path):
    task_dir = tmp_path / "review-task"
    task_dir.mkdir()
    review = factual_content._validated_review(
        {
            "verdict": "blocked",
            "reason": "Claim lacks evidence",
            "claims": [{"claim": "The Moon is cheese.", "source_ids": []}],
        },
        "The Moon is cheese.",
        [FactualSource(**SOURCE)],
    )
    (task_dir / "factual_review.json").write_text(json.dumps(review))
    with patch.object(
        factual_content.utils,
        "task_dir",
        return_value=str(task_dir),
    ):
        summary = factual_content.load_review_summary("review-task")
        assert summary["status"] == "blocked"
        assert summary["claims"][0]["source_ids"] == []
        assert SOURCE["excerpt"] not in json.dumps(summary)

        (task_dir / "factual_review.json").unlink()
        (task_dir / "factual_review.json").symlink_to(tmp_path / "outside.json")
        with pytest.raises(factual_content.FactualReviewBlocked, match="unavailable"):
            factual_content.load_review_summary("review-task")


def test_new_review_summary_hides_quotes_and_old_approval_remains_readable(tmp_path):
    task_dir = tmp_path / "review-task"
    task_dir.mkdir()
    review = factual_content._validated_review(
        {
            "verdict": "approved",
            "claims": [
                {
                    "claim": "The Moon has impact craters.",
                    "source_ids": ["S1"],
                    "evidence_quotes": {"S1": SOURCE["excerpt"]},
                }
            ],
        },
        "The Moon has impact craters.",
        [FactualSource(**SOURCE)],
    )
    target = task_dir / "factual_review.json"
    target.write_text(json.dumps(review))
    with patch.object(factual_content.utils, "task_dir", return_value=str(task_dir)):
        summary = factual_content.load_review_summary("review-task")
        assert "evidence_quotes" not in summary["claims"][0]
        assert SOURCE["excerpt"] not in json.dumps(summary)
        factual_content.validate_saved_approval(
            "review-task", "The Moon has impact craters.", [FactualSource(**SOURCE)]
        )
        review["claims"][0].pop("evidence_quotes")
        target.write_text(json.dumps(review))
        assert (
            factual_content.load_review_summary("review-task")["status"] == "approved"
        )
        factual_content.validate_saved_approval(
            "review-task", "The Moon has impact craters.", [FactualSource(**SOURCE)]
        )


def test_webui_task_manager_displays_blocked_review_without_video(tmp_path):
    task_dir = tmp_path / "review-task"
    task_dir.mkdir()
    review = factual_content._validated_review(
        {
            "verdict": "blocked",
            "reason": "Claim lacks evidence",
            "claims": [{"claim": "The Moon is cheese.", "source_ids": []}],
        },
        "The Moon is cheese.",
        [FactualSource(**SOURCE)],
    )
    (task_dir / "factual_review.json").write_text(json.dumps(review))

    def task_dir_path(task_id=None):
        return str(tmp_path / task_id) if task_id else str(tmp_path)

    app_path = Path(__file__).parents[2] / "webui" / "Main.py"
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.object(factual_content.utils, "task_dir", side_effect=task_dir_path),
    ):
        app = AppTest.from_file(str(app_path), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["artifact_package_task_id"] = "review-task"
        app.run()
    assert not app.exception
    assert any(
        item.key and str(item.key).startswith("artifacts_task_") and not item.disabled
        for item in app.button
    )
    rendered = "\n".join(str(item.value) for item in app.text)
    assert "The Moon is cheese." in rendered
    assert "S1: Moon surface" in rendered
    assert SOURCE["excerpt"] not in rendered


def test_webui_artifacts_show_approved_script_only_review_after_restart(tmp_path):
    task_id = "script-review-task"
    task_dir = tmp_path / task_id
    task_dir.mkdir()
    script = "The Moon has impact craters."
    review = factual_content._validated_review(
        {
            "verdict": "approved",
            "claims": [
                {
                    "claim": script,
                    "source_ids": ["S1"],
                    "evidence_quotes": {"S1": SOURCE["excerpt"]},
                }
            ],
        },
        script,
        [FactualSource(**SOURCE)],
    )
    (task_dir / "factual_review.json").write_text(json.dumps(review))
    (task_dir / "script.json").write_text(
        json.dumps(
            {
                "script": script,
                "params": {
                    "video_subject": "Moon surface",
                    "video_source": "pexels",
                    "content_mode": "factual",
                    "factual_sources": [SOURCE],
                },
            }
        )
    )

    def task_dir_path(value=None):
        return str(tmp_path / value) if value else str(tmp_path)

    app_path = Path(__file__).parents[2] / "webui" / "Main.py"
    with (
        patch.object(config, "try_save_config", return_value=True),
        patch.object(factual_content.utils, "task_dir", side_effect=task_dir_path),
    ):
        app = AppTest.from_file(str(app_path), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["artifact_package_task_id"] = task_id
        app.run()
    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.text)
    assert script in rendered
    assert SOURCE["excerpt"] not in rendered
