"""Durable direct YouTube deliveries, isolated from legacy Upload-Post jobs."""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from queue import Queue, Full

from filelock import FileLock, Timeout
from loguru import logger

from app.services import youtube_accounts as accounts, youtube_studio as legacy
from app.services.youtube_google import GoogleYouTube, YouTubeError, video_id

ACTIVE = {
    "queued",
    "initiating",
    "uploading",
    "paused",
    "processing",
    "release_pending",
    "scheduled",
    "unknown",
    "blocked",
}
_queue = Queue(32)
_guard = threading.Lock()
_enqueued = set()
_started = False


def root():
    target = accounts.directory() / "jobs"
    if target.is_symlink():
        raise ValueError("Invalid direct publishing directory.")
    target.mkdir(exist_ok=True)
    return target


def _path(jid):
    if not isinstance(jid, str) or not re.fullmatch(r"[a-f0-9]{32}", jid):
        raise ValueError("Invalid delivery ID.")
    return root() / (jid + ".enc")


def _get(jid):
    job = accounts.read_secret(_path(jid))
    if not isinstance(job, dict):
        raise ValueError("Direct YouTube delivery is unavailable.")
    return job


def get(jid):
    return {k: v for k, v in _get(jid).items() if k != "upload_uri"}


def jobs():
    result = []
    for path in root().glob("*.enc"):
        result.append(get(path.stem))
    return sorted(result, key=lambda j: j["created_at"], reverse=True)


def _write(job, message=None):
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    if message:
        job["message"] = message
        job.setdefault("events", []).append(
            {"at": job["updated_at"], "state": job["state"], "message": message}
        )
        job["events"] = job["events"][-30:]
    accounts.write_secret(_path(job["id"]), job)
    return get(job["id"])


@contextmanager
def lease(jid):
    try:
        with FileLock(str(_path(jid)) + ".lock", timeout=0):
            yield
    except Timeout as exc:
        raise ValueError("This delivery is busy. Refresh shortly.") from exc


def options(value):
    normalized = legacy.options(value)
    category = str(value.get("category", "22"))
    if not re.fullmatch(r"[1-9][0-9]{0,2}", category):
        raise ValueError("Enter a valid YouTube category ID.")
    if normalized["scheduled_at"] and normalized["privacy"] != "public":
        raise ValueError(
            "Scheduled publication goes public. Choose public visibility or keep the video private without a schedule."
        )
    return normalized | {"category": category}


def _client(job):
    record = accounts.credential_record(job["connection_id"])
    if (
        record["channel_id"] != job["channel"]["channel_id"]
        or record["app"] != job["app"]
    ):
        raise ValueError(
            "The channel or Google app changed. Restore the approved connection."
        )
    client = GoogleYouTube(job["connection_id"])
    client.verify_channel(job["channel"]["channel_id"])
    return client


def prepare(task_id, relative, cid, value, *, publishing_package=None, thumbnail=None):
    settings = options(value)
    record = accounts.credential_record(cid)
    channel = GoogleYouTube(cid).verify_channel(record["channel_id"])
    source = legacy.source_file(task_id, relative)
    before = source.stat()
    digest = legacy.gm.media_sha256(source)
    from app.services import publishing_seo

    preparation = publishing_seo.audit(
        publishing_package, task_id, relative, "youtube", digest
    )
    if thumbnail:
        if thumbnail.get("source_sha256") != digest:
            raise ValueError("Thumbnail belongs to a changed video. Build it again.")
        publishing_seo.thumbnail_file(thumbnail)
    with FileLock(legacy.root() / "catalog.lock"):
        if len(jobs()) >= 1000:
            raise ValueError("Direct delivery history reached its 1000-job limit.")
        _duplicate(digest, channel["channel_id"])
        # Protect against deliberate duplication of an outstanding legacy delivery.
        if any(
            j["sha256"] == digest
            and j["channel"]["channel_id"] == channel["channel_id"]
            and j["state"] not in {"draft", "cancelled"}
            for j in legacy.jobs()
        ):
            raise ValueError(
                "This video already has a legacy Upload-Post delivery to this channel. Resolve that record first."
            )
        if shutil.disk_usage(legacy.root()).free < before.st_size + 16 * 1024 * 1024:
            raise ValueError("Not enough storage to freeze this video.")
        target = legacy.root() / "assets" / (digest + source.suffix)
        temporary = target.with_name("." + uuid.uuid4().hex + source.suffix)
        try:
            shutil.copyfile(source, temporary)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ) or legacy.gm.media_sha256(temporary) != digest:
                raise ValueError(
                    "Video changed while preparing review. Wait for rendering to finish."
                )
            clip = None
            try:
                clip = legacy.video._open_video_clip_quietly(str(temporary))
                if not 0 < clip.duration <= 3600 or min(clip.size) <= 0:
                    raise ValueError("Choose a valid video of at most one hour.")
                clip.get_frame(0)
            except Exception as exc:
                raise ValueError(
                    "Video could not be decoded. Re-export it before publishing."
                ) from exc
            finally:
                if clip is not None:
                    legacy.video.close_clip(clip)
            if (
                target.is_symlink()
                or not target.exists()
                or legacy.gm.media_sha256(target) != digest
            ):
                os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        job = {
            "id": uuid.uuid4().hex,
            "backend": "google",
            "platform": "youtube",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "draft",
            "task_id": task_id,
            "source": relative,
            "sha256": digest,
            "asset": target.name,
            "size": before.st_size,
            "mime": mimetypes.guess_type(source.name)[0] or "video/mp4",
            "connection_id": cid,
            "channel": channel,
            "app": record["app"],
            "options": settings,
            "publishing_preparation": preparation,
            "thumbnail": thumbnail,
            "offset": 0,
            "video_id": None,
            "events": [],
        }
        return _write(
            job, "Draft prepared. Review the frozen video, channel and settings."
        )


def _duplicate(digest, channel, exclude=None):
    if any(
        j["id"] != exclude
        and j["sha256"] == digest
        and j["channel"]["channel_id"] == channel
        and j["state"] not in {"draft", "cancelled", "deleted"}
        for j in jobs()
    ):
        raise ValueError(
            "Another direct delivery already exists for this video and channel."
        )


def approve(jid, reviewed=False):
    if reviewed is not True:
        raise ValueError("Review the video, destination and publishing settings first.")
    with FileLock(legacy.root() / "catalog.lock"), lease(jid):
        job = _get(jid)
        if job["state"] != "draft":
            raise ValueError("This delivery is already approved or cancelled.")
        options(job["options"])
        if any(
            j["sha256"] == job["sha256"]
            and j["channel"]["channel_id"] == job["channel"]["channel_id"]
            and j["state"] not in {"draft", "cancelled"}
            for j in legacy.jobs()
        ):
            raise ValueError(
                "A legacy delivery now exists for this video. Resolve it before approving direct delivery."
            )
        _client(job)
        legacy.snapshot_file(job)
        if job.get("thumbnail"):
            from app.services import publishing_seo

            publishing_seo.thumbnail_file(job["thumbnail"])
        _duplicate(job["sha256"], job["channel"]["channel_id"], jid)
        job["state"] = "queued"
        _write(job, "Approved for direct YouTube upload.")
    enqueue(jid)
    return get(jid)


def _received(job, response):
    if response.status_code == 308:
        value = response.headers.get("Range", "")
        if not value:
            job["offset"] = 0
        elif re.fullmatch(r"bytes=0-[0-9]+", value):
            job["offset"] = int(value.split("-")[1]) + 1
        else:
            raise YouTubeError(uncertain=True)
        if not 0 <= job["offset"] < job["size"]:
            raise YouTubeError(uncertain=True)
        return False
    try:
        data = response.json()
        identity = video_id(data["id"])
        if data.get("snippet", {}).get("channelId") != job["channel"]["channel_id"]:
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise YouTubeError(uncertain=True) from exc
    job.update(video_id=identity, offset=job["size"], state="processing")
    job.pop("upload_uri", None)
    return True


def dispatch(jid):
    with lease(jid):
        job = _get(jid)
        if job["state"] not in {"queued", "uploading"}:
            return get(jid)
        try:
            client = _client(job)
            path = legacy.snapshot_file(job)
            if not job.get("upload_uri"):
                job["state"] = "initiating"
                _write(job, "Starting a private resumable upload on YouTube.")
                job["upload_uri"] = client.initiate(job)
                job["state"] = "uploading"
                _write(job, "Resumable upload established.")
            # Always ask Google for its committed offset, including after restart.
            if _received(job, client.probe(job)):
                _write(
                    job, "YouTube received the video; checking publication settings."
                )
            else:
                stalls = 0
                while not job["video_id"]:
                    offset = job["offset"]
                    _received(job, client.chunk(job, path, offset))
                    stalls = stalls + 1 if job["offset"] <= offset else 0
                    if stalls >= 3:
                        raise YouTubeError(uncertain=True)
                    _write(
                        job,
                        "Uploading reviewed video bytes."
                        if not job["video_id"]
                        else "YouTube received the video.",
                    )
            return _sync(job, client, allow_release=True)
        except (YouTubeError, ValueError, OSError) as exc:
            if job.get("video_id"):
                job["state"] = "release_pending"
            elif job.get("upload_uri"):
                job["state"] = (
                    "unknown" if getattr(exc, "status", None) == 404 else "paused"
                )
            else:
                job["state"] = (
                    "unknown"
                    if job["state"] == "initiating" and getattr(exc, "uncertain", False)
                    else "blocked"
                )
            message = (
                "Local video or credential storage is unavailable. Restore storage access before resuming."
                if isinstance(exc, OSError)
                else str(exc)
            )
            return _write(job, message)


def _release(job, client):
    settings = job["options"]
    if settings["scheduled_at"] and datetime.fromisoformat(
        settings["scheduled_at"]
    ) <= datetime.now(timezone.utc):
        job["state"] = "release_pending"
        return _write(
            job,
            "The scheduled time passed before acceptance. The video remains private; choose a new time or explicitly publish now.",
        )
    row = client.owned_video(job["video_id"], job["channel"]["channel_id"])
    status = _writable_status(row)
    status["privacyStatus"] = (
        "private" if settings["scheduled_at"] else settings["privacy"]
    )
    status.pop("publishAt", None)
    if settings["scheduled_at"]:
        status["publishAt"] = settings["scheduled_at"]
    job["release_attempted"] = True
    job["state"] = "release_pending"
    _write(job, "Applying the reviewed YouTube publication settings.")
    client.update(job["video_id"], status=status)
    return None


def _sync(job, client, allow_release=False):
    row = client.owned_video(job["video_id"], job["channel"]["channel_id"])
    status = row.get("status", {})
    upload = status.get("uploadStatus")
    if upload in {"failed", "rejected", "deleted"}:
        job["state"] = "failed"
        return _write(
            job,
            "YouTube rejected or removed this video. Inspect it on YouTube; no upload will be repeated automatically.",
        )
    expected = job["options"]
    scheduled = status.get("publishAt")
    match_schedule = bool(
        expected["scheduled_at"]
        and scheduled
        and datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        == datetime.fromisoformat(expected["scheduled_at"])
    )
    matches = (
        status.get("privacyStatus") == expected["privacy"]
        and not expected["scheduled_at"]
    ) or match_schedule
    if job.get("thumbnail") and not job.get("thumbnail_applied") and not allow_release:
        job["state"] = "release_pending"
        return _write(
            job,
            "Reviewed thumbnail is still pending. Resume this delivery to apply it before completing publication.",
        )
    if allow_release and job.get("thumbnail") and not job.get("thumbnail_applied"):
        from app.services import publishing_seo

        data = publishing_seo.thumbnail_file(job["thumbnail"]).read_bytes()
        # Same-video thumbnail replacement is safe to repeat after a lost response.
        set_thumbnail(job["connection_id"], job["video_id"], data, reviewed=True)
        job["thumbnail_applied"] = True
        _write(job, "Reviewed thumbnail accepted by YouTube.")
    if allow_release and not matches:
        if _release(job, client):
            return get(job["id"])
        return _sync(job, client)
    if match_schedule:
        job["state"] = "scheduled"
        message = "YouTube accepted the publication schedule. Processing or account restrictions can delay publication."
    elif expected["scheduled_at"] and status.get("privacyStatus") == "public":
        job["state"] = "published"
        message = "YouTube reports this video as public."
    elif matches and upload == "processed":
        job["state"] = (
            "published" if status.get("privacyStatus") == "public" else "completed"
        )
        message = "YouTube processed this video with the reviewed visibility."
    elif matches:
        job["state"] = "processing"
        message = "YouTube received this video and is still processing it."
    else:
        job["state"] = "release_pending"
        message = "The upload exists, but publication settings are unconfirmed. Review and finish delivery; no new video will be uploaded."
    job["checked_at"] = time.time()
    job["actual_privacy"] = status.get("privacyStatus")
    job["post_url"] = "https://www.youtube.com/watch?v=" + job["video_id"]
    return _write(job, message)


def refresh(jid):
    with lease(jid):
        job = _get(jid)
        if job.get("video_id") and job["state"] not in {
            "cancelled",
            "deleted",
            "draft",
        }:
            return _sync(job, _client(job))
        if job.get("upload_uri") and job["state"] in {"paused", "unknown", "uploading"}:
            client = _client(job)
            if _received(job, client.probe(job)):
                _write(job, "Recovered the uploaded YouTube video.")
                return _sync(
                    job, client, allow_release=not job.get("release_attempted")
                )
            job["state"] = "paused"
            return _write(
                job,
                "YouTube confirmed the received byte offset. Resume to send remaining bytes.",
            )
        return get(jid)


def resume(jid, reviewed=False):
    if not reviewed:
        raise ValueError("Review the channel and delivery again before resuming.")
    with lease(jid):
        job = _get(jid)
        _client(job)
        if job.get("video_id") and job["state"] == "release_pending":
            return _sync(job, _client(job), allow_release=True)
        if job["state"] not in {"paused", "blocked"} or (
            not job.get("upload_uri") and job["state"] != "blocked"
        ):
            raise ValueError(
                "This outcome cannot safely restart an upload. Refresh or inspect YouTube first."
            )
        job["state"] = "queued"
        _write(job, "Resume approved; the existing session will be reconciled first.")
    enqueue(jid)
    return get(jid)


def cancel(jid):
    with lease(jid):
        job = _get(jid)
        if job["state"] in {"initiating", "uploading"}:
            raise ValueError(
                "Upload is busy. Wait for it to finish or pause before cancelling delivery."
            )
        if job.get("video_id"):
            client = _client(job)
            row = client.owned_video(job["video_id"], job["channel"]["channel_id"])
            if row["status"]["privacyStatus"] == "public":
                raise ValueError(
                    "This video is already public. Use Content to change its visibility or delete it."
                )
            status = _writable_status(row)
            status.update(privacyStatus="private")
            status.pop("publishAt", None)
            job["state"] = "release_pending"
            _write(
                job,
                "Requesting schedule cancellation; uploaded video will remain private.",
            )
            client.update(job["video_id"], status=status)
            confirmation = client.owned_video(
                job["video_id"], job["channel"]["channel_id"]
            )
            if confirmation.get("status", {}).get(
                "privacyStatus"
            ) != "private" or confirmation.get("status", {}).get("publishAt"):
                raise ValueError(
                    "Schedule cancellation is unconfirmed. Refresh the delivery before another action."
                )
        job["state"] = "cancelled"
        return _write(
            job,
            "Delivery cancelled. Any uploaded video remains on YouTube; it was not deleted.",
        )


def _writable_status(row):
    return {
        k: v
        for k, v in row.get("status", {}).items()
        if k
        in {
            "privacyStatus",
            "license",
            "embeddable",
            "publicStatsViewable",
            "selfDeclaredMadeForKids",
            "containsSyntheticMedia",
            "publishAt",
        }
    }


def edit_video(cid, identity, value, reviewed=False, etag=None):
    if not reviewed:
        raise ValueError("Review remote video changes before saving.")
    with FileLock(legacy.root() / "catalog.lock"):
        if any(j.get("video_id") == identity and j["state"] in ACTIVE for j in jobs()):
            raise ValueError(
                "Manage this pending delivery from Queue before editing its remote video."
            )
        record = accounts.credential_record(cid)
        client = GoogleYouTube(cid)
        row = client.owned_video(identity, record["channel_id"])
        if etag and row.get("etag") != etag:
            raise ValueError(
                "YouTube video changed since review. Reload it before saving."
            )
        normalized = options(value)
        snippet = {
            k: v
            for k, v in row["snippet"].items()
            if k
            in {
                "title",
                "description",
                "tags",
                "categoryId",
                "defaultLanguage",
                "defaultAudioLanguage",
            }
        }
        snippet.update(
            title=normalized["title"],
            description=normalized["description"],
            tags=normalized["tags"],
            categoryId=normalized["category"],
        )
        status = _writable_status(row)
        status.update(
            privacyStatus=normalized["privacy"],
            selfDeclaredMadeForKids=normalized["made_for_kids"],
            containsSyntheticMedia=normalized["synthetic"],
        )
        if normalized["privacy"] != "private" or normalized["scheduled_at"]:
            status.pop("publishAt", None)
        if normalized["scheduled_at"]:
            if (
                row["status"].get("privacyStatus") != "private"
                or row["status"].get("publishAt") is None
            ):
                raise ValueError(
                    "Use scheduling on a new approved delivery. Existing videos can be edited without a new schedule."
                )
            status.update(privacyStatus="private", publishAt=normalized["scheduled_at"])
        # Remote metadata updates do not reupload media.
        return client.update(identity, snippet=snippet, status=status)


def delete_video(cid, identity, confirmation):
    if confirmation != identity:
        raise ValueError("Type the exact video ID to confirm permanent deletion.")
    with FileLock(legacy.root() / "catalog.lock"):
        if any(j.get("video_id") == identity and j["state"] in ACTIVE for j in jobs()):
            raise ValueError("Cancel the pending delivery before deleting this video.")
        record = accounts.credential_record(cid)
        client = GoogleYouTube(cid)
        client.owned_video(identity, record["channel_id"])
        client.delete(identity)
        for item in jobs():
            if item.get("video_id") == identity:
                with lease(item["id"]):
                    job = _get(item["id"])
                    job["state"] = "deleted"
                    _write(
                        job,
                        "Video permanently deleted from YouTube by explicit confirmation.",
                    )


def reschedule(jid, when, reviewed=False):
    if not reviewed:
        raise ValueError("Review the changed publication time first.")
    with lease(jid):
        job = _get(jid)
        if not job.get("video_id") or job["state"] not in {
            "scheduled",
            "release_pending",
        }:
            raise ValueError("Only an uploaded pending publication can be rescheduled.")
        client = _client(job)
        row = client.owned_video(job["video_id"], job["channel"]["channel_id"])
        if row["status"]["privacyStatus"] == "public":
            raise ValueError("This video has already been published.")
        job["options"] = options(
            job["options"] | {"scheduled_at": when, "privacy": "public"}
        )
        _write(job, "New publication time explicitly approved.")
        return _sync(job, client, allow_release=True)


def _work():
    failed = set()
    while True:
        jid = _queue.get()
        try:
            dispatch(jid)
        except Exception as exc:
            # A storage failure must not spin/requeue forever. Retain the durable
            # record and leave a future operator recovery attempt possible.
            failed.add(jid)
            logger.warning(
                "Direct YouTube worker interrupted: job={}, error={}",
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
            threading.Thread(target=_work, name="direct-youtube", daemon=True).start()
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
        elif item["state"] in {"initiating", "uploading"}:
            try:
                with lease(item["id"]):
                    job = _get(item["id"])
                    if job["state"] in {"initiating", "uploading"}:
                        job["state"] = "paused" if job.get("upload_uri") else "unknown"
                        _write(
                            job,
                            "Upload interrupted. Reconcile the existing session before resuming.",
                        )
            except ValueError:
                pass


def set_thumbnail(cid, identity, data, reviewed=False):
    if not reviewed:
        raise ValueError("Review the thumbnail before uploading it.")
    import io
    from PIL import Image

    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError("Choose a JPG or PNG thumbnail up to 10 MiB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"} or max(image.size) > 4096:
                raise ValueError()
            mime = "image/jpeg" if image.format == "JPEG" else "image/png"
            image.verify()
    except Exception as exc:
        raise ValueError(
            "Choose a valid JPG or PNG thumbnail up to 4096 pixels per side."
        ) from exc
    record = accounts.credential_record(cid)
    client = GoogleYouTube(cid)
    client.owned_video(identity, record["channel_id"])
    return client.request(
        "POST",
        "thumbnails/set",
        thumbnail=True,
        params={"videoId": video_id(identity), "uploadType": "media"},
        headers={"Content-Type": mime},
        data=data,
    )
