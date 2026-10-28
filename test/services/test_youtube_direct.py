import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

import pytest
import requests
from google.oauth2.credentials import Credentials
from fastapi.testclient import TestClient

from app.services import (
    youtube_accounts as accounts,
    youtube_direct as studio,
    youtube_studio as legacy,
)
from app.services.youtube_google import GoogleYouTube, YouTubeError, session_url
from test.services import test_youtube_studio as old_fixtures
from webui.opencut_server import create_app

CID = "a" * 32
CHANNEL = "UC" + "a" * 22
VIDEO = "abcdefghijk"
URI = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=secret-session"
ORIGINAL_CHANNEL = GoogleYouTube.channel


@pytest.fixture
def direct_setup():
    f = old_fixtures.YouTubeStudioTest()
    f.setUp()
    with patch.dict(
        "os.environ",
        {
            "MPT_YOUTUBE_CLIENT_ID": "",
            "MPT_YOUTUBE_CLIENT_SECRET": "",
            "MPT_YOUTUBE_REDIRECT_URI": "",
            "MPT_SOCIAL_ENCRYPTION_KEY": "",
        },
    ):
        accounts.configure(
            "example.apps.googleusercontent.com",
            "secret-client",
            "http://127.0.0.1:8501" + accounts.CALLBACK,
        )
        f.credentials = Credentials(
            token="secret-access",
            refresh_token="secret-refresh",
            client_id="example.apps.googleusercontent.com",
            client_secret="secret-client",
            scopes=accounts.SCOPES,
            expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        )
        f.direct_channel = {
            "channel_id": CHANNEL,
            "name": "Garden YouTube",
            "picture": "",
            "uploads": "UU" + "a" * 22,
        }
        value = accounts.vault()
        value["connections"][CID] = {
            **f.direct_channel,
            "id": CID,
            "app": accounts.fingerprint(),
            "credentials": json.loads(f.credentials.to_json()),
            "reauth_required": False,
            "checked_at": time.time(),
        }
        accounts.save_vault(value)
        f.channel_patch = patch.object(
            GoogleYouTube, "channel", return_value=f.direct_channel
        )
        f.channel_call = f.channel_patch.start()
        enqueue = patch.object(studio, "enqueue")
        f.enqueue = enqueue.start()
        try:
            with (
                patch(
                    "requests.request",
                    side_effect=AssertionError("unexpected live YouTube operation"),
                ),
                patch(
                    "requests.post",
                    side_effect=AssertionError("unexpected live Google operation"),
                ),
            ):
                yield f
        finally:
            enqueue.stop()
            f.channel_patch.stop()
            f.doCleanups()


def draft(f, **changes):
    return studio.prepare("test-video", "final-1.mp4", CID, {**f.opts, **changes})


def approved(f, **changes):
    job = draft(f, **changes)
    studio.approve(job["id"], True)
    return studio.get(job["id"])


def response(status=308, data=None, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = data or {}
    return result


def remote(privacy="private", publish=None, upload="processed"):
    return {
        "id": VIDEO,
        "etag": "etag-original",
        "snippet": {
            "channelId": CHANNEL,
            "title": "Garden",
            "description": "flowers",
            "categoryId": "22",
            "tags": ["nature"],
        },
        "status": {
            "privacyStatus": privacy,
            "uploadStatus": upload,
            "selfDeclaredMadeForKids": False,
            **({"publishAt": publish} if publish else {}),
        },
    }


def test_credentials_and_upload_sessions_are_encrypted_and_wrong_key_is_safe(
    direct_setup,
):
    f = direct_setup
    job = draft(f)
    internal = studio._get(job["id"])
    internal["upload_uri"] = URI
    studio._write(internal)
    assert "upload_uri" not in studio.get(job["id"])
    assert accounts.connections()[0]["channel_id"] == CHANNEL
    for path in accounts.directory().rglob("*.enc"):
        raw = path.read_bytes()
        for secret in (
            b"secret-client",
            b"secret-refresh",
            b"secret-access",
            b"secret-session",
        ):
            assert secret not in raw
    from cryptography.fernet import Fernet

    with patch.dict(
        "os.environ", {"MPT_SOCIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()}
    ):
        with pytest.raises(ValueError, match="original encryption key"):
            accounts.vault()
    assert (
        accounts.credential_record(CID)["credentials"]["refresh_token"]
        == "secret-refresh"
    )


def test_real_authorization_url_has_offline_access_pkce_and_single_use_browser_binding(
    direct_setup,
):
    url = accounts.connect_ticket()
    ticket = parse_qs(urlsplit(url).query)["ticket"][0]
    authorize, state, browser = accounts.begin(ticket)
    query = parse_qs(urlsplit(authorize).query)
    assert urlsplit(authorize).hostname == "accounts.google.com"
    assert query["access_type"] == ["offline"] and query["code_challenge_method"] == [
        "S256"
    ]
    assert query["scope"] == [accounts.SCOPES[0]]
    with pytest.raises(ValueError, match="expired"):
        accounts.begin(ticket)
    with pytest.raises(ValueError, match="another browser"):
        accounts.finish(state, "wrong-browser", "code")
    with (
        patch.object(
            accounts, "_flow", return_value=Mock(credentials=direct_setup.credentials)
        ),
        patch.object(
            GoogleYouTube, "channel", return_value=direct_setup.direct_channel
        ),
    ):
        assert accounts.finish(state, browser, "code") == CID
    with pytest.raises(ValueError, match="expired"):
        accounts.finish(state, browser, "code")
    assert len(accounts.connections()) == 1


def test_gateway_callback_cookie_no_reflection_replay_or_redirect_leak(direct_setup):
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    client = TestClient(create_app(), base_url="http://127.0.0.1:8501")
    start = client.get(
        "/social/youtube/oauth/start", params={"ticket": ticket}, follow_redirects=False
    )
    assert (
        start.status_code == 303 and start.headers["referrer-policy"] == "no-referrer"
    )
    assert (
        "HttpOnly" in start.headers["set-cookie"]
        and "SameSite=lax" in start.headers["set-cookie"]
    )
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    foreign = TestClient(create_app(), base_url="http://127.0.0.1:8501")
    assert (
        foreign.get(
            accounts.CALLBACK, params={"state": state, "code": "secret-code"}
        ).status_code
        == 400
    )
    with patch.object(
        accounts, "_flow", return_value=Mock(credentials=direct_setup.credentials)
    ):
        callback = client.get(
            accounts.CALLBACK,
            params={"state": state, "code": "secret-code"},
            follow_redirects=False,
        )
    assert (
        callback.status_code == 303
        and callback.headers["location"] == "/?view=social&youtube_connected=1"
    )
    assert (
        "secret-code" not in callback.text
        and callback.headers["cache-control"] == "no-store"
    )
    assert (
        client.get(
            accounts.CALLBACK, params={"state": state, "code": "secret-code"}
        ).status_code
        == 400
    )


def test_declined_and_expired_flows_never_create_connections(direct_setup):
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    _, state, browser = accounts.begin(ticket)
    with pytest.raises(ValueError, match="declined"):
        accounts.finish(state, browser, error="access_denied")
    assert len(accounts.connections()) == 1
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    with patch.object(accounts.time, "time", return_value=time.time() + 1000):
        with pytest.raises(ValueError, match="expired"):
            accounts.begin(ticket)
    assert len(accounts.connections()) == 1


def test_immutable_review_legacy_records_and_duplicate_approvals_remain_separate(
    direct_setup,
):
    f = direct_setup
    a, b = draft(f), draft(f, title="Other title")
    assert legacy.jobs() == []
    studio.recover()
    f.enqueue.assert_not_called()
    f.source.unlink()
    assert legacy.snapshot_file(a).read_bytes() == b"original-video-bytes"
    with pytest.raises(ValueError, match="Review"):
        studio.approve(a["id"])
    studio.approve(a["id"], True)
    with pytest.raises(ValueError, match="Another direct"):
        studio.approve(b["id"], True)
    assert studio.get(a["id"])["state"] == "queued"


def test_legacy_pending_delivery_blocks_direct_approval(direct_setup):
    f = direct_setup
    job = draft(f)
    with patch.object(
        legacy,
        "jobs",
        return_value=[
            {
                "sha256": job["sha256"],
                "channel": {"channel_id": CHANNEL},
                "state": "scheduled",
            }
        ],
    ):
        with pytest.raises(ValueError, match="legacy delivery"):
            studio.approve(job["id"], True)


def test_upload_always_starts_private_and_persists_id_before_release(direct_setup):
    f = direct_setup
    job = approved(f, privacy="public")
    completed = response(201, {"id": VIDEO, "snippet": {"channelId": CHANNEL}})
    calls = []

    def update(*args, **kwargs):
        persisted = studio.get(job["id"])
        assert (
            persisted["video_id"] == VIDEO and persisted["state"] == "release_pending"
        )
        calls.append(kwargs)
        return remote("public")

    with (
        patch.object(GoogleYouTube, "initiate", return_value=URI),
        patch.object(GoogleYouTube, "probe", return_value=response()),
        patch.object(GoogleYouTube, "chunk", return_value=completed),
        patch.object(
            GoogleYouTube,
            "owned_video",
            side_effect=[remote(), remote(), remote("public")],
        ),
        patch.object(GoogleYouTube, "update", side_effect=update),
    ):
        result = studio.dispatch(job["id"])
    assert result["state"] == "published" and result["video_id"] == VIDEO
    assert calls[0]["status"]["privacyStatus"] == "public"
    assert "upload_uri" not in result
    # Direct initiation uses real Google transport with explicit private metadata.
    internal = studio._get(job["id"])
    with patch(
        "requests.post", return_value=response(200, headers={"Location": URI})
    ) as request:
        GoogleYouTube(CID).initiate(internal)
    assert request.call_args.kwargs["json"]["status"]["privacyStatus"] == "private"
    assert request.call_args.kwargs["allow_redirects"] is False


def test_interrupted_chunk_resumes_google_offset_without_new_upload(direct_setup):
    f = direct_setup
    job = approved(f)
    with (
        patch.object(GoogleYouTube, "initiate", return_value=URI) as initiate,
        patch.object(GoogleYouTube, "probe", return_value=response()),
        patch.object(GoogleYouTube, "chunk", side_effect=YouTubeError(uncertain=True)),
    ):
        assert studio.dispatch(job["id"])["state"] == "paused"
    internal = studio._get(job["id"])
    assert internal["upload_uri"] == URI
    internal["state"] = "uploading"
    studio._write(internal)
    studio.recover()
    assert studio.get(job["id"])["state"] == "paused"
    studio.resume(job["id"], True)
    with (
        patch.object(GoogleYouTube, "initiate") as initiate,
        patch.object(
            GoogleYouTube,
            "probe",
            return_value=response(headers={"Range": "bytes=0-3"}),
        ),
        patch.object(
            GoogleYouTube,
            "chunk",
            return_value=response(
                201, {"id": VIDEO, "snippet": {"channelId": CHANNEL}}
            ),
        ) as chunk,
        patch.object(GoogleYouTube, "owned_video", return_value=remote()),
    ):
        assert studio.dispatch(job["id"])["state"] == "completed"
        assert chunk.call_args.args[2] == 4
        initiate.assert_not_called()


def test_unknown_initialization_and_expired_session_never_blindly_resend(direct_setup):
    f = direct_setup
    job = approved(f)
    with patch.object(
        GoogleYouTube, "initiate", side_effect=YouTubeError(uncertain=True)
    ) as initiate:
        assert studio.dispatch(job["id"])["state"] == "unknown"
        studio.recover()
        studio.dispatch(job["id"])
        initiate.assert_called_once()
    with pytest.raises(ValueError, match="cannot safely"):
        studio.resume(job["id"], True)
    studio.cancel(job["id"])
    other = approved(f)
    internal = studio._get(other["id"])
    internal["upload_uri"] = URI
    studio._write(internal)
    with (
        patch.object(GoogleYouTube, "probe", side_effect=YouTubeError(404)),
        patch.object(GoogleYouTube, "initiate") as initiate,
    ):
        assert studio.dispatch(other["id"])["state"] == "unknown"
        initiate.assert_not_called()


def test_no_progress_and_invalid_offsets_pause_instead_of_looping(direct_setup):
    f = direct_setup
    job = approved(f)
    with (
        patch.object(GoogleYouTube, "initiate", return_value=URI),
        patch.object(GoogleYouTube, "probe", return_value=response()),
        patch.object(GoogleYouTube, "chunk", return_value=response()) as chunk,
    ):
        assert studio.dispatch(job["id"])["state"] == "paused"
        assert chunk.call_count == 3
    with pytest.raises(YouTubeError):
        studio._received(
            studio._get(job["id"]), response(headers={"Range": "bytes=0-99999"})
        )


def test_schedule_is_accepted_on_youtube_and_cancellation_keeps_private_video(
    direct_setup,
):
    f = direct_setup
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    job = approved(f, privacy="public", scheduled_at=when)
    completed = response(201, {"id": VIDEO, "snippet": {"channelId": CHANNEL}})
    with (
        patch.object(GoogleYouTube, "initiate", return_value=URI),
        patch.object(GoogleYouTube, "probe", return_value=response()),
        patch.object(GoogleYouTube, "chunk", return_value=completed),
        patch.object(
            GoogleYouTube,
            "owned_video",
            side_effect=[remote(), remote(), remote(publish=when)],
        ),
        patch.object(GoogleYouTube, "update") as update,
    ):
        assert studio.dispatch(job["id"])["state"] == "scheduled"
        status = update.call_args.kwargs["status"]
        assert status["publishAt"] == when and status["privacyStatus"] == "private"
    with (
        patch.object(
            GoogleYouTube, "owned_video", side_effect=[remote(publish=when), remote()]
        ),
        patch.object(GoogleYouTube, "update") as update,
        patch.object(GoogleYouTube, "delete") as delete,
    ):
        assert studio.cancel(job["id"])["state"] == "cancelled"
        assert "publishAt" not in update.call_args.kwargs["status"]
        delete.assert_not_called()


def test_elapsed_schedule_stays_private_and_release_timeout_does_not_reupload(
    direct_setup,
):
    f = direct_setup
    job = approved(
        f,
        privacy="public",
        scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    internal = studio._get(job["id"])
    internal.update(video_id=VIDEO, state="processing")
    internal["options"]["scheduled_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    studio._write(internal)
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=remote()),
        patch.object(GoogleYouTube, "update") as update,
    ):
        assert (
            studio._sync(internal, GoogleYouTube(CID), allow_release=True)["state"]
            == "release_pending"
        )
        update.assert_not_called()
    # Recover a lost metadata response by reading its actual schedule.
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    with (
        patch.object(
            GoogleYouTube,
            "owned_video",
            side_effect=[remote(), remote(), remote(), remote(publish=when)],
        ),
        patch.object(GoogleYouTube, "update"),
    ):
        assert studio.reschedule(job["id"], when, True)["state"] == "scheduled"


def test_content_edits_preserve_fields_check_ownership_and_delete_requires_exact_id(
    direct_setup,
):
    f = direct_setup
    row = remote()
    row["snippet"].update(defaultLanguage="en")
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(GoogleYouTube, "update", return_value=row) as update,
    ):
        studio.edit_video(
            CID, VIDEO, {**f.opts, "title": "Changed"}, True, etag="etag-original"
        )
        assert update.call_args.kwargs["snippet"]["defaultLanguage"] == "en"
        assert update.call_args.kwargs["snippet"]["title"] == "Changed"
        assert "uploadStatus" not in update.call_args.kwargs["status"]
        with pytest.raises(ValueError, match="changed since review"):
            studio.edit_video(CID, VIDEO, f.opts, True, etag="stale")
    with patch.object(GoogleYouTube, "delete") as delete:
        with pytest.raises(ValueError, match="exact video ID"):
            studio.delete_video(CID, VIDEO, "yes")
        delete.assert_not_called()
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(GoogleYouTube, "delete") as delete,
    ):
        studio.delete_video(CID, VIDEO, VIDEO)
        delete.assert_called_once_with(VIDEO)


def test_remote_channel_and_thumbnail_checks_do_not_accept_another_destination(
    direct_setup,
):
    f = direct_setup
    job = approved(f)
    f.channel_call.return_value = {**f.direct_channel, "channel_id": "UC" + "b" * 22}
    with patch.object(GoogleYouTube, "initiate") as initiate:
        assert studio.dispatch(job["id"])["state"] == "blocked"
        initiate.assert_not_called()
    with pytest.raises(ValueError, match="valid JPG"):
        studio.set_thumbnail(CID, VIDEO, b"not-image", True)


def test_session_urls_reject_redirects_foreign_hosts_and_wrong_paths(direct_setup):
    for value in (
        "http://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
        "https://evil.example/upload/youtube/v3/videos?upload_id=x",
        "https://www.googleapis.com/other?upload_id=x",
        "https://user@www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
    ):
        with pytest.raises(ValueError):
            session_url(value)
    client = GoogleYouTube(CID)
    with patch("requests.request", return_value=response(302)):
        with pytest.raises(YouTubeError):
            client.request("GET", "channels")
    with patch("requests.request", side_effect=requests.Timeout("secret-access")):
        with pytest.raises(YouTubeError) as exc:
            client.request("PUT", URI, upload=True)
        assert exc.value.uncertain and "secret-access" not in str(exc.value)


def test_disconnect_blocks_pending_work_and_revokes_without_deleting_remote_videos(
    direct_setup,
):
    job = approved(direct_setup)
    with pytest.raises(ValueError, match="pending deliveries"):
        accounts.disconnect(CID)
    studio.cancel(job["id"])
    with patch("requests.post", return_value=response(200)) as revoke:
        accounts.disconnect(CID)
    assert not accounts.connections()
    assert revoke.call_args.args[0] == "https://oauth2.googleapis.com/revoke"
    assert revoke.call_args.kwargs["data"]["token"] == "secret-refresh"


def test_lost_publication_response_reconciles_existing_video_without_reupload(
    direct_setup,
):
    f = direct_setup
    job = approved(f, privacy="public")
    with (
        patch.object(GoogleYouTube, "initiate", return_value=URI),
        patch.object(GoogleYouTube, "probe", return_value=response()),
        patch.object(
            GoogleYouTube,
            "chunk",
            return_value=response(
                201, {"id": VIDEO, "snippet": {"channelId": CHANNEL}}
            ),
        ),
        patch.object(GoogleYouTube, "owned_video", return_value=remote()),
        patch.object(GoogleYouTube, "update", side_effect=YouTubeError(uncertain=True)),
    ):
        assert studio.dispatch(job["id"])["state"] == "release_pending"
    assert studio.get(job["id"])["video_id"] == VIDEO
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=remote("public")),
        patch.object(GoogleYouTube, "initiate") as initiate,
        patch.object(GoogleYouTube, "update") as update,
    ):
        assert studio.refresh(job["id"])["state"] == "published"
        initiate.assert_not_called()
        update.assert_not_called()


def test_google_token_refresh_persists_and_transient_failure_does_not_revoke(
    direct_setup,
):
    from google.auth.exceptions import TransportError, RefreshError

    data = accounts.vault()
    data["connections"][CID]["credentials"]["expiry"] = "2000-01-01T00:00:00Z"
    accounts.save_vault(data)
    with patch.object(
        Credentials, "refresh", side_effect=TransportError("private-token")
    ):
        with pytest.raises(YouTubeError):
            GoogleYouTube(CID)._credentials()
    assert not accounts.credential_record(CID)["reauth_required"]

    def refresh(credentials, request):
        credentials.token = "new-access"
        credentials.expiry = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) + timedelta(hours=1)

    with patch.object(Credentials, "refresh", autospec=True, side_effect=refresh):
        assert GoogleYouTube(CID)._credentials().token == "new-access"
    assert accounts.credential_record(CID)["credentials"]["token"] == "new-access"
    assert b"new-access" not in (accounts.directory() / "accounts.enc").read_bytes()
    with patch.object(
        Credentials, "refresh", side_effect=RefreshError("invalid_grant")
    ):
        with pytest.raises(YouTubeError):
            GoogleYouTube(CID)._credentials(force=True)
    assert accounts.connections()[0]["reauth_required"]


def test_channel_lookup_and_content_pagination_use_official_endpoints(direct_setup):
    client = GoogleYouTube(CID)
    channel = {
        "id": CHANNEL,
        "snippet": {"title": "Garden"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "a" * 22}},
    }
    with patch.object(client, "request", return_value={"items": [channel]}) as request:
        assert ORIGINAL_CHANNEL(client)["channel_id"] == CHANNEL
        assert request.call_args.kwargs["params"]["mine"] == "true"
    with patch.object(
        client,
        "request",
        side_effect=[
            {
                "items": [{"contentDetails": {"videoId": VIDEO}}],
                "nextPageToken": "page-2",
            },
            {"items": [remote()]},
        ],
    ) as request:
        data = client.content()
        assert data["items"][0]["id"] == VIDEO and data["next"] == "page-2"
        assert request.call_args_list[0].args == ("GET", "playlistItems")
        assert request.call_args_list[1].kwargs["params"]["id"] == VIDEO
    with patch.object(
        client,
        "videos",
        return_value=[{**remote(), "snippet": {"channelId": "different"}}],
    ):
        with pytest.raises(ValueError, match="not available"):
            client.owned_video(VIDEO, CHANNEL)


def test_real_decoded_video_uses_direct_resumable_transport_and_remote_schedule(
    direct_setup,
):
    import subprocess
    from moviepy import VideoFileClip
    from app.utils import utils

    f = direct_setup
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
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with (
        patch.object(
            legacy.video,
            "_open_video_clip_quietly",
            side_effect=lambda name: VideoFileClip(name, audio=False),
        ),
        patch.object(legacy.video, "close_clip", side_effect=lambda clip: clip.close()),
    ):
        job = approved(f, privacy="public", scheduled_at=when)
    f.source.unlink()
    assert legacy.snapshot_file(job).read_bytes() == original
    schedule = {"value": None}

    def wire(method, url, **kwargs):
        if url == URI:
            if kwargs["headers"]["Content-Range"].startswith("bytes */"):
                return response()
            assert kwargs["data"] == original
            return response(201, {"id": VIDEO, "snippet": {"channelId": CHANNEL}})
        if url.endswith("/videos") and method == "GET":
            return response(200, {"items": [remote(publish=schedule["value"])]})
        if url.endswith("/videos") and method == "PUT":
            schedule["value"] = kwargs["json"]["status"]["publishAt"]
            return response(200, remote(publish=schedule["value"]))
        raise AssertionError("Unexpected Google operation")

    with (
        patch(
            "requests.post", return_value=response(200, headers={"Location": URI})
        ) as initiate,
        patch("requests.request", side_effect=wire),
    ):
        result = studio.dispatch(job["id"])
    assert result["state"] == "scheduled" and schedule["value"] == when
    assert initiate.call_args.kwargs["json"]["status"]["privacyStatus"] == "private"
    assert result["offset"] == len(original) and "upload_uri" not in result


def test_edit_private_scheduled_video_preserves_schedule_and_thumbnail_is_bounded(
    direct_setup,
):
    import io
    from PIL import Image

    f = direct_setup
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    row = remote(publish=when)
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(GoogleYouTube, "update") as update,
    ):
        studio.edit_video(CID, VIDEO, f.opts, True)
        assert update.call_args.kwargs["status"]["publishAt"] == when
    data = io.BytesIO()
    Image.new("RGB", (128, 72), "blue").save(data, format="PNG")
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(GoogleYouTube, "request", return_value={"items": []}) as request,
    ):
        studio.set_thumbnail(CID, VIDEO, data.getvalue(), True)
        assert request.call_args.args == ("POST", "thumbnails/set")
        assert request.call_args.kwargs["params"]["videoId"] == VIDEO


def test_new_channel_does_not_repoint_existing_connection_and_disconnect_clears_local_history(
    direct_setup,
):
    f = direct_setup
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    _, state, browser = accounts.begin(ticket)
    other = {**f.direct_channel, "channel_id": "UC" + "b" * 22, "name": "Other channel"}
    with (
        patch.object(accounts, "_flow", return_value=Mock(credentials=f.credentials)),
        patch.object(GoogleYouTube, "channel", return_value=other),
    ):
        new_id = accounts.finish(state, browser, "code")
    assert new_id != CID and accounts.credential_record(CID)["channel_id"] == CHANNEL
    assert accounts.credential_record(new_id)["channel_id"] == other["channel_id"]
    job = draft(f)
    studio.cancel(job["id"])
    with patch("requests.post", return_value=response(200)):
        accounts.disconnect(CID)
    assert not studio.jobs()
    assert accounts.connections()[0]["reauth_required"]
    assert f.source.exists()


def test_inflight_oauth_cannot_restore_connection_after_configuration_changed(
    direct_setup,
):
    f = direct_setup
    ticket = parse_qs(urlsplit(accounts.connect_ticket()).query)["ticket"][0]
    _, state, browser = accounts.begin(ticket)

    def exchange(**kwargs):
        accounts.configure(
            "example.apps.googleusercontent.com",
            "secret-client",
            "http://127.0.0.1:8502" + accounts.CALLBACK,
        )

    flow = Mock(credentials=f.credentials)
    flow.fetch_token.side_effect = exchange
    with patch.object(accounts, "_flow", return_value=flow):
        with pytest.raises(ValueError, match="settings changed"):
            accounts.finish(state, browser, "code")
    assert len(accounts.connections()) == 1


def test_direct_upload_does_not_require_upload_post_and_rejects_nonpublic_schedule(
    direct_setup,
):
    from app.config import config

    f = direct_setup
    with patch.object(
        config,
        "app",
        {**config.app, "upload_post_enabled": False, "upload_post_api_key": ""},
    ):
        assert draft(f)["state"] == "draft"
    with pytest.raises(ValueError, match="goes public"):
        draft(
            f, scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )
