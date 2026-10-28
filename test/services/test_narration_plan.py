from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.schema import VideoParams
from app.services import narration_plan as np, scene_planner, material, llm, task


def maker(rows):
    return SimpleNamespace(
        cues=[
            SimpleNamespace(
                start=timedelta(seconds=a), end=timedelta(seconds=b), content=t
            )
            for a, b, t in rows
        ]
    )


def test_speech_boundaries_choose_variable_shots_and_preserve_all_text():
    plan = np.build(
        "City crowds. Quiet mountains.",
        8,
        10,
        maker=maker([(0, 2.4, "City crowds."), (2.8, 7.5, "Quiet mountains.")]),
    )
    assert [r["duration"] for r in plan["scenes"]] == pytest.approx([2.4, 5.6])
    assert [r["text"] for r in plan["scenes"]] == ["City crowds.", "Quiet mountains."]
    assert plan["timing_source"] == "tts_cues"
    assert not plan["estimated_subdivision"]


def test_long_sentence_splits_on_available_word_cues_not_equal_chunks():
    plan = np.build(
        "Birds fly over green fields.",
        6,
        3,
        maker=maker(
            [
                (0, 1, "Birds"),
                (1, 2.2, "fly"),
                (2.2, 3.5, "over"),
                (3.5, 4.6, "green"),
                (4.6, 6, "fields."),
            ]
        ),
    )
    assert plan["scenes"][0]["text"] == "Birds fly"
    assert plan["scenes"][0]["end"] == 2.2
    assert all(0 < r["duration"] <= 3 for r in plan["scenes"])
    assert sum(r["duration"] for r in plan["scenes"]) == 6
    assert not plan["estimated_subdivision"]


@pytest.mark.parametrize(
    "rows", [[(0, 2, "wrong transcript")], [(2, 1, "Hello.")], [(0, 8, "Hello.")]]
)
def test_invalid_or_unrelated_timing_is_never_reported_as_speech_alignment(rows):
    plan = np.build("Hello.", 4, 3, maker=maker(rows))
    assert plan["timing_source"] == "estimated_text"
    assert sum(r["duration"] for r in plan["scenes"]) == 4


def test_no_voice_and_coarse_provider_mark_estimates():
    m = SimpleNamespace(
        subs=["Hello.", "Goodbye."],
        offset=[(0, 20000000), (20000000, 50000000)],
        timing_estimated=True,
    )
    assert (
        np.build("Hello. Goodbye.", 5, 3, maker=m)["timing_source"] == "estimated_text"
    )
    p = np.build(
        "One extraordinarilylongword.",
        8,
        3,
        maker=maker([(0, 8, "One extraordinarilylongword.")]),
    )
    assert p["estimated_subdivision"]
    assert all(r["duration"] <= 3 for r in p["scenes"])


def test_unicode_and_pause_tags_preserve_script_order():
    p = np.build("花开了。蜜蜂来了！", 5, 3)
    assert np.normalized("".join(r["text"] for r in p["scenes"])) == np.normalized(
        "花开了。蜜蜂来了！"
    )
    assert p["timing_source"] == "estimated_text"


def test_caption_clock_when_tts_has_no_timeline(tmp_path):
    captions = tmp_path / "subtitle.srt"
    captions.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nCity crowds.\n\n2\n00:00:01,700 --> 00:00:04,000\nQuiet mountains.\n"
    )
    p = np.build("City crowds. Quiet mountains.", 4, 5, captions=str(captions))
    assert p["timing_source"] == "caption_cues"
    assert p["scenes"][0]["end"] == 1.5


def test_persist_and_director_share_exact_scene_intervals(tmp_path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fixture-audio")
    with patch.object(np.utils, "task_dir", return_value=str(tmp_path)):
        p = np.prepare(
            "t",
            "City crowds. Quiet mountains.",
            str(audio),
            5,
            duration=4,
            maker=maker([(0, 1.5, "City crowds."), (1.5, 4, "Quiet mountains.")]),
        )
        with patch.object(
            llm, "generate_json_response", side_effect=AssertionError("network")
        ):
            directed = scene_planner.get_or_create_scene_plan(
                "t",
                "City crowds. Quiet mountains.",
                video_subject="Travel",
                audio_duration=4,
                max_scene_duration=5,
                aspect="9:16",
                narration_timeline=p,
                use_llm=False,
            )
        assert [s.target_duration for s in directed.scenes] == [1.5, 2.5]
        assert directed.scenes[1].narration_segment == "Quiet mountains."
        assert "City crowds" not in directed.scenes[1].prompt
        assert np.load("t")["audio_sha256"]
        # Same plan reload does not need the model.
        assert (
            scene_planner.get_or_create_scene_plan(
                "t",
                "City crowds. Quiet mountains.",
                video_subject="Travel",
                audio_duration=4,
                max_scene_duration=5,
                aspect="9:16",
                narration_timeline=p,
                use_llm=False,
            )
            == directed
        )


def test_stock_search_fails_specific_scene_without_borrowing_footage(tmp_path):
    data = np.build(
        "City crowds. Quiet mountains.",
        4,
        5,
        maker=maker([(0, 1.5, "City crowds."), (1.5, 4, "Quiet mountains.")]),
    )
    with patch.object(np.utils, "task_dir", return_value=str(tmp_path)):
        scene_planner._atomic_write_json(np.file("t"), data)
        with (
            patch.object(
                llm,
                "generate_json_response",
                return_value={
                    "scenes": [
                        {"scene_id": 1, "queries": ["city crowd"]},
                        {"scene_id": 2, "queries": ["quiet mountains"]},
                    ]
                },
            ),
            patch.object(
                material, "_search_videos_with_cache", return_value=[]
            ) as search,
            patch.object(material, "save_video") as download,
        ):
            with pytest.raises(ValueError, match="scene 1"):
                np.stock_materials("t", VideoParams(video_subject="Travel"))
            assert search.call_count == 1
            download.assert_not_called()
            assert np.load("t")["failed_scene_id"] == 1


def test_stock_rejects_wrong_scene_coverage_before_search(tmp_path):
    with patch.object(np.utils, "task_dir", return_value=str(tmp_path)):
        scene_planner._atomic_write_json(np.file("t"), np.build("Hello.", 2, 5))
        with (
            patch.object(
                llm,
                "generate_json_response",
                return_value={"scenes": [{"scene_id": 42, "queries": ["hello world"]}]},
            ),
            patch.object(material, "_search_videos_with_cache") as search,
        ):
            with pytest.raises(ValueError, match="IDs"):
                np.stock_materials("t", VideoParams(video_subject="Hello"))
            search.assert_not_called()


@pytest.mark.parametrize("source", ["pexels", "pixabay", "coverr"])
def test_stock_automatic_speed_preflight_before_any_speech(source):
    with patch.object(task.voice, "tts") as tts:
        result = task.start(
            "invalid-auto",
            VideoParams(
                video_subject="hello",
                video_source=source,
                local_ai_duration_mode="auto",
                video_clip_speed=1.5,
            ),
        )
        assert result["failed_stage"] == "preflight"
        tts.assert_not_called()


def test_short_stock_candidate_rejected_then_scene_alternative_used(tmp_path):
    from app.services import video

    params = VideoParams(video_subject="Flowers")
    with patch.object(np.utils, "task_dir", return_value=str(tmp_path)):
        scene_planner._atomic_write_json(np.file("t"), np.build("Flowers bloom.", 3, 5))
        item = SimpleNamespace(url="short", provider="pexels", source_info={})
        good = SimpleNamespace(url="long", provider="pexels", source_info={})

        class Clip:
            def __init__(self, duration):
                self.duration = duration

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch.object(
                llm,
                "generate_json_response",
                return_value={
                    "scenes": [
                        {"scene_id": 1, "queries": ["flowers bloom", "flower opening"]}
                    ]
                },
            ),
            patch.object(
                material, "_search_videos_with_cache", side_effect=[[item], [good]]
            ) as search,
            patch.object(material, "save_video", side_effect=["short.mp4", "long.mp4"]),
            patch.object(
                video, "_open_video_clip_quietly", side_effect=[Clip(1), Clip(4)]
            ),
            patch.object(material, "_material_source_record", return_value={}),
            patch.object(material, "_persist_material_sources"),
        ):
            assert np.stock_materials("t", params) == ["long.mp4"]
            assert search.call_count == 2
            assert np.load("t")["scenes"][0]["asset"] == "long.mp4"


from test.services.test_local_ai import LocalAITestCase  # noqa: E402


class TestAutomaticStockPipeline(LocalAITestCase):
    def test_real_stock_render_uses_planned_cut_and_never_global_keywords(self):
        from app.models.schema import VideoAspect
        from app.services import video
        from moviepy import ColorClip
        import numpy as numpy

        tid = "stock-timed"
        root = self.task_root / tid
        root.mkdir()
        paths = []
        for color, name in [((255, 0, 0), "red"), ((0, 0, 255), "blue")]:
            target = root / (name + ".mp4")
            clip = ColorClip((90, 160), color=color, duration=4)
            clip.write_videofile(
                str(target), fps=30, codec="libx264", audio=False, logger=None
            )
            clip.close()
            paths.append(str(target))

        def speech(**kwargs):
            self.make_audio(tid, 3.2)
            return maker([(0, 1.1, "City crowds."), (1.1, 3.2, "Quiet mountains.")])

        def search(**kwargs):
            item = SimpleNamespace(
                url=kwargs["search_term"], provider="pexels", source_info={}
            )
            return [item]

        with (
            patch.object(task.voice, "tts", side_effect=speech),
            patch.object(
                task, "generate_terms", side_effect=AssertionError("global search")
            ),
            patch.object(
                llm,
                "generate_json_response",
                return_value={
                    "scenes": [
                        {"scene_id": 1, "queries": ["city crowds"]},
                        {"scene_id": 2, "queries": ["quiet mountains"]},
                    ]
                },
            ),
            patch.object(material, "_search_videos_with_cache", side_effect=search),
            patch.object(material, "save_video", side_effect=paths),
            patch.object(material, "_material_source_record", return_value={}),
            patch.object(VideoAspect, "to_resolution", return_value=(90, 160)),
            patch.object(
                video, "combine_videos", wraps=video.combine_videos
            ) as combine,
        ):
            params = VideoParams(
                video_subject="Travel",
                video_script="City crowds. Quiet mountains.",
                video_source="pexels",
                local_ai_duration_mode="auto",
                video_clip_duration=1,
                subtitle_enabled=False,
                bgm_type="",
                n_threads=1,
            )
            result = task.start(tid, params)
            assert result["videos"], result
            assert combine.call_args.kwargs["scene_durations"][0] == 1.1
            with video._open_video_clip_quietly(result["videos"][0]) as final:
                before, after = (
                    numpy.mean(final.get_frame(0.7), axis=(0, 1)),
                    numpy.mean(final.get_frame(1.3), axis=(0, 1)),
                )
                assert before[0] > 200 and before[2] < 30
                assert after[2] > 200 and after[0] < 30
                assert abs(final.duration - 3.2) < 0.12
            timing = np.load(tid)
            assert timing["timing_source"] == "tts_cues"
            assert timing["scenes"][1]["queries"] == ["quiet mountains"]


def test_caption_and_scene_sentence_boundaries_share_tts_clock(tmp_path):
    from app.services import voice, subtitle

    m = maker([(0, 1.1, "Flowers open."), (1.4, 3.2, "Bees gather pollen.")])
    captions = tmp_path / "subtitle.srt"
    voice.create_subtitle(m, "Flowers open. Bees gather pollen.", str(captions))
    items = subtitle.file_to_subtitles(str(captions))
    assert items[0][1].endswith("00:00:01,100")
    p = np.build("Flowers open. Bees gather pollen.", 3.3, 5, maker=m)
    assert p["scenes"][0]["end"] == 1.1
    assert np.normalized(items[1][2]) == np.normalized(p["scenes"][1]["text"])


def test_varied_narration_cadence_preserves_coverage_and_provider_ceiling():
    import random

    rng = random.Random(42)
    for _ in range(50):
        rows = []
        at = 0
        for word in ["City", "crowds.", "Quiet", "mountains.", "Birds", "fly."]:
            length = rng.uniform(0.15, 2.5)
            rows.append((at, at + length, word))
            at += length
        p = np.build(
            "City crowds. Quiet mountains. Birds fly.",
            at,
            rng.choice([2.0, 3.0, 5.0]),
            maker=maker(rows),
        )
        assert sum(row["duration"] for row in p["scenes"]) == pytest.approx(at)
        assert all(
            1 / 30 <= row["duration"] <= p["maximum"] + 1e-6 for row in p["scenes"]
        )
        assert np.normalized(
            "".join(row["text"] for row in p["scenes"])
        ) == np.normalized("City crowds. Quiet mountains. Birds fly.")


def test_decimal_and_title_do_not_create_false_sentence_cuts():
    assert not np.sentence_end("Dr. Smith sees 3.14 stars.", 0, 4)
    text = "Dr. Smith sees 3.14 stars."
    assert not np.sentence_end(text, 0, text.index("3.") + 2)
    assert np.sentence_end(text, 0, len(text))


def test_corrupt_persisted_intervals_cannot_reach_renderer(tmp_path):
    with patch.object(np.utils, "task_dir", return_value=str(tmp_path)):
        data = np.build("Flowers bloom.", 3, 5)
        data["scenes"][0]["duration"] = -1
        scene_planner._atomic_write_json(np.file("t"), data)
        with pytest.raises(ValueError, match="intervals"):
            np.load("t")
