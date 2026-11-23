import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.services import content_library as library, facebook_accounts as meta
from app.services import (
    publishing_seo,
    short_video_direct as direct,
    tiktok_accounts as tiktok,
)
from app.services.facebook_graph import Graph
from test.services import test_facebook_direct as fixture
from test.services.test_publishing_seo import payload
from test.services.test_webui_youtube_studio import by_key
from webui.opencut_server import create_app

IG_ID = "543210"
IG_CID = "e" * 32
TT_CID = "f" * 32
UPLOAD_URL = "https://open-upload.tiktokapis.com/video/?upload_token=credential"


@pytest.fixture
def setup():
    for value in fixture.facebook_setup.__wrapped__():
        values = meta.vault()
        values["settings"]["config_id"] = "4567"
        values["grants"][fixture.GID]["pages"][0]["instagram"] = dict(
            id=IG_ID, name="garden"
        )
        values["instagram_connections"] = {
            IG_CID: dict(
                id=IG_CID,
                identity=IG_ID,
                page_id=fixture.PAGE,
                grant_id=fixture.GID,
                name="garden",
            )
        }
        meta.save(values)
        tiktok.configure(
            "tiktok_key", "tiktok_secret", "https://example.com" + tiktok.CALLBACK
        )
        data = tiktok._read()
        data["connections"][TT_CID] = dict(
            id=TT_CID,
            identity="creator",
            name="Garden TikTok",
            token="token",
            refresh="renew",
            app=tiktok._app(tiktok.settings()),
            expires=9999999999,
            refresh_expires=9999999999,
        )
        tiktok._write(data)

        def freeze(task_id, relative, settings):
            source = fixture.legacy.source_file(task_id, relative)
            digest = fixture.legacy.gm.media_sha256(source)
            path = fixture.legacy.root() / "assets" / (digest + ".mp4")
            path.write_bytes(source.read_bytes())
            return digest, digest, path

        with (
            patch.object(direct, "enqueue") as enqueue,
            patch.object(direct.facebook_direct, "_freeze", side_effect=freeze),
            patch.object(meta, "refresh_pages"),
            patch.object(
                direct.media.video,
                "_open_video_clip_quietly",
                return_value=Mock(duration=10, w=720, h=1280, fps=30),
            ),
            patch(
                "requests.put", side_effect=AssertionError("unexpected TikTok upload")
            ),
            patch(
                "requests.post",
                side_effect=AssertionError("unexpected Instagram upload"),
            ),
        ):
            value.short_enqueue = enqueue
            yield value


def draft(studio, cid):
    return studio.prepare(
        "test-video",
        "final-1.mp4",
        cid,
        {"title": "Garden", "description": "Water regularly.", "synthetic": True},
    )


def test_instagram_upload_is_approved_before_container_and_publish(setup):
    studio = direct.instagram
    job = draft(studio, IG_CID)
    jid = job["id"]
    with pytest.raises(ValueError, match="Review"):
        studio.approve(jid)
    setup.short_enqueue.assert_not_called()
    response = Mock(status_code=200)
    response.json.return_value = {"success": True}
    with (
        patch.object(
            Graph,
            "request",
            side_effect=[
                {"id": "200"},
                {"status_code": "IN_PROGRESS"},
                {"status_code": "FINISHED"},
                {"id": "300"},
            ],
        ) as graph,
        patch.object(direct.requests, "post", return_value=response) as upload,
    ):
        studio.approve(jid, True)
        graph.assert_not_called()
        studio.dispatch(jid)
        assert studio.get(jid)["state"] == "processing"
        studio.dispatch(jid)
        assert studio.get(jid)["post_id"] == "300"
    assert upload.call_args.args[0].endswith("/v26.0/200")
    assert graph.call_args_list[0].args == ("POST", IG_ID + "/media")
    assert graph.call_args_list[0].kwargs["data"]["caption"] == "Water regularly."
    assert graph.call_args.args == ("POST", IG_ID + "/media_publish")


def test_instagram_ambiguous_publication_only_polls_existing_container(setup):
    studio = direct.instagram
    job = draft(studio, IG_CID)
    job.update(state="unknown", stage="publishing", video_id="200")
    studio._write(job)
    with patch.object(
        Graph, "request", return_value={"status_code": "FINISHED"}
    ) as graph:
        studio.refresh(job["id"])
        graph.assert_called_once_with("GET", "200", params={"fields": "status_code"})
    assert studio.get(job["id"])["state"] == "unknown"


def test_tiktok_file_upload_waits_for_tiktok_to_confirm_publication(setup):
    studio = direct.tiktok
    job = draft(studio, TT_CID)
    studio.approve(job["id"], True)
    with (
        patch.object(
            tiktok,
            "request",
            side_effect=[
                {
                    "data": {
                        "publish_id": "v_inbox_file~v2.123",
                        "upload_url": UPLOAD_URL,
                    }
                },
                {"data": {"status": "SEND_TO_USER_INBOX"}},
                {"data": {"status": "PUBLISH_COMPLETE"}},
            ],
        ) as api,
        patch.object(
            direct.requests, "put", return_value=Mock(status_code=201)
        ) as upload,
    ):
        studio.dispatch(job["id"])
        assert studio.get(job["id"])["state"] == "processing"
        assert studio.refresh(job["id"])["state"] == "inbox"
        assert studio.refresh(job["id"])["state"] == "published"
    headers = upload.call_args.kwargs["headers"]
    assert headers["Content-Range"] == f"bytes 0-{job['size'] - 1}/{job['size']}"
    assert not upload.call_args.kwargs["allow_redirects"]
    assert "post_info" not in api.call_args_list[0].kwargs["json"]
    assert api.call_args_list[0].args[1].endswith("/inbox/video/init/")


def test_tiktok_validates_upload_host_and_keeps_ambiguous_attempt_frozen(setup):
    studio = direct.tiktok
    job = draft(studio, TT_CID)
    studio.approve(job["id"], True)
    with patch.object(
        tiktok,
        "request",
        return_value={
            "data": {
                "publish_id": "v_inbox",
                "upload_url": "https://open-upload.tiktokapis.com.evil.invalid/video/?x=1",
            }
        },
    ) as api:
        studio.dispatch(job["id"])
        studio.dispatch(job["id"])
        api.assert_called_once()
    assert studio.get(job["id"])["state"] == "unknown"


def test_tiktok_login_ticket_is_browser_bound_and_single_use(setup):
    with (
        patch.object(
            tiktok,
            "_exchange",
            return_value={
                k: v
                for k, v in tiktok.credentials(TT_CID).items()
                if k not in {"name", "id"}
            },
        ) as exchange,
        patch.object(
            tiktok,
            "request",
            return_value={
                "data": {
                    "user": {"open_id": "creator", "display_name": "Garden TikTok"}
                }
            },
        ),
    ):
        client = TestClient(create_app(), base_url="https://example.com")
        url = tiktok.connect_ticket()
        entry = client.get(url, follow_redirects=False)
        assert entry.status_code == 303
        params = parse_qs(urlsplit(entry.headers["location"]).query)
        assert set(params["scope"][0].split(",")) == {"user.info.basic", "video.upload"}
        callback = tiktok.CALLBACK + "?state=" + params["state"][0] + "&code=example"
        other = TestClient(create_app(), base_url="https://example.com")
        assert other.get(callback, follow_redirects=False).status_code == 400
        exchange.assert_not_called()
        result = client.get(callback, follow_redirects=False)
        assert (
            result.headers["location"]
            == "/?view=social&platform=tiktok&tiktok_connected=1"
        )
        assert client.get(callback, follow_redirects=False).status_code == 400
        exchange.assert_called_once()
    assert "tiktok_secret" not in (tiktok.directory() / "accounts.enc").read_text()


def test_new_destinations_use_existing_batch_review_and_require_immediate_mode(setup):
    keys = ["instagram:" + IG_CID, "tiktok:" + TT_CID]
    (setup.root / "script.json").write_text(
        json.dumps(
            {
                "script": "Water the garden regularly.",
                "params": {"video_subject": "Garden"},
            }
        )
    )
    with (
        patch.object(library, "enqueue"),
        patch.object(
            publishing_seo.llm, "generate_json_response", return_value=payload()
        ),
    ):
        library.select_final("test-video", "final-1.mp4", True)
        for key in keys:
            library.save_preset(
                key, "UTC", [], [0], {"synthetic": True}, thumbnail=False
            )
        with pytest.raises(ValueError, match="after approval"):
            library.create_batch(["test-video"], keys, "slots")
        batch = library.create_batch(["test-video"], keys, "now")
        batch = library.prepare_batch(batch["id"])
        assert [i["state"] for i in batch["items"]] == ["review", "review"], [
            i["error"] for i in batch["items"]
        ]
        setup.short_enqueue.assert_not_called()
        library.approve_batch(batch["id"], True, batch["revision"])
        assert len(setup.short_enqueue.call_args_list) == 2


def test_navigation_keeps_routes_and_campaign_draft_in_one_session(setup):
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "webui/Main.py"), default_timeout=60
    )
    app.query_params["view"] = "campaigns"
    app.run()
    assert not app.exception
    by_key(app.text_area, "campaign_brief").set_value(
        "Garden tips for new growers"
    ).run()
    by_key(app.button, "workspace_nav:Accounts").click().run()
    assert not app.exception and app.query_params["view"] == ["social"]
    by_key(app.radio, "social_platform").set_value("Instagram").run()
    assert not app.exception and any(
        b.label == "Connect Meta for Instagram" for b in app.button
    )
    by_key(app.radio, "social_platform").set_value("TikTok").run()
    assert not app.exception and any(b.label == "Connect TikTok" for b in app.button)
    by_key(app.button, "workspace_nav:Campaigns").click().run()
    assert not app.exception
    assert (
        by_key(app.text_area, "campaign_brief").value == "Garden tips for new growers"
    )
