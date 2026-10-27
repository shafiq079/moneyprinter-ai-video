"""Reviewed direct Meta deliveries, independent from Google and Upload-Post."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from queue import Queue, Full
from urllib.parse import urlsplit

from filelock import FileLock, Timeout
from loguru import logger

from app.services import (
    facebook_accounts as accounts,
    youtube_accounts as crypto,
    youtube_studio as legacy,
)
from app.services.facebook_graph import FacebookPage, MetaError, numeric_id
from app.utils import utils

ACTIVE = {
    "queued",
    "initiating",
    "uploading",
    "paused",
    "ready",
    "finalizing",
    "processing",
    "scheduled",
    "unknown",
    "blocked",
    "cancelling",
}
_queue = Queue(32)
_guard = threading.Lock()
_enqueued = set()
_started = False


def root():
    target = accounts.directory() / "jobs"
    if target.is_symlink():
        raise ValueError("Invalid Facebook delivery storage.")
    target.mkdir(exist_ok=True)
    return target


def _path(jid):
    if not isinstance(jid, str) or not re.fullmatch(r"[a-f0-9]{32}", jid):
        raise ValueError("Invalid Facebook delivery ID.")
    return root() / (jid + ".enc")


def _get(jid):
    job = crypto.read_secret(_path(jid))
    if not isinstance(job, dict):
        raise ValueError("Facebook delivery is unavailable.")
    return job


def get(jid):
    return {
        k: v
        for k, v in _get(jid).items()
        if k not in {"upload_url", "upload_session_id"}
    }


def jobs():
    return sorted(
        [get(p.stem) for p in root().glob("*.enc")],
        key=lambda j: j["created_at"],
        reverse=True,
    )


def _write(job, message=None):
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    if message:
        job["message"] = message
        job.setdefault("events", []).append(
            {"at": job["updated_at"], "state": job["state"], "message": message}
        )
        job["events"] = job["events"][-30:]
    crypto.write_secret(_path(job["id"]), job)
    return get(job["id"])


@contextmanager
def lease(jid):
    try:
        with FileLock(str(_path(jid)) + ".lock", timeout=0):
            yield
    except Timeout as exc:
        raise ValueError("Facebook delivery is busy. Refresh shortly.") from exc


def options(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid Facebook settings.")
    title, description = value.get("title"), value.get("description", "")
    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 100
        or any(c in title for c in "\n\r")
    ):
        raise ValueError(
            "Enter a Facebook title of 1–100 characters without line breaks."
        )
    if not isinstance(description, str) or len(description) > 5000:
        raise ValueError("Facebook description must contain at most 5000 characters.")
    if (
        value.get("media_type") not in {"VIDEO", "REELS"}
        or type(value.get("synthetic")) is not bool
    ):
        raise ValueError(
            "Choose Page video or Reel and review the AI content declaration."
        )
    when = value.get("scheduled_at") or None
    if when:
        try:
            if isinstance(when, str):
                parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Scheduled time needs a timezone.")
                when = int(parsed.timestamp())
            else:
                when = int(when)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid Facebook scheduled time.") from exc
        if not time.time() + 15 * 60 <= when <= time.time() + 7 * 86400:
            raise ValueError(
                "Facebook scheduling in this app requires 15 minutes to seven days of notice."
            )
    return {
        "title": title.strip(),
        "description": description,
        "media_type": value["media_type"],
        "synthetic": value["synthetic"],
        "scheduled_at": when,
        "timezone": str(value.get("timezone") or "UTC")[:80],
    }


def _client(job):
    record = accounts.credential_record(job["connection_id"])
    if record["page_id"] != job["page"]["page_id"] or record["app"] != job["app"]:
        raise ValueError(
            "Facebook app or Page changed. Restore the approved connection."
        )
    client = FacebookPage(job["connection_id"])
    client.verify_page(job["page"]["page_id"])
    return client


def _duplicate(source_hash, page_id, exclude=None):
    if any(
        j["id"] != exclude
        and j["source_sha256"] == source_hash
        and j["page"]["page_id"] == page_id
        and j["state"] not in {"draft", "cancelled", "deleted"}
        for j in jobs()
    ):
        raise ValueError(
            "Another direct delivery already exists for this video and Facebook Page."
        )
    if any(
        j["sha256"] == source_hash
        and j["channel"]["channel_id"] == page_id
        and j["state"] not in {"draft", "cancelled"}
        for j in legacy.jobs("facebook")
    ):
        raise ValueError(
            "A legacy Upload-Post delivery already exists for this video and Page. Resolve it first."
        )


def _freeze(task_id, relative, settings):
    source = legacy.source_file(task_id, relative)
    before = source.stat()
    original_hash = legacy.gm.media_sha256(source)
    if shutil.disk_usage(legacy.root()).free < before.st_size * 2 + 32 * 1024 * 1024:
        raise ValueError("Not enough storage to prepare this Facebook video.")
    token = uuid.uuid4().hex
    raw = legacy.root() / "assets" / ("." + token + source.suffix)
    output = legacy.root() / "assets" / ("." + token + ".facebook.mp4")
    try:
        shutil.copyfile(source, raw)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ) or legacy.gm.media_sha256(raw) != original_hash:
            raise ValueError(
                "Video changed during preparation. Wait for rendering to finish."
            )
        if source.suffix == ".webm":
            try:
                subprocess.run(
                    [
                        utils.get_ffmpeg_binary(),
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(raw),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0?",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "20",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-movflags",
                        "+faststart",
                        "-fs",
                        str(legacy.MAX_VIDEO + 1),
                        str(output),
                    ],
                    check=True,
                    timeout=300,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                raise ValueError(
                    "WebM could not be converted to MP4 within five minutes. Export MP4 or use a shorter video."
                ) from exc
        else:
            os.replace(raw, output)
        if not 0 < output.stat().st_size <= legacy.MAX_VIDEO:
            raise ValueError("Prepared Facebook MP4 exceeds 512 MiB.")
        clip = None
        try:
            clip = legacy.video._open_video_clip_quietly(str(output))
            if not 0 < clip.duration <= 3600 or min(clip.size) <= 0:
                raise ValueError("Choose a valid video of at most one hour.")
            if settings["media_type"] == "REELS" and not (
                4 <= clip.duration <= 60
                and clip.w >= 540
                and clip.h >= 960
                and abs(clip.w / clip.h - 9 / 16) <= 0.015
                and 24 <= clip.fps <= 60
            ):
                raise ValueError(
                    "Reels in this app require 4–60 seconds, 9:16, at least 540×960 and 24–60 fps. Choose Page video or re-export."
                )
            clip.get_frame(0)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                "Facebook video could not be decoded. Re-export it before publishing."
            ) from exc
        finally:
            if clip is not None:
                legacy.video.close_clip(clip)
        digest = legacy.gm.media_sha256(output)
        destination = legacy.root() / "assets" / (digest + ".mp4")
        if (
            destination.is_symlink()
            or not destination.exists()
            or legacy.gm.media_sha256(destination) != digest
        ):
            os.replace(output, destination)
        return original_hash, digest, destination
    finally:
        raw.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


def prepare(task_id, relative, cid, value, *, publishing_package=None):
    settings = options(value)
    record = accounts.credential_record(cid)
    page = FacebookPage(cid).verify_page(record["page_id"])
    with FileLock(legacy.root() / "catalog.lock"):
        if len(jobs()) >= 1000:
            raise ValueError("Facebook delivery history reached its 1000-job limit.")
        source_hash, digest, path = _freeze(task_id, relative, settings)
        from app.services import publishing_seo

        preparation = publishing_seo.audit(
            publishing_package, task_id, relative, "facebook", source_hash
        )
        _duplicate(source_hash, page["page_id"])
        job = {
            "id": uuid.uuid4().hex,
            "backend": "meta",
            "platform": "facebook",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "draft",
            "task_id": task_id,
            "source": relative,
            "source_sha256": source_hash,
            "sha256": digest,
            "asset": path.name,
            "size": path.stat().st_size,
            "mime": "video/mp4",
            "connection_id": cid,
            "page": page,
            "app": record["app"],
            "options": settings,
            "publishing_preparation": preparation,
            "video_id": None,
            "offset": 0,
            "events": [],
        }
        return _write(
            job,
            "Facebook draft prepared. Review the exact MP4, Page ID and public publication settings.",
        )


def approve(jid, reviewed=False):
    if reviewed is not True:
        raise ValueError(
            "Review the Facebook video, Page and public publishing settings first."
        )
    with FileLock(legacy.root() / "catalog.lock"), lease(jid):
        job = _get(jid)
        if job["state"] != "draft":
            raise ValueError("This Facebook delivery is already approved or cancelled.")
        options(job["options"])
        _client(job)
        legacy.snapshot_file(job)
        _duplicate(job["source_sha256"], job["page"]["page_id"], jid)
        job["state"] = "queued"
        _write(job, "Approved for direct Meta upload and publication.")
    enqueue(jid)
    return get(jid)


def _range(job, data):
    try:
        start, end = int(data["start_offset"]), int(data["end_offset"])
    except (ValueError, TypeError, KeyError) as exc:
        raise MetaError(uncertain=True) from exc
    if (
        not 0 <= start <= end <= job["size"]
        or end - start > 32 * 1024 * 1024
        or (start == end and start != job["size"])
    ):
        raise ValueError("Meta returned invalid video offsets.")
    job.update(
        offset=start, end_offset=end, transfer_complete=start == end == job["size"]
    )


def dispatch(jid):
    with lease(jid):
        job = _get(jid)
        if job["state"] != "queued":
            return get(jid)
        try:
            client = _client(job)
            path = legacy.snapshot_file(job)
            if not job.get("video_id"):
                job["state"] = "initiating"
                _write(job, "Creating the reviewed Page upload session.")
                data = client.initiate(job)
                job["video_id"] = numeric_id(str(data["video_id"]))
                if job["options"]["media_type"] == "REELS":
                    job["upload_url"] = data["upload_url"]
                else:
                    job["upload_session_id"] = numeric_id(
                        str(data["upload_session_id"])
                    )
                    _range(job, data)
                job["state"] = "uploading"
                _write(job, "Meta video ID saved before transferring any media.")
            if not job.get("transfer_complete"):
                if job["options"]["media_type"] == "REELS":
                    if job.get("transfer_attempted"):
                        return _sync(job, client)
                    job["transfer_attempted"] = True
                    _write(job, "Uploading the reviewed Reel bytes.")
                    client.transfer(job, path)
                    job.update(offset=job["size"], transfer_complete=True)
                    _write(
                        job, "Meta accepted the Reel transfer; publication is separate."
                    )
                else:
                    stalls = 0
                    while not job.get("transfer_complete"):
                        previous = job["offset"]
                        try:
                            result = client.transfer(job, path)
                        except MetaError as exc:
                            if not exc.offsets:
                                raise
                            result = exc.offsets
                        _range(job, result)
                        stalls = stalls + 1 if job["offset"] <= previous else 0
                        if stalls >= 3:
                            raise MetaError(uncertain=True)
                        _write(job, "Meta confirmed the next Page video byte range.")
            return _finish(job, client)
        except (ValueError, OSError) as exc:
            if (
                job.get("finish_attempted")
                or job.get("video_id")
                and getattr(exc, "uncertain", False)
            ):
                job["state"] = "unknown"
            elif job.get("video_id"):
                job["state"] = "paused"
            else:
                job["state"] = (
                    "unknown"
                    if job["state"] == "initiating" and getattr(exc, "uncertain", False)
                    else "blocked"
                )
            return _write(
                job,
                "Local Facebook video storage is unavailable."
                if isinstance(exc, OSError)
                else str(exc),
            )


def _finish(job, client):
    when = job["options"]["scheduled_at"]
    if when and when <= time.time() + 10 * 60:
        job["state"] = "blocked"
        return _write(
            job,
            "The schedule is too close or passed before Meta acceptance. The upload was not published; explicitly choose a new time.",
        )
    job.update(state="finalizing", finish_attempted=True)
    _write(job, "Requesting the approved Facebook publication or Meta-owned schedule.")
    client.finish(job)
    job["finish_accepted"] = True
    _write(job, "Meta accepted the finish operation; checking actual video status.")
    return _sync(job, client)


def _sync(job, client):
    row = client.video(job["video_id"])
    owner = (row.get("from") or {}).get("id")
    if owner is not None and str(owner) != job["page"]["page_id"]:
        raise ValueError(
            "Meta video belongs to another Page. No further action was sent."
        )
    status = row.get("status") or {}
    phases = [
        status.get(p, {})
        for p in ("uploading_phase", "processing_phase", "publishing_phase")
    ]
    if status.get("video_status") in {"error", "failed"} or any(
        p.get("status") in {"error", "failed"} for p in phases
    ):
        job["state"] = "failed"
        message = "Meta reports a failed video. Inspect its status; no new upload was started."
    elif row.get("published") is True and (
        status.get("video_status") == "ready" or phases[2].get("status") == "complete"
    ):
        job["state"] = "published"
        message = "Meta confirms this Facebook video is published."
    elif (
        job["options"]["scheduled_at"]
        and row.get("published") is False
        and _timestamp(row.get("scheduled_publish_time"))
        == job["options"]["scheduled_at"]
    ):
        job["state"] = "scheduled"
        message = "Meta confirms the scheduled publication time. Processing or Page restrictions can still delay publication."
    elif job.get("finish_accepted"):
        job["state"] = "processing"
        message = "Meta accepted publication; final availability is not confirmed yet."
    elif job.get("finish_attempted"):
        job["state"] = "unknown"
        message = "Publication outcome is unconfirmed. Refresh the same video; do not create another upload."
    elif job.get("transfer_complete") or phases[0].get("status") == "complete":
        job.update(state="ready", transfer_complete=True, offset=job["size"])
        message = "Meta received the video. Review and resume to finish the original delivery."
    else:
        job["state"] = "paused"
        message = "Upload transfer is incomplete or unconfirmed. Page video sessions can resume; Reel bytes will not be resent blindly."
    url = row.get("permalink_url")
    if isinstance(url, str):
        parsed = urlsplit(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"}
            and not parsed.username
            and not parsed.password
        ):
            job["post_url"] = url
    job["checked_at"] = time.time()
    return _write(job, message)


def _timestamp(value):
    try:
        return (
            int(value)
            if isinstance(value, (int, float))
            or isinstance(value, str)
            and value.isdigit()
            else int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        )
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def refresh(jid):
    with lease(jid):
        job = _get(jid)
        if job.get("video_id") and job["state"] not in {
            "cancelled",
            "deleted",
            "draft",
        }:
            return _sync(job, _client(job))
        return get(jid)


def resume(jid, reviewed=False):
    if not reviewed:
        raise ValueError("Review the Facebook Page and delivery before resuming.")
    with lease(jid):
        job = _get(jid)
        if job["state"] not in {"paused", "ready", "unknown", "blocked"}:
            raise ValueError("This delivery cannot be resumed in its current state.")
        client = _client(job)
        if job.get("video_id"):
            _sync(job, client)
            job = _get(jid)
            if job["state"] in {"published", "scheduled", "failed"}:
                return get(jid)
            if job.get("finish_attempted"):
                raise ValueError(
                    "Publication was already requested. Refresh or inspect Meta before another action."
                )
            if (
                job["options"]["media_type"] == "REELS"
                and job.get("transfer_attempted")
                and not job.get("transfer_complete")
            ):
                raise ValueError(
                    "Reel transfer is unconfirmed. Refresh status; its bytes cannot be resent safely."
                )
        elif job["state"] == "unknown":
            raise ValueError(
                "Upload initialization is unconfirmed. Inspect Meta; a new upload will not be started automatically."
            )
        job["state"] = "queued"
        _write(job, "Resume approved for the existing Facebook delivery.")
    enqueue(jid)
    return get(jid)


def cancel(jid, reviewed=False):
    if not reviewed:
        raise ValueError(
            "Confirm cancellation and deletion of any unpublished Facebook upload."
        )
    with lease(jid):
        job = _get(jid)
        if job["state"] in {"initiating", "uploading", "finalizing"}:
            raise ValueError("Facebook upload is busy. Wait for it to finish or pause.")
        if job["state"] == "unknown" and not job.get("video_id"):
            raise ValueError(
                "Meta upload initialization is unconfirmed. Inspect Meta before resolving this delivery; cancellation cannot confirm that no remote upload exists."
            )
        if job.get("video_id"):
            client = _client(job)
            row = client.video(job["video_id"], job["page"]["page_id"])
            if row.get("published") is not False:
                raise ValueError(
                    "Meta does not confirm this video is unpublished. Use Content for explicit permanent deletion."
                )
            job["state"] = "cancelling"
            _write(job, "Deleting the unpublished Meta video to cancel this delivery.")
            try:
                client.delete(job["video_id"])
            except ValueError:
                job["state"] = "unknown"
                _write(
                    job,
                    "Meta deletion/cancellation is unconfirmed. Refresh before creating another delivery.",
                )
                raise
        job["state"] = "cancelled"
        return _write(
            job,
            "Delivery cancelled. Any known unpublished Meta upload was deleted; the local video/project is retained.",
        )


def reschedule(jid, when, reviewed=False):
    if not reviewed:
        raise ValueError("Review the new Facebook publication time.")
    with lease(jid):
        job = _get(jid)
        if not job.get("video_id") or job["state"] not in {
            "scheduled",
            "ready",
            "blocked",
            "unknown",
        }:
            raise ValueError("Choose an uploaded pending Facebook delivery.")
        settings = options(job["options"] | {"scheduled_at": when})
        client = _client(job)
        row = client.video(job["video_id"], job["page"]["page_id"])
        if row.get("published") is not False:
            raise ValueError("Meta does not confirm this video is unpublished.")
        job["options"] = settings
        _write(job, "New Facebook publication time explicitly approved.")
        if not job.get("finish_attempted") and job.get("transfer_complete"):
            return _finish(job, client)
        job["state"] = "unknown"
        _write(job, "Updating the existing Meta video schedule; no new upload is sent.")
        client.update(
            job["video_id"],
            published="false",
            scheduled_publish_time=str(settings["scheduled_at"]),
        )
        return _sync(job, client)


def edit_video(cid, identity, title, description, reviewed=False, revision=None):
    if not reviewed:
        raise ValueError("Review Facebook metadata changes before saving.")
    settings = options(
        {
            "title": title,
            "description": description,
            "media_type": "VIDEO",
            "synthetic": False,
        }
    )
    with FileLock(legacy.root() / "catalog.lock"):
        if any(j.get("video_id") == identity and j["state"] in ACTIVE for j in jobs()):
            raise ValueError(
                "Manage this pending delivery from Calendar / Queue first."
            )
        record = accounts.credential_record(cid)
        client = FacebookPage(cid)
        client.verify_page(record["page_id"])
        row = client.video(identity, record["page_id"])
        if revision and row.get("updated_time") != revision:
            raise ValueError(
                "Facebook video changed since review. Reload before saving."
            )
        return client.update(
            identity, name=settings["title"], description=settings["description"]
        )


def delete_video(cid, identity, confirmation):
    if confirmation != identity:
        raise ValueError("Type the exact Facebook video ID to confirm deletion.")
    with FileLock(legacy.root() / "catalog.lock"):
        if any(j.get("video_id") == identity and j["state"] in ACTIVE for j in jobs()):
            raise ValueError("Cancel the pending delivery before deleting this video.")
        record = accounts.credential_record(cid)
        client = FacebookPage(cid)
        client.verify_page(record["page_id"])
        client.video(identity, record["page_id"])
        client.delete(identity)
        for item in jobs():
            if item.get("video_id") == identity:
                with lease(item["id"]):
                    job = _get(item["id"])
                    job["state"] = "deleted"
                    _write(
                        job,
                        "Facebook video permanently deleted after explicit confirmation.",
                    )


def _work():
    failed = set()
    while True:
        jid = _queue.get()
        try:
            dispatch(jid)
        except Exception as exc:
            failed.add(jid)
            logger.warning(
                "Direct Facebook worker interrupted: job={}, error={}",
                jid,
                type(exc).__name__,
            )
        finally:
            with _guard:
                _enqueued.discard(jid)
            _queue.task_done()
        try:
            pending = jobs()
        except (ValueError, OSError):
            continue
        for job in reversed(pending):
            if job["state"] == "queued" and job["id"] not in failed:
                enqueue(job["id"])


def enqueue(jid):
    global _started
    with _guard:
        if jid in _enqueued:
            return
        if not _started:
            threading.Thread(target=_work, name="direct-facebook", daemon=True).start()
            _started = True
        try:
            _queue.put_nowait(jid)
            _enqueued.add(jid)
        except Full:
            pass


def recover():
    for item in jobs():
        if item["state"] == "queued":
            enqueue(item["id"])
        elif item["state"] in {"initiating", "uploading", "finalizing", "cancelling"}:
            try:
                with lease(item["id"]):
                    job = _get(item["id"])
                    if job["state"] in {
                        "initiating",
                        "uploading",
                        "finalizing",
                        "cancelling",
                    }:
                        job["state"] = (
                            "unknown"
                            if job.get("finish_attempted")
                            or not job.get("video_id")
                            or job["state"] == "cancelling"
                            else "paused"
                        )
                        _write(
                            job,
                            "Facebook operation interrupted. Reconcile the original video before resuming.",
                        )
            except ValueError:
                pass
