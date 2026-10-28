import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from app.services import facebook_accounts as accounts, facebook_direct as studio
from app.services import youtube_accounts, youtube_studio as legacy
from app.services.facebook_graph import FacebookPage, Graph, MetaError
from test.services import test_youtube_direct as fixtures
from webui.opencut_server import create_app

CID, GID, PAGE, USER, VIDEO = "c" * 32, "b" * 32, "12345678", "98765", "876543210"


@pytest.fixture
def facebook_setup():
    for f in fixtures.direct_setup.__wrapped__():
        with patch.dict(
            "os.environ",
            {
                k: ""
                for k in (
                    "MPT_FACEBOOK_APP_ID",
                    "MPT_FACEBOOK_APP_SECRET",
                    "MPT_FACEBOOK_REDIRECT_URI",
                    "MPT_FACEBOOK_GRAPH_VERSION",
                    "MPT_FACEBOOK_LOGIN_CONFIG_ID",
                )
            },
        ):
            accounts.configure(
                dict(
                    app_id="12345",
                    app_secret="meta-secret",
                    redirect_uri="http://127.0.0.1:8501" + accounts.CALLBACK,
                    version="v26.0",
                    config_id="",
                )
            )
            page = dict(
                page_id=PAGE,
                name="Garden Facebook",
                token="secret-page-token",
                can_publish=True,
            )
            data = accounts.vault()
            data["grants"][GID] = dict(
                id=GID,
                user_id=USER,
                token="secret-user-token",
                expires_at=time.time() + 3600,
                pages=[page],
                app=accounts.fingerprint(),
                reauth_required=False,
            )
            data["connections"][CID] = dict(
                id=CID,
                grant_id=GID,
                page_id=PAGE,
                name=page["name"],
                app=accounts.fingerprint(),
                checked_at=time.time(),
                reauth_required=False,
            )
            accounts.save(data)
            f.fb_opts = dict(
                title="Garden",
                description="Growing plants",
                media_type="VIDEO",
                synthetic=True,
            )
            with (
                patch.object(
                    FacebookPage,
                    "verify_page",
                    return_value=dict(page_id=PAGE, name=page["name"]),
                ) as verify,
                patch.object(studio, "enqueue") as enqueue,
                patch(
                    "requests.get",
                    side_effect=AssertionError("unexpected live Meta OAuth"),
                ),
            ):
                f.fb_verify, f.fb_enqueue = verify, enqueue
                yield f


def draft(f, **changes):
    return studio.prepare("test-video", "final-1.mp4", CID, f.fb_opts | changes)


def approved(f, **changes):
    job = draft(f, **changes)
    studio.approve(job["id"], True)
    return studio.get(job["id"])


def remote(**changes):
    return (
        dict(
            id=VIDEO,
            **{"from": {"id": PAGE}},
            published=True,
            title="Garden",
            description="Growing plants",
            updated_time="revision1",
            status={"video_status": "ready"},
            permalink_url="https://www.facebook.com/" + VIDEO,
        )
        | changes
    )


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


def session(job):
    return dict(
        video_id=VIDEO,
        upload_session_id="54321",
        start_offset="0",
        end_offset=str(job["size"]),
    )


def test_frozen_review_encryption_and_duplicate_guard(facebook_setup):
    f = facebook_setup
    job = draft(f)
    assert job["state"] == "draft" and not f.fb_enqueue.called
    with pytest.raises(ValueError, match="Review"):
        studio.approve(job["id"])
    assert (
        legacy.snapshot_file(job).read_bytes()
        == legacy.source_file("test-video", "final-1.mp4").read_bytes()
    )
    studio.approve(job["id"], True)
    assert studio.get(job["id"])["state"] == "queued"
    with pytest.raises(ValueError, match="already exists"):
        draft(f)
    raw = (accounts.directory() / "accounts.enc").read_bytes()
    assert all(
        secret.encode() not in raw
        for secret in ["secret-user-token", "secret-page-token", "meta-secret"]
    )
    assert not any("token" in k for k in accounts.connections()[0])
    assert youtube_accounts.connections()[0]["channel_id"] == fixtures.CHANNEL


def test_video_upload_uses_server_ranges_then_confirms_publication(facebook_setup):
    job = approved(facebook_setup)
    with (
        patch.object(FacebookPage, "initiate", return_value=session(job)) as start,
        patch.object(
            FacebookPage,
            "transfer",
            return_value=dict(
                start_offset=str(job["size"]), end_offset=str(job["size"])
            ),
        ) as transfer,
        patch.object(FacebookPage, "finish") as finish,
        patch.object(FacebookPage, "video", return_value=remote()),
    ):
        result = studio.dispatch(job["id"])
    assert result["state"] == "published" and result["offset"] == job["size"]
    start.assert_called_once()
    transfer.assert_called_once()
    finish.assert_called_once()
    assert "upload_session_id" not in result
    assert b"54321" not in studio._path(job["id"]).read_bytes()


def test_offset_conflict_recovers_existing_upload_without_duplicate(facebook_setup):
    job = approved(facebook_setup)
    done = dict(start_offset=str(job["size"]), end_offset=str(job["size"]))
    with (
        patch.object(FacebookPage, "initiate", return_value=session(job)) as start,
        patch.object(
            FacebookPage, "transfer", side_effect=MetaError(400, offsets=done)
        ),
        patch.object(FacebookPage, "finish"),
        patch.object(FacebookPage, "video", return_value=remote()),
    ):
        assert studio.dispatch(job["id"])["state"] == "published"
    start.assert_called_once()


def test_uncertain_initialization_is_not_restarted(facebook_setup):
    job = approved(facebook_setup)
    with patch.object(
        FacebookPage, "initiate", side_effect=MetaError(uncertain=True)
    ) as start:
        assert studio.dispatch(job["id"])["state"] == "unknown"
        with pytest.raises(ValueError, match="initialization"):
            studio.resume(job["id"], True)
    start.assert_called_once()


def test_uncertain_finish_never_blindly_republishes(facebook_setup):
    job = approved(facebook_setup)
    with (
        patch.object(FacebookPage, "initiate", return_value=session(job)),
        patch.object(
            FacebookPage,
            "transfer",
            return_value=dict(
                start_offset=str(job["size"]), end_offset=str(job["size"])
            ),
        ),
        patch.object(
            FacebookPage, "finish", side_effect=MetaError(uncertain=True)
        ) as finish,
        patch.object(FacebookPage, "video", return_value=remote(published=False)),
    ):
        assert studio.dispatch(job["id"])["state"] == "unknown"
        with pytest.raises(ValueError, match="already requested"):
            studio.resume(job["id"], True)
    finish.assert_called_once()


def test_reel_uncertain_transfer_needs_status_confirmation(facebook_setup):
    f = facebook_setup
    job = approved(f)
    raw = studio._get(job["id"])
    raw["options"]["media_type"] = "REELS"
    studio._write(raw)
    with (
        patch.object(
            FacebookPage,
            "initiate",
            return_value=dict(
                video_id=VIDEO,
                upload_url="https://rupload.facebook.com/video-upload/v26.0/" + VIDEO,
            ),
        ) as start,
        patch.object(
            FacebookPage, "transfer", side_effect=MetaError(uncertain=True)
        ) as transfer,
        patch.object(
            FacebookPage,
            "video",
            return_value=remote(
                published=False, status={"uploading_phase": {"status": "in_progress"}}
            ),
        ),
    ):
        assert studio.dispatch(job["id"])["state"] == "unknown"
        with pytest.raises(ValueError, match="cannot be resent"):
            studio.resume(job["id"], True)
    with patch.object(
        FacebookPage,
        "video",
        return_value=remote(
            published=False, status={"uploading_phase": {"status": "complete"}}
        ),
    ):
        studio.resume(job["id"], True)
    with (
        patch.object(FacebookPage, "transfer") as never,
        patch.object(FacebookPage, "finish"),
        patch.object(FacebookPage, "video", return_value=remote()),
    ):
        assert studio.dispatch(job["id"])["state"] == "published"
        never.assert_not_called()
    start.assert_called_once()
    transfer.assert_called_once()


def test_schedule_requires_actual_remote_confirmation(facebook_setup):
    when = int(time.time()) + 7200
    job = approved(facebook_setup, scheduled_at=when)
    with (
        patch.object(FacebookPage, "initiate", return_value=session(job)),
        patch.object(
            FacebookPage,
            "transfer",
            return_value=dict(
                start_offset=str(job["size"]), end_offset=str(job["size"])
            ),
        ),
        patch.object(FacebookPage, "finish"),
        patch.object(
            FacebookPage,
            "video",
            return_value=remote(published=False, scheduled_publish_time=when),
        ),
    ):
        assert studio.dispatch(job["id"])["state"] == "scheduled"
    with patch.object(
        FacebookPage,
        "video",
        return_value=remote(published=False, scheduled_publish_time=when + 60),
    ):
        assert studio.refresh(job["id"])["state"] != "scheduled"


def test_elapsed_schedule_blocks_finish_and_can_be_explicitly_rescheduled(
    facebook_setup,
):
    job = approved(facebook_setup, scheduled_at=int(time.time()) + 7200)
    raw = studio._get(job["id"])
    raw.update(video_id=VIDEO, upload_session_id="54321", transfer_complete=True)
    raw["options"]["scheduled_at"] = int(time.time()) - 1
    studio._write(raw)
    with patch.object(FacebookPage, "finish") as finish:
        assert studio.dispatch(job["id"])["state"] == "blocked"
        finish.assert_not_called()
    when = int(time.time()) + 10800
    with (
        patch.object(
            FacebookPage,
            "video",
            return_value=remote(published=False, scheduled_publish_time=when),
        ),
        patch.object(FacebookPage, "finish") as finish,
    ):
        assert studio.reschedule(job["id"], when, True)["state"] == "scheduled"
        finish.assert_called_once()


def test_cancel_requires_confirmed_unpublished_and_delete_ack(facebook_setup):
    job = approved(facebook_setup)
    raw = studio._get(job["id"])
    raw.update(state="paused", video_id=VIDEO)
    studio._write(raw)
    with (
        patch.object(FacebookPage, "video", return_value=remote()),
        patch.object(FacebookPage, "delete") as delete,
    ):
        with pytest.raises(ValueError, match="unpublished"):
            studio.cancel(job["id"], True)
        delete.assert_not_called()
    with (
        patch.object(FacebookPage, "video", return_value=remote(published=False)),
        patch.object(FacebookPage, "delete", side_effect=MetaError(uncertain=True)),
    ):
        with pytest.raises(MetaError):
            studio.cancel(job["id"], True)
    assert studio.get(job["id"])["state"] == "unknown"
    with (
        patch.object(FacebookPage, "video", return_value=remote(published=False)),
        patch.object(FacebookPage, "delete"),
    ):
        assert studio.cancel(job["id"], True)["state"] == "cancelled"
    assert legacy.snapshot_file(job).is_file()


def test_metadata_review_stale_guard_and_exact_delete(facebook_setup):
    with (
        patch.object(FacebookPage, "video", return_value=remote()),
        patch.object(FacebookPage, "update") as update,
    ):
        with pytest.raises(ValueError, match="changed since"):
            studio.edit_video(CID, VIDEO, "New", "Description", True, "old")
        studio.edit_video(CID, VIDEO, "New", "Description", True, "revision1")
        update.assert_called_once_with(VIDEO, name="New", description="Description")
    with pytest.raises(ValueError, match="exact"):
        studio.delete_video(CID, VIDEO, "wrong")
    with (
        patch.object(FacebookPage, "video", return_value=remote()),
        patch.object(FacebookPage, "delete") as delete,
    ):
        studio.delete_video(CID, VIDEO, VIDEO)
        delete.assert_called_once_with(VIDEO)


def test_graph_uses_fixed_hosts_proof_no_redirect_and_safe_errors(facebook_setup):
    graph = Graph("secret-page-token", accounts.settings())
    with patch("requests.request", return_value=response({"success": True})) as request:
        graph.request(
            "POST", PAGE + "/videos", video_upload=True, data={"upload_phase": "start"}
        )
        args, kw = request.call_args
        assert args[1] == "https://graph-video.facebook.com/v26.0/" + PAGE + "/videos"
        assert (
            kw["allow_redirects"] is False
            and kw["headers"]["Authorization"] == "Bearer secret-page-token"
        )
        assert len(kw["params"]["appsecret_proof"]) == 64
    with pytest.raises(ValueError):
        graph.request("GET", "https://evil.example/")
    with patch(
        "requests.request",
        return_value=response({"error": {"code": 190, "message": "secret-token"}}, 400),
    ):
        with pytest.raises(MetaError) as exc:
            graph.request("GET", "me")
        assert "secret-token" not in str(exc.value) and exc.value.code == 190
    with patch("requests.request", side_effect=requests.Timeout()):
        with pytest.raises(MetaError) as exc:
            graph.request("POST", PAGE)
        assert exc.value.uncertain


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/video-upload/v26.0/" + VIDEO,
        "https://rupload.facebook.com@evil.example/" + VIDEO,
        "http://rupload.facebook.com/video-upload/v26.0/" + VIDEO,
        "https://rupload.facebook.com/video-upload/v26.0/" + VIDEO + "?token=x",
    ],
)
def test_reel_upload_endpoint_rejects_foreign_targets(facebook_setup, url):
    with pytest.raises(ValueError):
        FacebookPage.upload_url(url, VIDEO)


def test_page_listing_uses_opaque_cursor_not_next_url(facebook_setup):
    page = dict(
        id=PAGE,
        name="Garden",
        access_token="secret-page-token",
        tasks=["CREATE_CONTENT"],
    )
    with patch(
        "requests.request",
        side_effect=[
            response(
                {
                    "data": [page],
                    "paging": {
                        "next": "https://evil.example",
                        "cursors": {"after": "cursor"},
                    },
                }
            ),
            response({"data": []}),
        ],
    ) as request:
        assert Graph("token", accounts.settings()).pages()[0]["can_publish"]
    assert request.call_args.args[1].startswith("https://graph.facebook.com/")
    assert request.call_args.kwargs["params"]["after"] == "cursor"


def test_oauth_browser_binding_single_use_and_explicit_page_attach(facebook_setup):
    data = accounts.vault()
    data["grants"] = {}
    data["connections"] = {}
    accounts.save(data)
    url, state, browser = accounts.begin(
        parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    )
    query = parse_qs(urlsplit(url).query)
    assert (
        query["response_type"] == ["code"]
        and set(query["scope"][0].split(" ")) == accounts.SCOPES
    )
    with pytest.raises(ValueError):
        accounts.finish(state, "wrong-browser", "code")
    pages = [
        dict(page_id=PAGE, name="Garden", token="secret-page-token", can_publish=True)
    ]

    def graph_request(_self, method, path, **kw):
        if path == "me/permissions":
            return {
                "data": [dict(permission=p, status="granted") for p in accounts.SCOPES]
            }
        if path == "me":
            return {"id": USER}
        raise AssertionError(path)

    with (
        patch.object(
            accounts,
            "_exchange",
            side_effect=[
                {"access_token": "short"},
                {"access_token": "long", "expires_in": 3600},
            ],
        ),
        patch.object(Graph, "request", graph_request),
        patch.object(Graph, "pages", return_value=pages),
    ):
        accounts.finish(state, browser, "code")
        assert not accounts.connections()
        gid = accounts.grants()[0]["id"]
        cid = accounts.attach(gid, PAGE)
        assert accounts.connections()[0]["page_id"] == PAGE
        assert accounts.attach(gid, PAGE) == cid
        with pytest.raises(ValueError):
            accounts.finish(state, browser, "code")


def test_gateway_cookie_is_meta_bound_and_callback_redirects_to_facebook(
    facebook_setup,
):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8501")
    ticket = accounts.connect_ticket()
    start = client.get(ticket, follow_redirects=False)
    assert (
        start.status_code == 303 and "httponly" in start.headers["set-cookie"].lower()
    )
    query = parse_qs(urlsplit(start.headers["location"]).query)
    state = query["state"][0]
    with patch.object(accounts, "finish") as finish:
        result = client.get(
            accounts.CALLBACK,
            params={"state": state, "code": "secret-code"},
            follow_redirects=False,
        )
    assert (
        result.status_code == 303 and "platform=facebook" in result.headers["location"]
    )
    assert finish.call_args.args[1] and result.headers["cache-control"] == "no-store"
    assert "secret-code" not in result.text


def test_expired_and_revoked_permissions_require_reauthorization(facebook_setup):
    data = accounts.vault()
    data["grants"][GID]["expires_at"] = time.time() - 1
    accounts.save(data)
    assert accounts.connections()[0]["reauth_required"]
    with pytest.raises(ValueError):
        accounts.credential_record(CID)


def test_disconnect_does_not_touch_youtube_and_preserves_local_video(facebook_setup):
    job = draft(facebook_setup)
    with patch.object(Graph, "request", return_value={"success": True}) as request:
        assert accounts.disconnect(GID)
    assert not accounts.connections() and not studio.jobs()
    request.assert_called_once_with("DELETE", USER + "/permissions")
    assert youtube_accounts.connections()[0]["channel_id"] == fixtures.CHANNEL
    assert legacy.snapshot_file(job).exists()


def test_disconnect_blocks_pending_delivery_and_expired_token_is_not_claimed_revoked(
    facebook_setup,
):
    job = approved(facebook_setup)
    with pytest.raises(ValueError, match="pending"):
        accounts.disconnect(GID)
    studio.cancel(job["id"], True)
    with patch.object(Graph, "request", side_effect=MetaError(400, 190)):
        assert accounts.disconnect(GID) is False


def test_schedule_policy_and_reel_media_constraints(facebook_setup):
    with pytest.raises(ValueError, match="15 minutes"):
        draft(facebook_setup, scheduled_at=int(time.time()) + 60)
    with pytest.raises(ValueError, match="Reels"):
        draft(facebook_setup, media_type="REELS")
    with patch.object(
        legacy.video,
        "_open_video_clip_quietly",
        return_value=Mock(duration=5, size=(540, 960), w=540, h=960, fps=30),
    ):
        assert draft(facebook_setup, media_type="REELS")["state"] == "draft"


def test_real_mp4_snapshot_and_graph_upload_bytes(facebook_setup):
    import subprocess
    from moviepy import VideoFileClip
    from app.utils import utils

    f = facebook_setup
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
            str(f.source),
        ],
        check=True,
    )
    original = f.source.read_bytes()
    with (
        patch.object(
            legacy.video,
            "_open_video_clip_quietly",
            side_effect=lambda name: VideoFileClip(name, audio=False),
        ),
        patch.object(legacy.video, "close_clip", side_effect=lambda clip: clip.close()),
    ):
        job = approved(f)
    f.source.unlink()
    phases = []

    def wire(method, url, **kw):
        if method == "GET":
            assert url == "https://graph.facebook.com/v26.0/" + VIDEO
            return response(remote())
        assert url == "https://graph-video.facebook.com/v26.0/" + PAGE + "/videos"
        data = kw["data"]
        phase = data["upload_phase"]
        phases.append(phase)
        if phase == "start":
            return response(session(job))
        if phase == "transfer":
            assert kw["files"]["video_file_chunk"][1] == original
            assert data["start_offset"] == "0"
            return response(
                dict(start_offset=str(len(original)), end_offset=str(len(original)))
            )
        assert data["published"] == "true"
        return response({"success": True})

    with patch("requests.request", side_effect=wire):
        assert studio.dispatch(job["id"])["state"] == "published"
    assert phases == ["start", "transfer", "finish"]


def test_real_webm_is_converted_to_reviewed_mp4_before_upload(facebook_setup):
    import subprocess
    from moviepy import VideoFileClip
    from app.utils import utils

    f = facebook_setup
    webm = f.root / "final-2.webm"
    subprocess.run(
        [
            utils.get_ffmpeg_binary(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x288:r=24:d=1",
            "-t",
            "1",
            "-c:v",
            "libvpx-vp9",
            "-threads",
            "1",
            str(webm),
        ],
        check=True,
    )
    original = webm.read_bytes()
    # Native exports are only accepted when they are retained task artifacts.
    with patch.object(legacy, "source_file", return_value=webm):
        with (
            patch.object(
                legacy.video,
                "_open_video_clip_quietly",
                side_effect=lambda name: VideoFileClip(name, audio=False),
            ),
            patch.object(
                legacy.video, "close_clip", side_effect=lambda clip: clip.close()
            ),
        ):
            job = studio.prepare("test-video", "final-2.webm", CID, f.fb_opts)
    frozen = legacy.snapshot_file(job)
    assert frozen.suffix == ".mp4" and frozen.read_bytes() != original
    assert job["source_sha256"] != job["sha256"] and job["state"] == "draft"
    with VideoFileClip(str(frozen), audio=False) as clip:
        assert clip.duration > 0 and clip.size == [160, 288]
    assert webm.read_bytes() == original


def test_reel_wire_payload_and_schedule(facebook_setup):
    job = draft(facebook_setup)
    job["options"].update(media_type="REELS", scheduled_at=int(time.time()) + 7200)
    job["video_id"] = VIDEO
    job["upload_url"] = "https://rupload.facebook.com/video-upload/v26.0/" + VIDEO
    client = FacebookPage(CID)
    with patch("requests.post", return_value=response({"success": True})) as upload:
        client.transfer(job, legacy.snapshot_file(job))
        assert upload.call_args.kwargs["headers"]["file_size"] == str(job["size"])
        assert upload.call_args.kwargs["allow_redirects"] is False
    with patch("requests.request", return_value=response({"success": True})) as finish:
        client.finish(job)
        data = finish.call_args.kwargs["data"]
        assert data["video_state"] == "SCHEDULED" and data["video_id"] == VIDEO
        assert data["is_ai_generated"] == "true"
        assert data["scheduled_publish_time"] == str(job["options"]["scheduled_at"])


def test_oauth_missing_permissions_and_expired_state_never_attach(facebook_setup):
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    _, state, browser = accounts.begin(ticket)
    with (
        patch.object(accounts, "_exchange", return_value={"access_token": "new-token"}),
        patch.object(Graph, "request", return_value={"data": []}),
    ):
        with pytest.raises(ValueError, match="permissions"):
            accounts.finish(state, browser, "code")
    assert len(accounts.connections()) == 1  # Existing grant remains intact.
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    with patch.object(accounts.time, "time", return_value=time.time() + 601):
        with pytest.raises(ValueError):
            accounts.begin(ticket)


def test_recovery_preserves_existing_id_and_blocks_unknown_initialization_cancel(
    facebook_setup,
):
    job = approved(facebook_setup)
    raw = studio._get(job["id"])
    raw.update(state="initiating")
    studio._write(raw)
    studio.recover()
    assert studio.get(job["id"])["state"] == "unknown"
    with pytest.raises(ValueError, match="initialization"):
        studio.cancel(job["id"], True)
    raw = studio._get(job["id"])
    raw.update(state="uploading", video_id=VIDEO)
    studio._write(raw)
    studio.recover()
    assert studio.get(job["id"])["state"] == "paused"
    assert studio.get(job["id"])["video_id"] == VIDEO


def test_malformed_successful_start_blocks_replacement(facebook_setup):
    job = approved(facebook_setup)
    with patch(
        "requests.request", return_value=response({"video_id": VIDEO})
    ) as request:
        assert studio.dispatch(job["id"])["state"] == "unknown"
        with pytest.raises(ValueError, match="initialization"):
            studio.resume(job["id"], True)
    request.assert_called_once()
