import json
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PIL import Image

from app.services import publishing_seo as seo, youtube_direct as youtube
from app.services.youtube_google import GoogleYouTube, YouTubeError
from test.services import test_youtube_direct as fixtures


@pytest.fixture
def direct_setup():
    yield from fixtures.direct_setup.__wrapped__()


def payload(**changes):
    return (
        dict(
            titles=["Grow a small garden", "Start gardening at home"],
            description="Learn how to grow a small garden.",
            tags=["gardening", "home garden"],
            hashtags=["#Gardening", "#HomeGarden"],
            focus="Starting a home garden",
            thumbnail_text="START GROWING",
            thumbnail_concept="A real plant from the finished video.",
        )
        | changes
    )


def script(f):
    path = f.root / "script.json"
    path.write_text(
        json.dumps(
            dict(
                script="Plant seeds in soil, then water them.",
                params={"video_subject": "A garden"},
            )
        )
    )


def generate(f, platform="youtube", **kwargs):
    script(f)
    with patch.object(
        seo.llm, "generate_json_response", return_value=payload()
    ) as call:
        package = seo.generate("test-video", "final-1.mp4", platform, **kwargs)
    return package, call


def test_script_grounded_package_is_encrypted_durable_and_does_not_publish(
    direct_setup,
):
    package, call = generate(direct_setup)
    assert "Plant seeds in soil" in call.call_args.args[0]
    assert call.call_args.kwargs == dict(timeout_seconds=90, max_retries=0)
    assert package["metadata"]["description"].endswith("#Gardening #HomeGarden")
    assert seo.load("test-video", "final-1.mp4", "youtube") == package
    assert not direct_setup.enqueue.called and not youtube.jobs()
    assert b"START GROWING" not in next(seo._root().glob("*.enc")).read_bytes()


def test_failure_retains_previous_package_and_does_not_publish(direct_setup):
    package, _ = generate(direct_setup)
    with patch.object(
        seo.llm, "generate_json_response", side_effect=RuntimeError("secret-token")
    ):
        with pytest.raises(ValueError, match="previous draft was retained") as error:
            seo.generate("test-video", "final-1.mp4", "youtube")
    assert "secret-token" not in str(error.value)
    assert seo.load("test-video", "final-1.mp4", "youtube")["id"] == package["id"]


@pytest.mark.parametrize(
    "changes",
    [
        dict(titles=[]),
        dict(titles=["Bad\ntitle"]),
        dict(description="Visit https://example.com"),
        dict(hashtags=["#two words"]),
        dict(tags=["x" * 80] * 21),
        dict(tags=["bad,tag"]),
        dict(thumbnail_text="x" * 61),
        dict(description="x" * 4501),
    ],
)
def test_invalid_model_output_is_not_silently_published(changes):
    with pytest.raises(ValueError):
        seo.normalize(payload(**changes), "youtube")


def test_platform_isolation_hash_tags_and_override(direct_setup):
    package, call = generate(
        direct_setup,
        "facebook",
        brief="This edited video shows only watering plants.",
        language="Urdu",
    )
    assert (
        "This edited video" in call.call_args.args[0]
        and "Urdu" in call.call_args.args[0]
    )
    assert package["metadata"]["tags"] == []
    assert seo.load("test-video", "final-1.mp4", "youtube") is None
    normalized = seo.normalize(
        payload(
            description="Growing plants #Gardening",
            hashtags=["#Gardening", "#Gardening"],
        ),
        "youtube",
    )
    assert normalized["description"].count("#Gardening") == 1
    assert "made_for_kids" not in normalized and "privacy" not in normalized


def test_changed_source_or_script_invalidates_package(direct_setup):
    package, _ = generate(direct_setup)
    direct_setup.source.write_bytes(b"new-video-bytes")
    assert seo.load("test-video", "final-1.mp4", "youtube") is None
    with pytest.raises(ValueError, match="changed video"):
        youtube.prepare(
            "test-video",
            "final-1.mp4",
            fixtures.CID,
            direct_setup.opts,
            publishing_package=package,
        )


def test_empty_script_needs_summary_and_generation_race_is_rejected(direct_setup):
    with pytest.raises(ValueError, match="summary"):
        seo.generate("test-video", "final-1.mp4", "youtube")
    script(direct_setup)

    def changed(*args, **kwargs):
        direct_setup.source.write_bytes(b"changed video")
        return payload()

    with patch.object(seo.llm, "generate_json_response", side_effect=changed):
        with pytest.raises(ValueError, match="changed during"):
            seo.generate("test-video", "final-1.mp4", "youtube")
    assert seo.load("test-video", "final-1.mp4", "youtube") is None


def test_thumbnail_is_real_jpeg_bound_to_source_and_freezes_with_job(direct_setup):
    package, _ = generate(direct_setup)
    clip = Mock(
        duration=3, get_frame=Mock(return_value=np.zeros((360, 640, 3), dtype=np.uint8))
    )
    with patch.object(seo.legacy.video, "_open_video_clip_quietly", return_value=clip):
        record = seo.make_thumbnail(
            "test-video", "final-1.mp4", package["metadata"]["thumbnail_text"], 0.5
        )
    with Image.open(seo.thumbnail_file(record)) as image:
        assert image.size == (1280, 720) and image.format == "JPEG"
    seo.save_thumbnail("test-video", "final-1.mp4", package["id"], record)
    package = seo.load("test-video", "final-1.mp4", "youtube")
    job = youtube.prepare(
        "test-video",
        "final-1.mp4",
        fixtures.CID,
        direct_setup.opts,
        publishing_package=package,
        thumbnail=record,
    )
    assert (
        job["thumbnail"] == record
        and job["publishing_preparation"]["id"] == package["id"]
    )
    assert job["options"]["privacy"] == direct_setup.opts["privacy"]
    assert "brief" not in job["publishing_preparation"]
    seo.thumbnail_file(record).write_bytes(b"bad-thumbnail")
    with pytest.raises(ValueError, match="changed"):
        youtube.approve(job["id"], True)


def test_thumbnail_uploaded_before_public_release_and_failure_blocks_release(
    direct_setup,
):
    f = direct_setup
    job = youtube.prepare(
        "test-video", "final-1.mp4", fixtures.CID, f.opts | {"privacy": "public"}
    )
    raw = youtube._get(job["id"])
    raw.update(video_id=fixtures.VIDEO, thumbnail={"test": True})
    youtube._write(raw)
    row = fixtures.remote()
    row["status"]["privacyStatus"] = "private"
    events = []
    with (
        patch.object(GoogleYouTube, "owned_video", side_effect=lambda *args: row),
        patch.object(seo, "thumbnail_file", return_value=f.source),
        patch.object(
            youtube,
            "set_thumbnail",
            side_effect=lambda *args, **kwargs: events.append("thumbnail"),
        ),
        patch.object(
            GoogleYouTube,
            "update",
            side_effect=lambda *args, **kwargs: (
                events.append("release"),
                row["status"].update(privacyStatus="public"),
            ),
        ),
    ):
        youtube._sync(raw, GoogleYouTube(fixtures.CID), allow_release=True)
    assert (
        events == ["thumbnail", "release"]
        and youtube.get(job["id"])["thumbnail_applied"]
    )
    raw["thumbnail_applied"] = False
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=row),
        patch.object(seo, "thumbnail_file", return_value=f.source),
        patch.object(
            youtube, "set_thumbnail", side_effect=YouTubeError(uncertain=True)
        ),
        patch.object(GoogleYouTube, "update") as release,
    ):
        with pytest.raises(YouTubeError):
            youtube._sync(raw, GoogleYouTube(fixtures.CID), allow_release=True)
        release.assert_not_called()


def test_refresh_does_not_complete_private_delivery_with_pending_thumbnail(
    direct_setup,
):
    job = youtube.prepare("test-video", "final-1.mp4", fixtures.CID, direct_setup.opts)
    raw = youtube._get(job["id"])
    raw.update(
        video_id=fixtures.VIDEO, thumbnail={"pending": True}, state="release_pending"
    )
    youtube._write(raw)
    row = fixtures.remote()
    row["status"].update(privacyStatus="private", uploadStatus="processed")
    with patch.object(GoogleYouTube, "owned_video", return_value=row):
        assert youtube.refresh(job["id"])["state"] == "release_pending"


def test_real_cpu_video_thumbnail_and_invalid_time(direct_setup):
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
            "color=c=green:s=160x288:r=24:d=1",
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
    with (
        patch.object(
            seo.legacy.video,
            "_open_video_clip_quietly",
            side_effect=lambda name: VideoFileClip(name, audio=False),
        ),
        patch.object(
            seo.legacy.video, "close_clip", side_effect=lambda clip: clip.close()
        ),
    ):
        record = seo.make_thumbnail("test-video", "final-1.mp4", "REAL VIDEO", 0.4)
        assert seo.thumbnail_file(record).stat().st_size < 2 * 1024 * 1024
        with pytest.raises(ValueError, match="inside"):
            seo.make_thumbnail("test-video", "final-1.mp4", "", 100)


def test_facebook_package_binds_original_webm_hash_and_no_youtube_tags(direct_setup):
    # Audit uses the source hash, not a platform conversion's delivered-file hash.
    package, _ = generate(direct_setup, "facebook")
    assert (
        seo.audit(
            package, "test-video", "final-1.mp4", "facebook", package["source_sha256"]
        )["platform"]
        == "facebook"
    )
    with pytest.raises(ValueError):
        seo.audit(
            package, "test-video", "final-1.mp4", "youtube", package["source_sha256"]
        )


def test_thumbnail_transport_uses_real_media_endpoint_body_and_content_type(
    direct_setup,
):
    import io

    image = io.BytesIO()
    Image.new("RGB", (1280, 720), "green").save(image, format="JPEG")
    data = image.getvalue()
    with (
        patch.object(GoogleYouTube, "owned_video", return_value=fixtures.remote()),
        patch(
            "requests.request",
            return_value=Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "items": [
                            {"default": {"url": "https://example.test/thumbnail.jpg"}}
                        ]
                    }
                ),
            ),
        ) as wire,
    ):
        youtube.set_thumbnail(fixtures.CID, fixtures.VIDEO, data, True)
    assert wire.call_args.args == (
        "POST",
        "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
    )
    kwargs = wire.call_args.kwargs
    assert kwargs["data"] == data and kwargs["headers"]["Content-Type"] == "image/jpeg"
    assert kwargs["params"] == {"videoId": fixtures.VIDEO, "uploadType": "media"}
    assert kwargs["allow_redirects"] is False and "files" not in kwargs
    with pytest.raises(ValueError, match="operation"):
        GoogleYouTube(fixtures.CID).request("DELETE", "videos", thumbnail=True)
