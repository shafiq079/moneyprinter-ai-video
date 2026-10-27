"""Reviewed, durable YouTube delivery jobs; independent from video generation.

The provider owns accepted schedules. Local immutable snapshots, durable state,
OS leases and provider idempotency prevent reruns/restarts from reposting media.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from queue import Full, Queue
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from filelock import FileLock, Timeout
from loguru import logger

from app.services import generation_manifest as gm, scene_planner, video
from app.services.youtube_publisher import ProviderError, YouTubePublisher, publisher
from app.utils import utils

UTC = timezone.utc
MAX_VIDEO = 512 * 1024 * 1024
_ACTIVE = {
    "queued",
    "submitting",
    "processing",
    "scheduled",
    "unknown",
    "retrying",
    "cancelling",
}
_queue = Queue(maxsize=32)
_worker_started = False
_enqueued = set()
_thread_lock = threading.Lock()


def root():
    target = Path(utils.storage_dir("publishing", create=True))
    for name in ("jobs", "assets"):
        directory = target / name
        if directory.is_symlink():
            raise ValueError("Invalid publishing storage directory.")
        directory.mkdir(exist_ok=True)
    return target


def _now():
    return datetime.now(UTC)


def _stamp():
    return _now().isoformat()


def _path(job_id):
    if not isinstance(job_id, str) or not re.fullmatch("[a-f0-9]{32}", job_id):
        raise ValueError("Invalid publishing job identifier.")
    return root() / "jobs" / (job_id + ".json")


def get(job_id):
    path = _path(job_id)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Publishing job is unavailable.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(job, message=None):
    job["updated_at"] = _stamp()
    if message:
        job["message"] = message
        events = job.setdefault("events", [])
        events.append(
            {"at": job["updated_at"], "state": job["state"], "message": message}
        )
        job["events"] = events[-20:]
    scene_planner._atomic_write_json(_path(job["id"]), job)
    return job


def jobs():
    records = []
    for target in (root() / "jobs").glob("*.json"):
        try:
            records.append(get(target.stem))
        except (ValueError, OSError):
            continue
    return sorted(records, key=lambda j: j["created_at"], reverse=True)


@contextmanager
def _lease(job_id):
    lease = FileLock(str(_path(job_id)) + ".lock", thread_local=False)
    try:
        lease.acquire(timeout=0)
    except Timeout as exc:
        raise ValueError(
            "This delivery is being updated. Refresh its status shortly."
        ) from exc
    try:
        yield lease
    finally:
        lease.release()


def source_file(task_id, relative):
    if not isinstance(task_id, str) or not re.fullmatch(
        "[A-Za-z0-9_-]{1,128}", task_id
    ):
        raise ValueError("Invalid task identifier.")
    if not isinstance(relative, str) or not re.fullmatch(
        r"(?:final-\d+\.mp4|opencut/exports/[a-f0-9]{32}\.(?:mp4|webm))", relative
    ):
        raise ValueError("Choose a completed generated video or OpenCut export.")
    source = gm.resolve_asset(task_id, relative)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_VIDEO:
        raise ValueError("Choose a non-empty video smaller than 512 MiB.")
    return source


def completed_videos():
    results = []
    tasks_root = Path(utils.task_dir())
    directories = sorted(
        (p for p in tasks_root.iterdir() if p.is_dir() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:250]
    for directory in directories:
        try:
            metadata = directory / "script.json"
            if not metadata.is_file() or metadata.stat().st_size > 2 * 1024 * 1024:
                continue
            script = json.loads(metadata.read_text(encoding="utf-8"))
            title = str(
                (script.get("params") or {}).get("video_subject")
                or script.get("script")
                or directory.name
            )[:100]
            paths = [
                *directory.glob("final-*.mp4"),
                *(directory / "opencut" / "exports").glob("*"),
            ]
            for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[
                :16
            ]:
                relative = path.relative_to(directory).as_posix()
                source_file(directory.name, relative)
                results.append(
                    {
                        "task_id": directory.name,
                        "asset": relative,
                        "title": title,
                        "label": f"{title} · {directory.name[:8]} · {relative}",
                        "size": path.stat().st_size,
                    }
                )
        except (ValueError, OSError, TypeError, AttributeError):
            continue
    return results


def scheduled_utc(local_time, zone):
    """Reject DST gaps/folds instead of silently choosing an unexpected hour."""
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(
            "Enter a valid IANA timezone, for example Asia/Karachi."
        ) from exc
    if not isinstance(local_time, datetime) or local_time.tzinfo is not None:
        raise ValueError("Enter a local date and time without an embedded timezone.")
    a = local_time.replace(tzinfo=tz, fold=0)
    b = local_time.replace(tzinfo=tz, fold=1)
    if a.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != local_time:
        raise ValueError("That local time does not exist because of a clock change.")
    if a.utcoffset() != b.utcoffset():
        raise ValueError(
            "That local time is ambiguous. Choose another time or use UTC."
        )
    return a.astimezone(UTC).isoformat()


def options(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid YouTube settings.")
    if not isinstance(value.get("title"), str):
        raise ValueError("Enter a YouTube title.")
    title = value["title"].strip()
    description = value.get("description", "")
    tags = value.get("tags", [])
    if not title or len(title) > 100 or any(c in title for c in "<>\n\r"):
        raise ValueError(
            "YouTube title must contain 1–100 characters without angle brackets or line breaks."
        )
    if (
        not isinstance(description, str)
        or len(description) > 5000
        or "<" in description
        or ">" in description
    ):
        raise ValueError(
            "Description must contain at most 5000 characters without angle brackets."
        )
    if (
        not isinstance(tags, list)
        or any(not isinstance(t, str) or not t.strip() or len(t) > 100 for t in tags)
        or sum(len(t) + 1 for t in tags) > 500
    ):
        raise ValueError("Use non-empty tags totaling at most 500 characters.")
    if value.get("privacy") not in {"private", "unlisted", "public"}:
        raise ValueError("Choose private, unlisted or public visibility.")
    for field in ("made_for_kids", "synthetic", "paid_placement"):
        if type(value.get(field)) is not bool:
            raise ValueError(
                "Review the audience and content declarations before continuing."
            )
    scheduled_at = value.get("scheduled_at") or None
    if scheduled_at:
        try:
            moment = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid scheduled time.") from exc
        if moment.tzinfo is None or not _now() + timedelta(
            minutes=2
        ) <= moment.astimezone(UTC) <= _now() + timedelta(days=365):
            raise ValueError(
                "Schedule at least two minutes ahead and within the next 365 days."
            )
        scheduled_at = moment.astimezone(UTC).isoformat()
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "privacy": value["privacy"],
        "made_for_kids": value["made_for_kids"],
        "synthetic": value["synthetic"],
        "paid_placement": value["paid_placement"],
        "scheduled_at": scheduled_at,
        "timezone": str(value.get("timezone") or "UTC")[:80],
    }


def _client(job=None):
    client = YouTubePublisher(publisher.api_key)
    if not client.configured:
        raise ValueError("Enable Upload-Post and configure its API key first.")
    if job and client.credential_id != job["credential_id"]:
        raise ValueError(
            "The provider API key changed. Restore the original key to manage this delivery."
        )
    return client


def _channel(client, job):
    channel = client.get_channel(job["channel"]["profile"])
    if not channel["connected"] or channel["reauth_required"]:
        raise ValueError("Reconnect the selected YouTube channel before continuing.")
    if channel["channel_id"] != job["channel"]["channel_id"]:
        raise ValueError(
            "The profile now points to another channel. Prepare and review a new post."
        )
    return channel


def prepare(task_id, relative, profile, value):
    client = _client()
    settings = options(value)
    channel = client.get_channel(profile)
    if not channel["connected"] or channel["reauth_required"]:
        raise ValueError("Connect a YouTube channel before preparing a post.")
    source = source_file(task_id, relative)
    # Freeze bytes before review, so later editor exports cannot change approval.
    before = source.stat()
    digest = gm.media_sha256(source)
    destination = root() / "assets" / (digest + source.suffix.lower())
    with FileLock(root() / "catalog.lock"):
        existing = jobs()
        if len(existing) >= 1000:
            raise ValueError("Publishing history reached its 1000-job limit.")
        duplicate = next(
            (
                j
                for j in existing
                if j["sha256"] == digest
                and j["channel"]["channel_id"] == channel["channel_id"]
                and j["state"] not in {"draft", "cancelled"}
            ),
            None,
        )
        if duplicate:
            raise ValueError(
                "This video already has a delivery to this channel. Open its history entry instead of creating a duplicate."
            )
        if shutil.disk_usage(root()).free < before.st_size + 16 * 1024 * 1024:
            raise ValueError("Not enough free storage to freeze the reviewed video.")
        temporary = root() / "assets" / ("." + uuid.uuid4().hex + source.suffix)
        try:
            shutil.copyfile(source, temporary)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ) or gm.media_sha256(temporary) != digest:
                raise ValueError(
                    "Video changed while preparing the post. Wait for rendering to finish."
                )
            clip = None
            try:
                clip = video._open_video_clip_quietly(str(temporary))
                if (
                    not clip.duration
                    or not 0 < clip.duration <= 3600
                    or min(clip.size) <= 0
                ):
                    raise ValueError("Video is invalid or exceeds one hour.")
                clip.get_frame(0)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(
                    "This video could not be decoded. Finish or re-export the video before preparing a post."
                ) from exc
            finally:
                if clip is not None:
                    video.close_clip(clip)
            if not destination.exists():
                os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        job = {
            "id": uuid.uuid4().hex,
            "state": "draft",
            "created_at": _stamp(),
            "task_id": task_id,
            "source": relative,
            "sha256": digest,
            "asset": destination.name,
            "size": destination.stat().st_size,
            "mime": mimetypes.guess_type(source.name)[0] or "video/mp4",
            "channel": channel,
            "credential_id": client.credential_id,
            "options": settings,
            "request_id": uuid.uuid4().hex,
            "provider_job_id": None,
            "events": [],
        }
        return _write(
            job,
            "Draft prepared. Review the frozen video and destination before approving.",
        )


def snapshot_file(job):
    filename = job["asset"]
    if (
        not re.fullmatch(r"[a-f0-9]{64}\.(?:mp4|webm)", filename)
        or filename != job["sha256"] + Path(filename).suffix
    ):
        raise ValueError("Invalid publishing video reference.")
    target = root() / "assets" / filename
    if (
        target.is_symlink()
        or not target.is_file()
        or gm.media_sha256(target) != job["sha256"]
    ):
        raise ValueError(
            "The reviewed video snapshot is missing or changed. Prepare a new draft."
        )
    return target


def approve(job_id, *, reviewed=False):
    if reviewed is not True:
        raise ValueError("Review the video, channel and settings before approving.")
    with FileLock(root() / "catalog.lock"):
        with _lease(job_id):
            job = get(job_id)
            if job["state"] != "draft":
                raise ValueError("This post is already submitted or cancelled.")
            options(job["options"])
            client = _client(job)
            _channel(client, job)
            snapshot_file(job)
            if any(
                j["id"] != job_id
                and j["sha256"] == job["sha256"]
                and j["channel"]["channel_id"] == job["channel"]["channel_id"]
                and j["state"] not in {"draft", "cancelled"}
                for j in jobs()
            ):
                raise ValueError(
                    "Another delivery already exists for this video and channel."
                )
            job["state"] = "queued"
            job["approved_at"] = _stamp()
            _write(job, "Approved for delivery.")
    start(job_id)
    return get(job_id)


def _apply_result(job, data):
    provider_id = data.get("job_id")
    if isinstance(provider_id, str) and 0 < len(provider_id) <= 200:
        job["provider_job_id"] = provider_id
    request_id = data.get("request_id")
    if isinstance(request_id, str) and 0 < len(request_id) <= 200:
        job["request_id"] = request_id
    results = data.get("results") or []
    if isinstance(results, dict):
        results = [
            {"platform": k, **v} for k, v in results.items() if isinstance(v, dict)
        ]
    if not isinstance(results, list):
        results = []
    result = next(
        (r for r in results if isinstance(r, dict) and r.get("platform") == "youtube"),
        {},
    )
    job["post_url"] = None
    url = result.get("post_url") or result.get("url")
    if isinstance(url, str):
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"youtube.com", "www.youtube.com", "youtu.be"}
            and not parsed.username
            and not parsed.password
        ):
            job["post_url"] = url
    state = str(result.get("status") or "").lower()
    if result.get("skipped") or state == "skipped":
        job["state"] = "blocked"
        message = "YouTube was skipped by the provider. Reconnect the channel and inspect the provider record."
    elif state in {"queued", "processing", "retryable", "pending"}:
        job["state"] = "processing"
        message = (
            "YouTube is processing or retrying this delivery; no new upload is needed."
        )
    elif result.get("success") is False or state == "failed":
        job["state"] = "failed"
        message = "YouTube delivery failed. Correct the account/settings and use Retry failed delivery."
    elif state == "completed" or (
        result.get("success") is True and data.get("status") == "completed"
    ):
        job["state"] = "completed"
        message = "YouTube upload completed with the selected visibility."
    elif data.get("status") in {"not_found", "failed", "completed"}:
        job["state"] = "unknown"
        message = "The provider has no confirmed YouTube result. Refresh status; do not upload again."
    else:
        job["state"] = (
            "scheduled"
            if job["options"]["scheduled_at"] and job.get("provider_job_id")
            else "processing"
        )
        message = (
            "Scheduled by Upload-Post."
            if job["state"] == "scheduled"
            else "Upload accepted; waiting for a confirmed YouTube result."
        )
    job["checked_at"] = _stamp()
    return _write(job, message)


def dispatch(job_id):
    with _lease(job_id):
        job = get(job_id)
        if job["state"] != "queued":
            return job
        try:
            client = _client(job)
            _channel(client, job)
            options(job["options"])
            path = snapshot_file(job)
        except ValueError as exc:
            job["state"] = "blocked"
            return _write(job, str(exc))
        job["state"] = "submitting"
        job["submitted_once"] = True
        _write(job, "Uploading the approved video snapshot…")
        try:
            response = client.upload(job, path)
        except ProviderError as exc:
            job["state"] = "unknown" if exc.uncertain else "rejected"
            if not exc.uncertain:
                job.pop("submitted_once", None)
            return _write(job, str(exc))
        return _apply_result(job, response)


def refresh(job_id):
    with _lease(job_id):
        job = get(job_id)
        if job["state"] == "queued" or (
            job["state"] in {"blocked", "rejected"} and not job.get("submitted_once")
        ):
            return job
        if job["state"] not in _ACTIVE | {"failed", "blocked", "rejected"}:
            return job
        client = _client(job)
        try:
            response = client.status(job)
        except ProviderError as exc:
            if exc.status == 404:
                job["state"] = "unknown"
                job["checked_at"] = _stamp()
                return _write(
                    job,
                    "No confirmed provider record yet. This video will not be sent again automatically.",
                )
            raise
        return _apply_result(job, response)


def cancel(job_id):
    with _lease(job_id):
        job = get(job_id)
        if job["state"] in {"draft", "queued"} or (
            job["state"] in {"blocked", "rejected"} and not job.get("submitted_once")
        ):
            job["state"] = "cancelled"
        elif job["state"] == "scheduled" and job.get("provider_job_id"):
            client = _client(job)
            job["state"] = "cancelling"
            _write(job, "Requesting cancellation from Upload-Post…")
            try:
                client.cancel(job)
            except ProviderError:
                job["state"] = "unknown"
                _write(
                    job,
                    "Cancellation is unconfirmed. Refresh status before making another post.",
                )
                raise
            job["state"] = "cancelled"
        else:
            raise ValueError(
                "Only drafts, queued posts and confirmed schedules can be cancelled here."
            )
        return _write(job, "Delivery cancelled.")


def retry(job_id, *, reviewed=False):
    if reviewed is not True:
        raise ValueError("Review the destination again before retrying.")
    with _lease(job_id):
        job = get(job_id)
        client = _client(job)
        _channel(client, job)
        if job["state"] in {"blocked", "rejected"} and "submitted_once" not in job:
            # Pre-upload failures can retry the same approved immutable request.
            job["state"] = "queued"
            _write(job, "Retry queued with the original duplicate-protection key.")
        elif job["state"] == "failed":
            job["state"] = "retrying"
            _write(job, "Retry requested for the failed YouTube destination only.")
            try:
                response = client.retry(job)
            except ProviderError:
                job["state"] = "unknown"
                _write(
                    job,
                    "Retry outcome is unconfirmed. Refresh status before taking another action.",
                )
                raise
            return _apply_result(job, response)
        else:
            raise ValueError(
                "An uncertain or completed upload cannot be resent. Refresh its status."
            )
    start(job_id)
    return get(job_id)


def _work():
    while True:
        job_id = _queue.get()
        try:
            dispatch(job_id)
        except Exception as exc:
            # Recovery only polls submitting jobs, never re-uploads them.
            logger.warning(
                "YouTube delivery worker interrupted: job={}, error={}",
                job_id,
                type(exc).__name__,
            )
            threading.Event().wait(0.2)
        finally:
            with _thread_lock:
                _enqueued.discard(job_id)
            _queue.task_done()
        if _queue.empty():
            for pending in reversed(jobs()):
                if pending["state"] == "queued":
                    start(pending["id"])


def start(job_id):
    global _worker_started
    with _thread_lock:
        if job_id in _enqueued:
            return
        if not _worker_started:
            threading.Thread(
                target=_work, name="youtube-publishing", daemon=True
            ).start()
            _worker_started = True
        try:
            _queue.put_nowait(job_id)
            _enqueued.add(job_id)
        except Full:
            pass  # Durable queued jobs remain visible and can be resumed.


def recover():
    """Resume only approved work; opening a page never approves a draft."""
    for job in jobs():
        if job["state"] == "queued":
            start(job["id"])
        elif job["state"] in {"submitting", "retrying", "cancelling"}:
            try:
                with _lease(job["id"]):
                    current = get(job["id"])
                    if current["state"] in {"submitting", "retrying", "cancelling"}:
                        current["state"] = "unknown"
                        _write(
                            current,
                            "Interrupted provider operation. Refresh status to recover its result; no upload was repeated.",
                        )
            except ValueError:
                pass


def cached_channels():
    target = root() / "channels.json"
    if (
        target.is_file()
        and not target.is_symlink()
        and target.stat().st_size <= 1024 * 1024
    ):
        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get("credential_id") == publisher.credential_id:
            return data
    return {"channels": [], "checked_at": None}


def refresh_channels():
    client = _client()
    data = {
        "credential_id": client.credential_id,
        "channels": client.profiles(),
        "checked_at": _stamp(),
    }
    scene_planner._atomic_write_json(root() / "channels.json", data)
    return data


def assert_account_editable(profile):
    if any(
        j["channel"]["profile"] == profile and j["state"] in _ACTIVE for j in jobs()
    ):
        raise ValueError(
            "Cancel or finish this profile’s pending deliveries before changing its connected channel."
        )
