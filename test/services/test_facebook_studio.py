"""Offline Facebook contracts, including destination pins and queue isolation."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from app.config import config
from app.services import facebook_studio as studio, youtube_studio as delivery
from app.services.facebook_publisher import FacebookPublisher
from app.services.youtube_publisher import ProviderError, YouTubePublisher
from test.services import test_youtube_studio as fixtures


@pytest.fixture
def setup_facebook():
    fixture = fixtures.YouTubeStudioTest()
    fixture.setUp()
    fixture.facebook = {
        **fixture.channel,
        "channel_id": "123456",
        "account_id": "987654",
        "name": "Garden Page",
        "selected_page_id": "",
    }
    fixture.facebook_options = {
        "title": "A garden",
        "description": "Flowers",
        "media_type": "VIDEO",
        "synthetic": True,
        "scheduled_at": None,
    }
    fixture.facebook_profile = {
        **fixture.facebook,
        "channel_id": "987654",
        "pages": [
            {"id": "123456", "name": "Garden Page"},
            {"id": "456789", "name": "Travel Page"},
        ],
    }
    facebook_patch = patch.object(
        FacebookPublisher, "get_channel", return_value=fixture.facebook
    )
    fixture.facebook_get = facebook_patch.start()
    fixture.addCleanup(facebook_patch.stop)
    with patch.object(
        FacebookPublisher, "profiles", return_value=[fixture.facebook_profile]
    ):
        studio.refresh_channels()
    try:
        with patch(
            "app.services.youtube_publisher.requests.request",
            side_effect=AssertionError("unexpected live publishing request"),
        ):
            yield fixture
    finally:
        fixture.doCleanups()


def draft(f, **options):
    return studio.prepare(
        "test-video",
        "final-1.mp4",
        "garden",
        "123456",
        {**f.facebook_options, **options},
    )


def approved(f, **options):
    job = draft(f, **options)
    studio.approve(job["id"], reviewed=True)
    return studio.get(job["id"])


def test_facebook_review_is_frozen_and_approval_separate(setup_facebook):
    f = setup_facebook
    job = draft(f)
    assert job["platform"] == "facebook" and job["state"] == "draft"
    studio.recover()
    f.start.assert_not_called()
    f.source.unlink()
    assert studio.snapshot_file(job).read_bytes() == b"original-video-bytes"
    with pytest.raises(ValueError, match="Review"):
        studio.approve(job["id"])
    studio.approve(job["id"], reviewed=True)
    f.start.assert_called_once_with(job["id"])
    assert studio.get(job["id"])["state"] == "queued"
    assert "private-key" not in json.dumps(studio.get(job["id"]))


def test_same_bytes_can_go_to_both_platforms_but_not_same_page_twice(setup_facebook):
    f = setup_facebook
    youtube = f.approved()
    facebook = approved(f)
    assert [j["id"] for j in studio.jobs()] == [facebook["id"]]
    assert [j["id"] for j in delivery.jobs()] == [youtube["id"]]
    with pytest.raises(ValueError, match="already has a delivery"):
        draft(f, title="Another title")
    with pytest.raises(ValueError, match="another platform"):
        studio.cancel(youtube["id"])
    assert delivery.get(youtube["id"])["state"] == "queued"
    # Old records remain YouTube without migration.
    legacy = delivery.get(youtube["id"])
    legacy.pop("platform")
    delivery._write(legacy)
    assert delivery.jobs()[0]["id"] == youtube["id"]
    assert len(delivery.jobs(None)) == 2


def test_page_identity_account_and_credentials_checked_at_approval_dispatch_retry(
    setup_facebook,
):
    f = setup_facebook
    job = draft(f)
    f.facebook_get.return_value = {**f.facebook, "account_id": "another-account"}
    with pytest.raises(ValueError, match="another channel"):
        studio.approve(job["id"], reviewed=True)
    f.facebook_get.return_value = f.facebook
    studio.approve(job["id"], reviewed=True)
    f.facebook_get.side_effect = ValueError("pinned to another Facebook Page")
    with patch.object(FacebookPublisher, "upload") as upload:
        delivery.dispatch(job["id"])
        upload.assert_not_called()
    assert studio.get(job["id"])["state"] == "blocked"
    f.facebook_get.side_effect = None
    with patch.object(
        config, "app", {**config.app, "upload_post_api_key": "changed-key"}
    ):
        with pytest.raises(ValueError, match="API key changed"):
            studio.retry(job["id"], reviewed=True)
    studio.retry(job["id"], reviewed=True)
    with patch.object(
        FacebookPublisher, "upload", return_value={"status": "processing"}
    ) as upload:
        delivery.dispatch(job["id"])
        upload.assert_called_once()


def test_duplicate_drafts_are_serialized_on_approval_and_page_specific(setup_facebook):
    f = setup_facebook
    a, b = draft(f), draft(f)
    studio.approve(a["id"], reviewed=True)
    with pytest.raises(ValueError, match="Another delivery"):
        studio.approve(b["id"], reviewed=True)
    f.facebook_get.return_value = {**f.facebook, "channel_id": "456789"}
    second = studio.prepare(
        "test-video", "final-1.mp4", "garden", "456789", f.facebook_options
    )
    studio.approve(second["id"], reviewed=True)
    assert len(studio.jobs()) == 3


def test_facebook_timeouts_restarts_never_resend_and_results_are_platform_specific(
    setup_facebook,
):
    f = setup_facebook
    job = approved(f)
    with patch.object(
        FacebookPublisher, "upload", side_effect=ProviderError(uncertain=True)
    ) as upload:
        delivery.dispatch(job["id"])
        studio.recover()
        delivery.dispatch(job["id"])
        upload.assert_called_once()
    assert studio.get(job["id"])["state"] == "unknown"
    with pytest.raises(ValueError, match="cannot be resent"):
        studio.retry(job["id"], reviewed=True)
    with patch.object(
        FacebookPublisher,
        "status",
        return_value={
            "status": "completed",
            "results": [{"platform": "youtube", "success": True}],
        },
    ):
        assert studio.refresh(job["id"])["state"] == "unknown"
    with patch.object(
        FacebookPublisher,
        "status",
        return_value={
            "status": "completed",
            "results": [
                {
                    "platform": "facebook",
                    "success": True,
                    "post_url": "https://www.facebook.com/reel/123",
                }
            ],
        },
    ):
        result = studio.refresh(job["id"])
    assert result["state"] == "completed"
    assert result["post_url"] == "https://www.facebook.com/reel/123"
    assert "Facebook" in result["message"] and "YouTube" not in result["message"]


def test_provider_schedules_cancel_and_failed_retry_retains_media(setup_facebook):
    f = setup_facebook
    schedule = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    job = approved(f, scheduled_at=schedule, timezone="Asia/Karachi")
    with patch.object(
        FacebookPublisher,
        "upload",
        return_value={"job_id": "fb-schedule", "status": "scheduled"},
    ):
        delivery.dispatch(job["id"])
    assert studio.get(job["id"])["state"] == "scheduled"
    with pytest.raises(ValueError, match="pending deliveries"):
        studio.assert_account_editable("garden")
    delivery.assert_account_editable("garden")  # FB connection does not lock YouTube.
    with patch.object(
        FacebookPublisher, "cancel", side_effect=ProviderError(uncertain=True)
    ):
        with pytest.raises(ProviderError):
            studio.cancel(job["id"])
    assert studio.get(job["id"])["state"] == "unknown"
    with patch.object(
        FacebookPublisher,
        "status",
        return_value={
            "status": "completed",
            "results": [{"platform": "facebook", "success": False}],
        },
    ):
        assert studio.refresh(job["id"])["state"] == "failed"
    with (
        patch.object(
            FacebookPublisher, "retry", return_value={"status": "processing"}
        ) as retry,
        patch.object(FacebookPublisher, "upload") as upload,
    ):
        studio.retry(job["id"], reviewed=True)
        retry.assert_called_once()
        upload.assert_not_called()


def test_reel_preflight_blocks_bad_format_without_transcoding_or_upload(setup_facebook):
    f = setup_facebook
    for duration, size, fps in [
        (2, (1080, 1920), 30),
        (91, (1080, 1920), 30),
        (10, (1920, 1080), 30),
        (10, (360, 640), 30),
        (10, (1080, 1920), 15),
    ]:
        with patch.object(
            delivery.video,
            "_open_video_clip_quietly",
            return_value=Mock(duration=duration, size=size, fps=fps),
        ):
            with pytest.raises(ValueError, match="Reels require"):
                draft(f, media_type="REELS")
    assert not studio.jobs()
    with patch.object(
        delivery.video,
        "_open_video_clip_quietly",
        return_value=Mock(duration=10, size=(1080, 1920), fps=30),
    ):
        job = draft(f, media_type="REELS")
    assert job["options"]["media_type"] == "REELS"
    with pytest.raises(ValueError, match="Choose a Page video"):
        draft(f, media_type="STORIES")
    with pytest.raises(ValueError, match="Select a Facebook Page"):
        studio.prepare("test-video", "final-1.mp4", "garden", None, f.facebook_options)


def test_hosted_connect_disconnect_are_facebook_only(setup_facebook):
    client = FacebookPublisher()
    with patch.object(
        client,
        "request",
        return_value={"access_url": "https://app.upload-post.com/connect?token=secret"},
    ) as request:
        client.connect_url("garden")
        assert request.call_args.kwargs["json"]["platforms"] == ["facebook"]
        client.disconnect("garden")
        assert request.call_args.kwargs["json"] == {
            "profile_username": "garden",
            "social_platform": "facebook",
        }
    with patch.object(
        client, "request", return_value={"access_url": "https://evil.example/connect"}
    ):
        with pytest.raises(ProviderError):
            client.connect_url("garden")


def test_pages_are_profile_scoped_and_pins_cannot_silently_override_target(
    setup_facebook,
):
    f = setup_facebook
    client = FacebookPublisher()
    # Exercise actual get_channel despite the fixture's adapter mock.
    with (
        patch.object(YouTubePublisher, "get_channel", return_value=f.facebook),
        patch.object(
            client,
            "pages",
            return_value={
                "pages": f.facebook_profile["pages"],
                "selected_page_id": "456789",
            },
        ),
    ):
        with pytest.raises(ValueError, match="pinned to another"):
            ORIGINAL_GET_CHANNEL(client, "garden", "123456")
        assert (
            ORIGINAL_GET_CHANNEL(client, "garden", "456789")["channel_id"] == "456789"
        )
    with patch.object(
        client,
        "request",
        return_value={
            "pages": [{"id": "123456", "name": "Garden", "access_token": "secret"}],
            "selected_page_id": None,
        },
    ) as request:
        assert client.pages("garden")["pages"] == [{"id": "123456", "name": "Garden"}]
        assert request.call_args.kwargs["params"] == {"profile_username": "garden"}


ORIGINAL_GET_CHANNEL = FacebookPublisher.get_channel


def test_facebook_multipart_uses_reviewed_page_type_and_only_facebook(setup_facebook):
    f = setup_facebook
    schedule = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    job = draft(f, scheduled_at=schedule)
    client = FacebookPublisher()
    with patch.object(
        client, "request", return_value={"job_id": "scheduled"}
    ) as request:
        client.upload(job, studio.snapshot_file(job))
    data = dict(request.call_args.kwargs["data"])
    assert data["platform[]"] == "facebook"
    assert data["facebook_page_id"] == "123456"
    assert data["facebook_media_type"] == "VIDEO" and data["video_state"] == "PUBLISHED"
    assert data["scheduled_date"] == schedule and data["timezone"] == "UTC"
    assert "privacyStatus" not in data and "selfDeclaredMadeForKids" not in data
    assert "facebook_is_ai_generated" not in data
    assert request.call_args.kwargs["headers"]["Idempotency-Key"] == job["id"]
    job["options"].update(media_type="REELS", synthetic=True)
    assert dict(client.upload_fields(job))["facebook_is_ai_generated"] == "true"


def test_facebook_expired_status_history_matches_platform_profile_and_id(
    setup_facebook,
):
    f = setup_facebook
    job = approved(f)
    client = FacebookPublisher()
    history = [
        {
            "external_id": job["id"],
            "profile_username": "garden",
            "platform": "youtube",
            "success": True,
        },
        {
            "external_id": "different",
            "profile_username": "garden",
            "platform": "facebook",
            "success": True,
        },
        {
            "external_id": job["id"],
            "profile_username": "garden",
            "platform": "facebook",
            "success": True,
        },
    ]
    with patch.object(
        client, "request", side_effect=[ProviderError(404), {"history": history}]
    ) as request:
        result = client.status(job)
    assert result["results"] == [history[2]]
    assert request.call_args.kwargs["params"]["platform"] == "facebook"


def test_raw_transport_network_timeout_is_uncertain_and_safe(setup_facebook):
    client = FacebookPublisher()
    with patch(
        "app.services.youtube_publisher.requests.request",
        side_effect=requests.Timeout("secret"),
    ):
        with pytest.raises(ProviderError) as exc:
            client.request("POST", "/api/upload")
    assert exc.value.uncertain and "secret" not in str(exc.value)


def test_real_reel_snapshot_approves_schedules_and_cancels_with_mocked_transport(
    setup_facebook,
):
    import subprocess
    from moviepy import VideoFileClip
    from app.utils import utils

    f = setup_facebook
    subprocess.run(
        [
            utils.get_ffmpeg_binary(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=540x960:r=24:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-c:a",
            "aac",
            str(f.source),
        ],
        check=True,
    )
    original = f.source.read_bytes()
    schedule = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with (
        patch.object(
            delivery.video,
            "_open_video_clip_quietly",
            side_effect=lambda name: VideoFileClip(name, audio=False),
        ),
        patch.object(
            delivery.video, "close_clip", side_effect=lambda clip: clip.close()
        ),
    ):
        job = approved(f, media_type="REELS", scheduled_at=schedule)
    f.source.unlink()
    response = Mock(status_code=202)
    response.json.return_value = {"success": True, "job_id": "fb-scheduled"}
    captured = {}

    def transport(method, url, **kwargs):
        captured.update(kwargs)
        assert method == "POST" and url.endswith("/api/upload")
        assert kwargs["files"]["video"][1].read() == original
        return response

    with patch(
        "app.services.youtube_publisher.requests.request", side_effect=transport
    ):
        delivery.dispatch(job["id"])
    assert studio.get(job["id"])["state"] == "scheduled"
    assert dict(captured["data"])["facebook_page_id"] == "123456"
    assert dict(captured["data"])["facebook_media_type"] == "REELS"
    with patch.object(
        FacebookPublisher, "request", return_value={"success": True}
    ) as cancel:
        studio.cancel(job["id"])
    assert cancel.call_args.args[:2] == (
        "DELETE",
        "/api/uploadposts/schedule/fb-scheduled",
    )
    assert studio.get(job["id"])["state"] == "cancelled"
    assert studio.snapshot_file(job).read_bytes() == original
