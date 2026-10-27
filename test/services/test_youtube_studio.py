import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app.config import config
from app.services import youtube_studio as studio
from app.services.youtube_publisher import ProviderError, YouTubePublisher
from app.utils import utils


class YouTubeStudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.tasks = self.base / "tasks"
        self.tasks.mkdir()
        self.root = self.tasks / "test-video"
        self.root.mkdir()
        self.root.joinpath("script.json").write_text(
            json.dumps({"params": {"video_subject": "Garden"}})
        )
        self.storage = patch.object(utils, "storage_dir", side_effect=self.storage_dir)
        self.storage.start()
        self.addCleanup(self.storage.stop)
        task_patch = patch.object(
            utils, "task_dir", side_effect=lambda sub="": str(self.tasks / sub)
        )
        task_patch.start()
        self.addCleanup(task_patch.stop)
        config_patch = patch.object(
            config,
            "app",
            {
                **config.app,
                "upload_post_enabled": True,
                "upload_post_api_key": "private-key",
                "upload_post_auto_upload": False,
            },
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        env = patch.dict("os.environ", {"UPLOAD_POST_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.channel = {
            "profile": "garden",
            "profile_label": "Garden",
            "channel_id": "UC-abc",
            "handle": "@garden",
            "name": "Garden channel",
            "connected": True,
            "reauth_required": False,
        }
        self.opts = {
            "title": "A garden",
            "description": "Flowers",
            "tags": ["nature"],
            "privacy": "private",
            "made_for_kids": False,
            "synthetic": True,
            "paid_placement": False,
            "scheduled_at": None,
        }
        self.source = self.root / "final-1.mp4"
        self.source.write_bytes(b"original-video-bytes")
        channel_patch = patch.object(
            YouTubePublisher, "get_channel", return_value=self.channel
        )
        self.get_channel = channel_patch.start()
        self.addCleanup(channel_patch.stop)
        probe = patch.object(
            studio.video,
            "_open_video_clip_quietly",
            return_value=Mock(duration=3.0, size=(360, 640)),
        )
        probe.start()
        self.addCleanup(probe.stop)
        close = patch.object(studio.video, "close_clip")
        close.start()
        self.addCleanup(close.stop)
        enqueue = patch.object(studio, "start")
        self.start = enqueue.start()
        self.addCleanup(enqueue.stop)

    def storage_dir(self, sub="", create=False):
        target = self.base / sub
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def draft(self, **changes):
        return studio.prepare(
            "test-video", "final-1.mp4", "garden", {**self.opts, **changes}
        )

    def approved(self, **changes):
        job = self.draft(**changes)
        studio.approve(job["id"], reviewed=True)
        return studio.get(job["id"])

    def test_frozen_review_survives_source_changes_reload_and_requires_explicit_approval(
        self,
    ):
        with patch.object(YouTubePublisher, "upload") as upload:
            job = self.draft()
            self.assertEqual(job["state"], "draft")
            studio.recover()
            upload.assert_not_called()
        self.source.write_bytes(b"changed-original-video")
        self.assertEqual(
            studio.snapshot_file(studio.get(job["id"])).read_bytes(),
            b"original-video-bytes",
        )
        with self.assertRaisesRegex(ValueError, "Review"):
            studio.approve(job["id"])
        studio.approve(job["id"], reviewed=True)
        self.assertEqual(studio.get(job["id"])["state"], "queued")
        with self.assertRaisesRegex(ValueError, "already submitted"):
            studio.approve(job["id"], reviewed=True)
        self.assertNotIn("private-key", json.dumps(studio.get(job["id"])))

    def test_duplicate_drafts_cannot_both_be_approved_and_metadata_changes_do_not_bypass_guard(
        self,
    ):
        a, b = self.draft(), self.draft(title="Another title")
        studio.approve(a["id"], reviewed=True)
        with self.assertRaisesRegex(ValueError, "Another delivery"):
            studio.approve(b["id"], reviewed=True)
        with self.assertRaisesRegex(ValueError, "already has a delivery"):
            self.draft()
        self.assertEqual(len(studio.jobs()), 2)

    def test_channel_identity_and_credentials_are_rechecked_at_dispatch(self):
        job = self.approved()
        self.get_channel.return_value = {**self.channel, "channel_id": "UC-other"}
        with patch.object(YouTubePublisher, "upload") as upload:
            studio.dispatch(job["id"])
            upload.assert_not_called()
        self.assertEqual(studio.get(job["id"])["state"], "blocked")
        self.get_channel.return_value = self.channel
        studio.retry(job["id"], reviewed=True)
        with (
            patch.object(
                config, "app", {**config.app, "upload_post_api_key": "another-key"}
            ),
            patch.object(YouTubePublisher, "upload") as upload,
        ):
            studio.dispatch(job["id"])
            upload.assert_not_called()
        self.assertEqual(studio.get(job["id"])["state"], "blocked")

    def test_timeout_is_uncertain_and_never_reuploads_during_restart_or_retry(self):
        job = self.approved()
        with patch.object(
            YouTubePublisher, "upload", side_effect=ProviderError(uncertain=True)
        ) as upload:
            studio.dispatch(job["id"])
            studio.dispatch(job["id"])
            studio.recover()
            with self.assertRaisesRegex(ValueError, "uncertain"):
                studio.retry(job["id"], reviewed=True)
            self.assertEqual(upload.call_count, 1)
        self.assertEqual(studio.get(job["id"])["state"], "unknown")
        with patch.object(
            YouTubePublisher,
            "status",
            return_value={
                "status": "completed",
                "results": [
                    {
                        "platform": "youtube",
                        "status": "completed",
                        "success": True,
                        "post_url": "https://youtube.com/watch?v=abc",
                    }
                ],
            },
        ):
            result = studio.refresh(job["id"])
        self.assertEqual(result["state"], "completed")
        self.assertIn("youtube.com", result["post_url"])

    def test_restart_submitting_job_only_reconciles_and_active_lease_blocks_other_process(
        self,
    ):
        job = self.approved()
        job["state"] = "submitting"
        studio._write(job)
        with studio._lease(job["id"]):
            studio.recover()
            self.assertEqual(studio.get(job["id"])["state"], "submitting")
            with self.assertRaises(ValueError):
                studio.refresh(job["id"])
        studio.recover()
        self.assertEqual(studio.get(job["id"])["state"], "unknown")
        with patch.object(YouTubePublisher, "status", side_effect=ProviderError(404)):
            self.assertEqual(studio.refresh(job["id"])["state"], "unknown")

    def test_schedule_cancel_failure_and_retry_use_provider_record_not_video_reupload(
        self,
    ):
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        job = self.approved(scheduled_at=when)
        with patch.object(
            YouTubePublisher,
            "upload",
            return_value={"success": True, "job_id": "scheduled-1"},
        ):
            self.assertEqual(studio.dispatch(job["id"])["state"], "scheduled")
        with self.assertRaisesRegex(ValueError, "pending deliveries"):
            studio.assert_account_editable("garden")
        with patch.object(
            YouTubePublisher, "cancel", side_effect=ProviderError(uncertain=True)
        ):
            with self.assertRaises(ProviderError):
                studio.cancel(job["id"])
        self.assertEqual(studio.get(job["id"])["state"], "unknown")
        current = studio.get(job["id"])
        studio._apply_result(
            current,
            {
                "status": "failed",
                "results": [
                    {"platform": "youtube", "success": False, "status": "failed"}
                ],
            },
        )
        with (
            patch.object(
                YouTubePublisher, "retry", return_value={"success": True}
            ) as retry,
            patch.object(YouTubePublisher, "upload") as upload,
        ):
            studio.retry(job["id"], reviewed=True)
            self.assertEqual(retry.call_args.args[0]["provider_job_id"], "scheduled-1")
            upload.assert_not_called()
        current = studio.get(job["id"])
        current["state"] = "scheduled"
        studio._write(current)
        with patch.object(YouTubePublisher, "cancel", return_value={"success": True}):
            self.assertEqual(studio.cancel(job["id"])["state"], "cancelled")
        studio.assert_account_editable("garden")

    def test_skipped_retryable_and_unconfirmed_results_are_not_reported_as_success(
        self,
    ):
        job = self.approved()
        self.assertEqual(
            studio._apply_result(
                job,
                {
                    "status": "completed",
                    "results": [{"platform": "youtube", "skipped": True}],
                },
            )["state"],
            "blocked",
        )
        self.assertEqual(
            studio._apply_result(
                job,
                {
                    "status": "in_progress",
                    "results": [
                        {"platform": "youtube", "status": "retryable", "success": False}
                    ],
                },
            )["state"],
            "processing",
        )
        self.assertEqual(
            studio._apply_result(job, {"status": "completed", "results": []})["state"],
            "unknown",
        )
        self.assertIsNone(
            studio._apply_result(
                job,
                {
                    "status": "completed",
                    "results": [
                        {
                            "platform": "youtube",
                            "success": True,
                            "post_url": "https://evil.example/",
                        }
                    ],
                },
            )["post_url"]
        )

    def test_definitive_rejection_can_retry_same_identity_but_corrupt_snapshot_blocks(
        self,
    ):
        job = self.approved()
        with patch.object(YouTubePublisher, "upload", side_effect=ProviderError(401)):
            studio.dispatch(job["id"])
        self.assertEqual(studio.get(job["id"])["state"], "rejected")
        studio.retry(job["id"], reviewed=True)
        studio.snapshot_file(job).write_bytes(b"corrupt")
        with patch.object(YouTubePublisher, "upload") as upload:
            self.assertEqual(studio.dispatch(job["id"])["state"], "blocked")
            upload.assert_not_called()

    def test_drafts_and_queued_deliveries_can_cancel_locally_without_network(self):
        a = self.draft()
        studio.cancel(a["id"])
        b = self.approved()
        studio.cancel(b["id"])
        with patch.object(YouTubePublisher, "upload") as upload:
            studio.dispatch(b["id"])
            upload.assert_not_called()
        self.assertEqual(studio.get(b["id"])["state"], "cancelled")

    def test_source_boundaries_and_schedule_validation(self):
        for relative in (
            "../config.toml",
            "combined-1.mp4",
            "opencut/project.json",
            "/tmp/final-1.mp4",
        ):
            with self.assertRaises(ValueError):
                studio.source_file("test-video", relative)
        self.assertEqual(
            studio.scheduled_utc(datetime(2027, 1, 1, 12), "Asia/Karachi"),
            "2027-01-01T07:00:00+00:00",
        )
        for moment, zone in (
            (datetime(2027, 3, 14, 2, 30), "America/New_York"),
            (datetime(2027, 11, 7, 1, 30), "America/New_York"),
            (datetime(2027, 1, 1), "invalid"),
        ):
            with self.assertRaises(ValueError):
                studio.scheduled_utc(moment, zone)
        for bad in (
            {"made_for_kids": None},
            {"title": ""},
            {"privacy": "draft"},
            {"tags": ["x" * 501]},
            {"scheduled_at": "2020-01-01T00:00:00Z"},
        ):
            with self.assertRaises(ValueError):
                studio.options({**self.opts, **bad})

    def test_adapter_binds_youtube_only_and_uses_idempotency_and_explicit_declarations(
        self,
    ):
        job = self.approved()
        response = Mock(status_code=202)
        response.json.return_value = {"success": True, "request_id": job["request_id"]}
        with patch(
            "app.services.youtube_publisher.requests.request", return_value=response
        ) as request:
            YouTubePublisher().upload(job, studio.snapshot_file(job))
        kwargs = request.call_args.kwargs
        self.assertEqual(
            [v for k, v in kwargs["data"] if k == "platform[]"], ["youtube"]
        )
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], job["id"])
        self.assertEqual(dict(kwargs["data"])["selfDeclaredMadeForKids"], "false")
        self.assertEqual(dict(kwargs["data"])["containsSyntheticMedia"], "true")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("private-key", json.dumps(studio.jobs()))
        with patch(
            "app.services.youtube_publisher.requests.request",
            side_effect=requests.Timeout("private secret error"),
        ):
            with self.assertRaises(ProviderError) as caught:
                YouTubePublisher().upload(job, studio.snapshot_file(job))
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("secret", str(caught.exception))

    def test_profile_account_identity_link_validation_cache_and_disconnect_scope(self):
        client = YouTubePublisher()
        account = client.channel(
            {
                "username": "garden",
                "social_accounts": {"youtube": {"display_name": "Only a label"}},
            }
        )
        self.assertFalse(account["connected"])
        response = Mock(status_code=200)
        response.json.return_value = {
            "access_url": "https://app.upload-post.com/connect?token=transient"
        }
        with patch(
            "app.services.youtube_publisher.requests.request", return_value=response
        ) as request:
            self.assertIn("app.upload-post.com", client.connect_url("garden"))
            self.assertEqual(request.call_args.kwargs["json"]["platforms"], ["youtube"])
            client.disconnect("garden")
            self.assertEqual(
                request.call_args.kwargs["json"]["social_platform"], "youtube"
            )
        response.json.return_value = {"access_url": "https://evil.example/connect"}
        with (
            patch(
                "app.services.youtube_publisher.requests.request", return_value=response
            ),
            self.assertRaises(ProviderError),
        ):
            client.connect_url("garden")
        with patch.object(YouTubePublisher, "profiles", return_value=[self.channel]):
            studio.refresh_channels()
        self.assertEqual(studio.cached_channels()["channels"], [self.channel])
        with patch.object(
            config, "app", {**config.app, "upload_post_api_key": "new-key"}
        ):
            self.assertEqual(studio.cached_channels()["channels"], [])
        self.assertFalse(list(self.base.rglob("*transient*")))

    def test_native_webm_export_and_stock_output_are_available_as_explicit_sources(
        self,
    ):
        export = self.root / "opencut" / "exports" / ("a" * 32 + ".webm")
        export.parent.mkdir(parents=True)
        export.write_bytes(b"export")
        self.assertEqual(
            studio.source_file("test-video", "opencut/exports/" + export.name), export
        )
        self.assertEqual(len(studio.completed_videos()), 2)

    def test_real_cpu_video_is_frozen_decoded_and_scheduled_without_live_provider(self):
        import subprocess
        from moviepy import VideoFileClip

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
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=16000",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                "-c:a",
                "aac",
                str(self.source),
            ],
            check=True,
        )
        original = self.source.read_bytes()
        with (
            patch.object(
                studio.video,
                "_open_video_clip_quietly",
                side_effect=lambda name: VideoFileClip(name, audio=False),
            ),
            patch.object(
                studio.video, "close_clip", side_effect=lambda clip: clip.close()
            ),
        ):
            job = self.approved(
                scheduled_at=(
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat()
            )
        self.assertEqual(studio.snapshot_file(job).read_bytes(), original)
        self.source.unlink()
        with patch.object(
            YouTubePublisher,
            "upload",
            return_value={"success": True, "job_id": "remote-schedule"},
        ) as upload:
            studio.dispatch(job["id"])
            self.assertEqual(upload.call_args.args[1].read_bytes(), original)
        self.assertEqual(studio.get(job["id"])["state"], "scheduled")

    def test_expired_status_reconciles_history_by_exact_id_and_profile(self):
        job = self.approved()
        row = {
            "platform": "youtube",
            "profile_username": "garden",
            "external_id": job["id"],
            "success": True,
            "post_url": "https://youtube.com/watch?v=123",
        }
        with patch.object(
            YouTubePublisher,
            "request",
            side_effect=[ProviderError(404), {"history": [row]}],
        ) as request:
            data = YouTubePublisher().status(job)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(request.call_args.kwargs["params"]["external_id"], job["id"])
        for unrelated in (
            {**row, "profile_username": "other"},
            {**row, "external_id": "other"},
        ):
            with (
                patch.object(
                    YouTubePublisher,
                    "request",
                    side_effect=[ProviderError(404), {"history": [unrelated]}],
                ),
                self.assertRaises(ProviderError),
            ):
                YouTubePublisher().status(job)

    def test_queued_and_preupload_blocked_refresh_never_queries_unknown_provider_records(
        self,
    ):
        job = self.approved()
        with patch.object(YouTubePublisher, "status") as status:
            self.assertEqual(studio.refresh(job["id"])["state"], "queued")
            status.assert_not_called()
        self.get_channel.return_value = {**self.channel, "reauth_required": True}
        studio.dispatch(job["id"])
        with patch.object(YouTubePublisher, "status") as status:
            self.assertEqual(studio.refresh(job["id"])["state"], "blocked")
            status.assert_not_called()
        self.assertEqual(studio.cancel(job["id"])["state"], "cancelled")

    def test_invalid_video_preserves_history_and_does_not_expose_decoder_details(self):
        with patch.object(
            studio.video,
            "_open_video_clip_quietly",
            side_effect=OSError("private decoder path"),
        ):
            with self.assertRaisesRegex(ValueError, "could not be decoded") as caught:
                self.draft()
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(studio.jobs(), [])
        self.assertFalse(list((studio.root() / "assets").glob(".*.mp4")))
