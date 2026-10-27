import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import content_library as lib, publishing_seo as seo
from app.services import youtube_direct as youtube, facebook_direct as facebook
from test.services import test_facebook_direct as fixture
from test.services.test_publishing_seo import payload

YT = "youtube:" + fixture.fixtures.CID
FB = "facebook:" + fixture.CID


@pytest.fixture
def setup_library():
    for f in fixture.facebook_setup.__wrapped__():
        with (
            patch.object(lib, "enqueue") as queue,
            patch("app.services.state.state.get_task", return_value=None),
        ):
            f.library_queue = queue
            f.tasks_ids = []
            for i in range(5):
                tid = "ready-" + str(i)
                directory = f.tasks / tid
                directory.mkdir()
                (directory / "script.json").write_text(
                    json.dumps(
                        {
                            "script": "Plant seeds and water the garden.",
                            "params": {"video_subject": "Garden " + str(i)},
                        }
                    )
                )
                (directory / "final-1.mp4").write_bytes(
                    ("video-content-" + str(i)).encode()
                )
                f.tasks_ids.append(tid)
            youtube_defaults = f.opts | {"privacy": "public", "category": "22"}
            lib.save_preset(
                YT,
                "Asia/Karachi",
                ["12:00", "19:00"],
                list(range(7)),
                youtube_defaults,
                thumbnail=False,
            )
            lib.save_preset(
                FB,
                "Asia/Karachi",
                ["13:00", "20:00"],
                list(range(7)),
                f.fb_opts,
                thumbnail=False,
            )
            yield f


def ready(f):
    for tid in f.tasks_ids:
        lib.select_final(tid, "final-1.mp4", True)


def prepare(f, keys=None, mode="slots"):
    ready(f)
    value = lib.create_batch(f.tasks_ids, keys or [YT, FB], mode)
    with patch.object(seo.llm, "generate_json_response", return_value=payload()):
        lib.prepare_batch(value["id"])
    return lib.batch(value["id"])


def test_library_groups_original_and_exports_and_editing_is_optional(setup_library):
    f = setup_library
    tid = f.tasks_ids[0]
    exports = f.tasks / tid / "opencut/exports"
    exports.mkdir(parents=True)
    (exports / ("a" * 32 + ".mp4")).write_bytes(b"edited-video")
    project = next(p for p in lib.projects() if p["task_id"] == tid)
    assert (
        len(project["versions"]) == 2
        and project["source"] == "final-1.mp4"
        and not project["ready"]
    )
    lib.select_final(tid, "final-1.mp4", True)
    assert next(p for p in lib.projects() if p["task_id"] == tid)["ready"]
    lib.select_final(tid, "opencut/exports/" + "a" * 32 + ".mp4")
    assert not next(p for p in lib.projects() if p["task_id"] == tid)["ready"]


def test_five_videos_create_ten_drafts_without_approving_or_uploading(setup_library):
    f = setup_library
    value = prepare(f)
    assert len(value["items"]) == 10 and all(
        i["state"] == "review" for i in value["items"]
    )
    assert len(youtube.jobs()) == 5 and len(facebook.jobs()) == 5
    assert all(j["state"] == "draft" for j in youtube.jobs() + facebook.jobs())
    f.enqueue.assert_not_called()
    f.fb_enqueue.assert_not_called()
    for key in [YT, FB]:
        times = [
            i["options"]["scheduled_at"]
            for i in value["items"]
            if i["destination"]["key"] == key
        ]
        assert len(set(times)) == 5
    assert lib.batch(value["id"]) == value


def test_batch_requires_review_and_rejects_stale_review_revision(setup_library):
    value = prepare(setup_library, [YT])
    item = value["items"][0]
    with pytest.raises(ValueError, match="Review"):
        lib.approve_batch(value["id"], revision=value["revision"])
    lib.edit_item(
        value["id"], item["id"], item["options"] | {"title": "Reviewed changed title"}
    )
    with pytest.raises(ValueError, match="batch changed"):
        lib.approve_batch(value["id"], True, value["revision"])
    current = lib.batch(value["id"])
    lib.approve_batch(value["id"], True, current["revision"])
    assert all(j["state"] == "queued" for j in youtube.jobs())


def test_changed_final_blocks_only_affected_posts(setup_library):
    f = setup_library
    value = prepare(f)
    tid = f.tasks_ids[0]
    (f.tasks / tid / "final-2.mp4").write_bytes(b"another-final")
    lib.select_final(tid, "final-2.mp4", True)
    result = lib.approve_batch(value["id"], True, value["revision"])
    blocked = [i for i in result["items"] if i["state"] == "blocked"]
    assert len(blocked) == 2 and {i["task_id"] for i in blocked} == {tid}
    assert sum(j["state"] == "queued" for j in youtube.jobs() + facebook.jobs()) == 8


def test_prepare_failure_is_isolated_and_retry_reuses_existing_draft(setup_library):
    f = setup_library
    ready(f)
    value = lib.create_batch(f.tasks_ids, [YT, FB], "now")
    original = seo.generate

    def generate(tid, relative, platform, **kwargs):
        if platform == "facebook":
            raise ValueError("Reconnect Facebook")
        return original(tid, relative, platform, **kwargs)

    with (
        patch.object(seo, "generate", side_effect=generate),
        patch.object(seo.llm, "generate_json_response", return_value=payload()),
    ):
        lib.prepare_batch(value["id"])
    value = lib.batch(value["id"])
    assert sum(i["state"] == "review" for i in value["items"]) == 5
    assert sum(i["state"] == "error" for i in value["items"]) == 5
    count = len(youtube.jobs())
    lib.prepare_batch(value["id"])
    assert len(youtube.jobs()) == count
    failed = next(i for i in value["items"] if i["state"] == "error")
    lib.retry_item(value["id"], failed["id"])
    with patch.object(seo.llm, "generate_json_response", return_value=payload()):
        lib.prepare_batch(value["id"])
    assert len(facebook.jobs()) == 1


def test_recovery_adopts_child_after_lost_parent_link_and_never_reapproves(
    setup_library,
):
    f = setup_library
    value = prepare(f, [YT])
    item = value["items"][0]
    child = youtube.get(item["delivery_id"])
    value["items"][0].update(state="preparing", delivery_id=None)
    lib._write(value)
    lib.recover()
    lib.prepare_batch(value["id"])
    current = lib.batch(value["id"])
    assert (
        current["items"][0]["delivery_id"] == child["id"] and len(youtube.jobs()) == 5
    )
    youtube.approve(child["id"], True)
    with patch.object(youtube, "approve") as approve:
        lib.approve_batch(current["id"], True, current["revision"])
        assert child["id"] not in [c.args[0] for c in approve.call_args_list]


def test_unapproved_duplicate_is_blocked_and_exclusion_releases_plan(setup_library):
    f = setup_library
    ready(f)
    value = lib.create_batch([f.tasks_ids[0]], [YT])
    with pytest.raises(ValueError, match="already has"):
        lib.create_batch([f.tasks_ids[0]], [YT])
    lib.exclude_item(value["id"], value["items"][0]["id"])
    other = lib.create_batch([f.tasks_ids[0]], [YT])
    assert other["id"] != value["id"]


def test_exact_start_spreads_videos_and_respects_account_slots(setup_library):
    f = setup_library
    ready(f)
    exact = (
        (datetime.now(timezone.utc) + timedelta(days=1))
        .replace(second=0, microsecond=0)
        .isoformat()
    )
    value = lib.create_batch(f.tasks_ids, [YT, FB], "exact", exact, 30)
    for key in [YT, FB]:
        dates = [
            lib._when(i["options"]["scheduled_at"])
            for i in value["items"]
            if i["destination"]["key"] == key
        ]
        assert dates[1] - dates[0] == timedelta(minutes=30)
    with pytest.raises(ValueError, match="first"):
        lib.create_batch(["test-video"], [YT], "now")


def test_auto_preparation_is_opt_in_once_per_version_and_never_publishes(setup_library):
    f = setup_library
    lib.discover_automatic()
    assert not lib.catalog()["auto"]
    lib.set_automatic(True)
    lib.completed(f.tasks_ids[0])
    entries = lib.catalog()["auto"]
    assert len(entries) == 2
    with patch.object(
        seo.llm, "generate_json_response", return_value=payload()
    ) as model:
        for key in entries:
            lib._prepare_auto(key)
        lib.completed(f.tasks_ids[0])
        assert model.call_count == 2
    assert all(i["state"] == "prepared" for i in lib.catalog()["auto"].values())
    assert not youtube.jobs() and not facebook.jobs()
    assert not lib.catalog()["finals"]
    lib.set_automatic(False)
    lib.completed(f.tasks_ids[1])
    assert len(lib.catalog()["auto"]) == 2


def test_slot_allocation_skips_dst_fold_and_missing_slots(setup_library):
    preset = lib.catalog()["presets"][YT] | dict(
        timezone="Europe/London", times=["01:30", "03:00"], days=list(range(7))
    )
    now = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    result = lib.next_slot(preset, set(), now)
    assert datetime.fromisoformat(result).hour == 3
    with pytest.raises(ValueError, match="No available"):
        lib.next_slot(preset | {"times": []}, set(), now)


def test_catalog_is_encrypted_and_queue_recovery_never_approves(setup_library):
    f = setup_library
    value = prepare(f, [YT])
    assert b"Garden" not in (lib.root() / "catalog.enc").read_bytes()
    assert b"Garden" not in lib._path(value["id"]).read_bytes()
    with patch.object(youtube, "approve") as approve:
        lib.recover()
        approve.assert_not_called()
    assert not f.enqueue.called


def test_approved_post_resume_and_cancel_use_same_id(setup_library):
    value = prepare(setup_library, [YT])
    item = value["items"][0]
    lib.approve_batch(value["id"], True, value["revision"])
    with patch.object(
        youtube, "resume", return_value=youtube.get(item["delivery_id"])
    ) as resume:
        lib.delivery_action(value["id"], item["id"], "resume", True)
        resume.assert_called_once_with(item["delivery_id"], True)
    lib.delivery_action(value["id"], item["id"], "cancel", True)
    assert youtube.get(item["delivery_id"])["state"] == "cancelled"
    assert len(youtube.jobs()) == 5


def test_concurrent_batches_reserve_distinct_slots(setup_library):
    from concurrent.futures import ThreadPoolExecutor

    f = setup_library
    ready(f)
    with ThreadPoolExecutor(max_workers=2) as workers:
        a = workers.submit(lib.create_batch, f.tasks_ids[:2], [YT])
        b = workers.submit(lib.create_batch, f.tasks_ids[2:4], [YT])
        values = [a.result(), b.result()]
    dates = [i["options"]["scheduled_at"] for value in values for i in value["items"]]
    assert len(set(dates)) == 4


def test_summary_override_is_bound_to_final_revision_and_model_input(setup_library):
    f = setup_library
    tid = f.tasks_ids[0]
    final = lib.select_final(
        tid, "final-1.mp4", True, "This export only shows watering plants."
    )
    value = lib.create_batch([tid], [YT], "now")
    with patch.object(
        seo.llm, "generate_json_response", return_value=payload()
    ) as model:
        lib.prepare_batch(value["id"])
    assert "This export only shows watering plants." in model.call_args.args[0]
    assert model.call_args.kwargs["app_config"]
    assert "app_config" not in lib.batch(value["id"])["items"][0]
    updated = lib.select_final(tid, "final-1.mp4", True, "An updated factual summary.")
    assert updated["revision"] > final["revision"]
    with pytest.raises(ValueError, match="changed"):
        lib._final(tid, final)


def test_foreign_thumbnail_and_format_edits_require_fresh_review(setup_library):
    value = prepare(setup_library, [FB])
    item = value["items"][0]
    with pytest.raises(ValueError, match="format"):
        lib.edit_item(
            value["id"], item["id"], item["options"] | {"media_type": "REELS"}
        )
    with pytest.raises(ValueError, match="YouTube"):
        lib.replace_thumbnail(value["id"], item["id"], "Text")


def test_processing_tasks_and_partial_exports_do_not_become_ready(setup_library):
    f = setup_library
    tid = f.tasks_ids[0]
    exports = f.tasks / tid / "opencut/exports"
    exports.mkdir(parents=True)
    (exports / ".incomplete.mp4").write_bytes(b"partial")
    assert any(p["task_id"] == tid for p in lib.projects())
    with patch("app.services.state.state.get_task", return_value={"state": 4}):
        assert not lib.projects()
        with pytest.raises(ValueError, match="processing"):
            lib.select_final(tid, "final-1.mp4", True)


def test_time_and_batch_limits_do_not_create_any_delivery(setup_library):
    f = setup_library
    ready(f)
    with pytest.raises(ValueError, match="timezone"):
        lib.create_batch([f.tasks_ids[0]], [YT], "exact", "2026-11-01T12:00:00")
    with pytest.raises(ValueError, match="fifty"):
        lib.create_batch(list(map(str, range(51))), [YT])
    assert not youtube.jobs() and not facebook.jobs()


def test_row_refresh_shows_real_delivery_and_cancel_releases_reservation(setup_library):
    f = setup_library
    value = prepare(f, [YT])
    item = value["items"][0]
    lib.approve_batch(value["id"], True, value["revision"])
    lib.delivery_action(value["id"], item["id"], "cancel", True)
    other = lib.create_batch([item["task_id"]], [YT])
    assert other["id"] != value["id"]
    row = next(r for r in lib.delivery_rows() if r["id"] == item["id"])
    assert row["delivery"]["state"] == "cancelled"


def test_real_cpu_video_prepares_reviewed_thumbnail_and_two_platform_posts(
    setup_library,
):
    import subprocess
    from moviepy import VideoFileClip
    from app.utils import utils
    from app.services.youtube_google import GoogleYouTube
    from app.services.facebook_graph import FacebookPage

    f = setup_library
    tid = f.tasks_ids[0]
    source = f.tasks / tid / "final-1.mp4"
    subprocess.run(
        [
            utils.get_ffmpeg_binary(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x288:r=24:d=1",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
    )
    lib.select_final(tid, "final-1.mp4", True)
    p = lib.catalog()["presets"][YT]
    lib.save_preset(
        YT, p["timezone"], p["times"], p["days"], p["defaults"], thumbnail=True
    )
    value = lib.create_batch([tid], [YT, FB], "now")
    with (
        patch.object(seo.llm, "generate_json_response", return_value=payload()),
        patch.object(
            media := seo.legacy.video,
            "_open_video_clip_quietly",
            side_effect=lambda name: VideoFileClip(name, audio=False),
        ),
        patch.object(media, "close_clip", side_effect=lambda clip: clip.close()),
    ):
        lib.prepare_batch(value["id"])
    value = lib.batch(value["id"])
    assert all(i["state"] == "review" for i in value["items"])
    yt = next(i for i in value["items"] if i["destination"]["key"] == YT)
    fb = next(i for i in value["items"] if i["destination"]["key"] == FB)
    yt_job = youtube.get(yt["delivery_id"])
    assert yt_job["thumbnail"] and seo.thumbnail_file(yt_job["thumbnail"]).is_file()
    lib.approve_batch(value["id"], True, value["revision"])
    google = fixture.fixtures
    with (
        patch.object(GoogleYouTube, "initiate", return_value=google.URI),
        patch.object(GoogleYouTube, "probe", return_value=google.response()),
        patch.object(
            GoogleYouTube,
            "chunk",
            return_value=google.response(
                201, {"id": google.VIDEO, "snippet": {"channelId": google.CHANNEL}}
            ),
        ),
        patch.object(
            GoogleYouTube, "owned_video", return_value=google.remote(privacy="public")
        ),
        patch.object(youtube, "set_thumbnail") as thumb,
    ):
        assert youtube.dispatch(yt["delivery_id"])["state"] == "published"
        thumb.assert_called_once()
    fb_job = facebook.get(fb["delivery_id"])
    with (
        patch.object(FacebookPage, "initiate", return_value=fixture.session(fb_job)),
        patch.object(
            FacebookPage,
            "transfer",
            return_value={
                "start_offset": str(fb_job["size"]),
                "end_offset": str(fb_job["size"]),
            },
        ),
        patch.object(FacebookPage, "finish"),
        patch.object(FacebookPage, "video", return_value=fixture.remote()),
    ):
        assert facebook.dispatch(fb["delivery_id"])["state"] == "published"
    assert {r["delivery"]["state"] for r in lib.delivery_rows()} == {"published"}


def test_gateway_startup_recovers_but_never_approves_new_drafts(setup_library):
    from fastapi.testclient import TestClient
    from webui.opencut_server import create_app

    value = prepare(setup_library, [YT])
    with patch.object(youtube, "approve") as approve:
        with TestClient(create_app()):
            pass
        approve.assert_not_called()
    assert all(j["state"] == "draft" for j in youtube.jobs())
    assert lib.batch(value["id"])["revision"] == value["revision"]


def test_native_status_polling_is_bounded_and_fair_after_errors(setup_library):
    from unittest.mock import Mock

    rows = [
        {
            "destination": {"platform": "youtube"},
            "delivery": {
                "id": str(i),
                "video_id": "known-id",
                "state": "processing",
                "checked_at": 0,
                "options": {},
            },
        }
        for i in range(8)
    ]
    client = Mock()
    client.refresh.side_effect = ValueError("Reconnect")
    with (
        patch.object(lib, "delivery_rows", return_value=rows),
        patch.object(lib, "service", return_value=client),
        patch.dict(lib._last_poll, {}, clear=True),
    ):
        lib.refresh_pending()
        assert client.refresh.call_count == 5
        lib.refresh_pending()
        assert client.refresh.call_count == 8


def test_new_library_final_never_replaces_an_already_approved_snapshot(setup_library):
    f = setup_library
    value = prepare(f, [YT])
    item = value["items"][0]
    lib.approve_batch(value["id"], True, value["revision"])
    before = youtube.get(item["delivery_id"])
    original = lib.media.snapshot_file(before).read_bytes()
    (f.tasks / item["task_id"] / "final-2.mp4").write_bytes(b"changed-finished-video")
    lib.select_final(item["task_id"], "final-2.mp4", True)
    after = youtube.get(item["delivery_id"])
    assert after["state"] == "queued" and after["sha256"] == before["sha256"]
    assert lib.media.snapshot_file(after).read_bytes() == original
