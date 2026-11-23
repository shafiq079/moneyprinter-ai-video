"""Reviewed direct Instagram Reel and TikTok inbox deliveries."""

import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from urllib.parse import urlsplit

import requests
from filelock import FileLock, Timeout

from app.services import facebook_accounts as meta, facebook_direct, publishing_seo
from app.services import (
    tiktok_accounts as tt,
    youtube_accounts as crypto,
    youtube_studio as media,
)
from app.services.facebook_graph import Graph, MetaError, numeric_id

_QUEUE = Queue(32)
_LOCK = threading.Lock()
_BUSY = set()
_STARTED = False
_CHUNK_SIZE = 16 * 1024 * 1024


def _tiktok_upload_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("TikTok returned an invalid upload destination.")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not re.fullmatch(
            r"(?:open-upload|upload(?:\.[a-z0-9-]+)?)\.tiktokapis\.com",
            url.hostname or "",
        )
        or url.port not in {None, 443}
        or url.username
        or url.password
        or url.path != "/video/"
        or not url.query
        or url.fragment
    ):
        raise ValueError("TikTok returned an invalid upload destination.")
    return value


class ShortVideoDeliveries:
    ACTIVE = {"queued", "uploading", "processing", "paused", "unknown", "blocked"}

    def __init__(self, platform):
        self.platform = platform

    def _root(self):
        path = (
            meta.directory() if self.platform == "instagram" else tt.directory()
        ) / ("instagram-jobs" if self.platform == "instagram" else "jobs")
        if path.is_symlink():
            raise ValueError("Invalid short-video publishing directory.")
        path.mkdir(exist_ok=True)
        return path

    def _path(self, jid):
        if not isinstance(jid, str) or not re.fullmatch(r"[a-f0-9]{32}", jid):
            raise ValueError("Invalid delivery ID.")
        return self._root() / (jid + ".enc")

    @contextmanager
    def lease(self, jid):
        try:
            with FileLock(str(self._path(jid)) + ".lock", timeout=0):
                yield
        except Timeout:
            raise ValueError("This delivery is busy. Refresh shortly.") from None

    def _get(self, jid):
        job = crypto.read_secret(self._path(jid))
        if not isinstance(job, dict):
            raise ValueError("This delivery is unavailable.")
        return job

    def get(self, jid):
        return {k: v for k, v in self._get(jid).items() if k != "upload_url"}

    def jobs(self):
        return sorted(
            (self.get(p.stem) for p in self._root().glob("*.enc")),
            key=lambda item: item["created_at"],
            reverse=True,
        )

    def _write(self, job, message=None):
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if message:
            job["message"] = message
        crypto.write_secret(self._path(job["id"]), job)
        return self.get(job["id"])

    def options(self, value):
        title, description = value.get("title"), value.get("description", "")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 100
            or "\n" in title
        ):
            raise ValueError("Enter a short title of up to 100 characters.")
        if not isinstance(description, str) or len(description) > 2200:
            raise ValueError("Keep the caption to 2,200 characters or fewer.")
        if value.get("scheduled_at"):
            raise ValueError("Choose delivery after approval for Instagram and TikTok.")
        if self.platform == "instagram" and type(value.get("synthetic")) is not bool:
            raise ValueError("Review the Instagram AI content disclosure.")
        return dict(
            title=title.strip(),
            description=description.strip(),
            scheduled_at=None,
            timezone="UTC",
            synthetic=bool(value.get("synthetic")),
        )

    def _credentials(self, cid, verify=False):
        if self.platform == "instagram":
            return meta.instagram_credentials(cid, verify=verify)
        return tt.credentials(cid)

    def _check(self, job, verify=False):
        record = self._credentials(job["connection_id"], verify)
        if record["identity"] != job["identity"] or record["app"] != job["app"]:
            raise ValueError(
                "The approved account changed. Restore that connection before proceeding."
            )
        return record

    def _duplicate(self, source_hash, identity, exclude=None):
        if any(
            j["source_sha256"] == source_hash
            and j["identity"] == identity
            and j["id"] != exclude
            and j["state"] not in {"draft", "cancelled", "failed"}
            for j in self.jobs()
        ):
            raise ValueError("A delivery already exists for this video and account.")

    def prepare(
        self,
        task_id,
        relative,
        cid,
        value,
        *,
        publishing_package=None,
        planner_reference=None,
    ):
        options = self.options(value)
        record = self._credentials(cid)
        with FileLock(media.root() / "catalog.lock"):
            if len(self.jobs()) >= 1000:
                raise ValueError("This platform reached its delivery history limit.")
            source_hash, digest, path = facebook_direct._freeze(
                task_id, relative, {"media_type": "VIDEO"}
            )
            clip = media.video._open_video_clip_quietly(str(path))
            try:
                if clip.duration < 3 or clip.duration > (
                    180 if self.platform == "instagram" else 600
                ):
                    raise ValueError(
                        "Use a Reel of 3–180 seconds or a TikTok video of 3–600 seconds."
                    )
                if self.platform == "instagram" and (
                    abs(clip.w / clip.h - 9 / 16) > 0.015
                    or clip.w < 540
                    or not 23 <= clip.fps <= 60
                ):
                    raise ValueError(
                        "Export Instagram Reels at 9:16, at least 540×960 and 23–60 fps."
                    )
            finally:
                media.video.close_clip(clip)
            self._duplicate(source_hash, record["identity"])
            audit = publishing_seo.audit(
                publishing_package, task_id, relative, self.platform, source_hash
            )
            now = datetime.now(timezone.utc).isoformat()
            job = dict(
                id=uuid.uuid4().hex,
                platform=self.platform,
                state="draft",
                created_at=now,
                task_id=task_id,
                source=relative,
                source_sha256=source_hash,
                sha256=digest,
                asset=path.name,
                size=path.stat().st_size,
                connection_id=cid,
                identity=record["identity"],
                account_name=record["name"],
                app=record["app"],
                options=options,
                publishing_preparation=audit,
                planner_reference=planner_reference,
                video_id=None,
            )
            return self._write(
                job, "Review the frozen video, account and delivery details."
            )

    def approve(self, jid, reviewed=False):
        if reviewed is not True:
            raise ValueError(
                "Review the video and destination before approving delivery."
            )
        with FileLock(media.root() / "catalog.lock"), self.lease(jid):
            job = self._get(jid)
            if job["state"] != "draft":
                raise ValueError("Only a draft can be approved.")
            self.options(job["options"])
            self._check(job)
            media.snapshot_file(job)
            self._duplicate(job["source_sha256"], job["identity"], jid)
            job["state"] = "queued"
            self._write(job, "Reviewed and queued for delivery.")
        enqueue(self, jid)
        return self.get(jid)

    def cancel(self, jid, reviewed=False):
        if reviewed is not True:
            raise ValueError("Confirm the cancellation first.")
        with self.lease(jid):
            job = self._get(jid)
            if job["state"] not in {"draft", "queued", "blocked"}:
                raise ValueError("This delivery has already left MoneyPrinter.")
            job["state"] = "cancelled"
            return self._write(job, "Cancelled before upload.")

    def _instagram_graph(self, record):
        return Graph(record["token"], meta.settings())

    def _instagram_upload(self, job, path, record):
        graph = self._instagram_graph(record)
        payload = graph.request(
            "POST",
            job["identity"] + "/media",
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": job["options"]["description"],
                "is_ai_generated": str(job["options"]["synthetic"]).lower(),
            },
        )
        identity = numeric_id(str(payload.get("id", "")))
        url = (
            "https://rupload.facebook.com/ig-api-upload/"
            + graph.settings["version"]
            + "/"
            + identity
        )
        if payload.get("uri") and payload["uri"] != url:
            raise ValueError(
                "Meta returned an unexpected Instagram upload destination."
            )
        job.update(video_id=identity, stage="uploading")
        self._write(job, "Instagram accepted a Reel container.")
        with path.open("rb") as source:
            response = requests.post(
                url,
                data=source,
                headers={
                    "Authorization": "OAuth " + record["token"],
                    "offset": "0",
                    "file_size": str(job["size"]),
                    "Content-Type": "application/octet-stream",
                },
                timeout=(10, 180),
                allow_redirects=False,
            )
        result = response.json()
        if (
            not 200 <= response.status_code < 300
            or not isinstance(result, dict)
            or result.get("success") is not True
        ):
            raise ValueError(
                "Meta did not confirm the Reel upload. Check the existing container."
            )
        job.update(state="processing", stage="processing")
        self._write(job, "Instagram is processing the Reel.")
        return self._instagram_status(job, graph)

    def _instagram_status(self, job, graph):
        result = graph.request("GET", job["video_id"], params={"fields": "status_code"})
        status = result.get("status_code")
        if status == "FINISHED" and job.get("stage") not in {"publishing", "published"}:
            job.update(state="unknown", stage="publishing")
            self._write(job, "Waiting for Instagram to confirm publication.")
            result = graph.request(
                "POST",
                job["identity"] + "/media_publish",
                data={"creation_id": job["video_id"]},
            )
            job.update(
                state="published",
                stage="published",
                post_id=numeric_id(str(result.get("id", ""))),
            )
            return self._write(job, "Instagram confirmed Reel publication.")
        if status == "PUBLISHED":
            job.update(state="published", stage="published")
            return self._write(job, "Instagram confirmed Reel publication.")
        if status in {"ERROR", "EXPIRED"}:
            job["state"] = "failed"
            return self._write(
                job, "Instagram reported that the Reel container failed or expired."
            )
        return self._write(job)

    @staticmethod
    def _tiktok_data(value):
        data = value.get("data")
        if not isinstance(data, dict):
            raise ValueError("TikTok returned an incomplete delivery response.")
        return data

    def _tiktok_upload(self, job, path, record, replay=False):
        size = job["size"]
        chunk = min(size, _CHUNK_SIZE)
        count = size // chunk
        if not replay:
            response = tt.request(
                "POST",
                "/v2/post/publish/inbox/video/init/",
                token=record["token"],
                json={
                    "source_info": dict(
                        source="FILE_UPLOAD",
                        video_size=size,
                        chunk_size=chunk,
                        total_chunk_count=count,
                    ),
                },
            )
            result = self._tiktok_data(response)
            identity = result.get("publish_id")
            if not isinstance(identity, str) or not re.fullmatch(
                r"[a-zA-Z0-9_~.-]{1,200}", identity
            ):
                raise ValueError("TikTok did not return a usable delivery ID.")
            job["video_id"] = identity
            job.update(
                upload_url=_tiktok_upload_url(result.get("upload_url")),
                upload_expires=time.time() + 3600,
                offset=0,
            )
            self._write(job, "TikTok accepted an inbox upload slot.")
        url = _tiktok_upload_url(job["upload_url"])
        with path.open("rb") as stream:
            stream.seek(job["offset"])
            for index in range(job["offset"] // chunk, count):
                start = job["offset"]
                end = size if index == count - 1 else start + chunk
                data = stream.read(end - start)
                if len(data) != end - start:
                    raise ValueError("The approved video could not be read.")
                response = requests.put(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {start}-{end - 1}/{size}",
                    },
                    timeout=(10, 120),
                    allow_redirects=False,
                )
                if response.status_code != (201 if end == size else 206):
                    raise ValueError("TikTok did not confirm this upload range.")
                job["offset"] = end
                self._write(job)
        job.update(state="processing")
        job.pop("upload_url", None)
        return self._write(job, "TikTok is processing the video for the creator inbox.")

    def _tiktok_status(self, job, record):
        response = tt.request(
            "POST",
            "/v2/post/publish/status/fetch/",
            token=record["token"],
            json={"publish_id": job["video_id"]},
        )
        result = self._tiktok_data(response)
        status = result.get("status")
        outcomes = {
            "SEND_TO_USER_INBOX": (
                "inbox",
                "Open the TikTok inbox notification to add your caption, disclosures and publish.",
            ),
            "PUBLISH_COMPLETE": (
                "published",
                "TikTok confirmed that the creator published the video.",
            ),
            "FAILED": ("failed", "TikTok reported that the inbox delivery failed."),
        }
        if status in outcomes:
            job["state"], message = outcomes[status]
            job.pop("upload_url", None)
            self._write(job, message)
        return result

    def dispatch(self, jid):
        with self.lease(jid):
            job = self._get(jid)
            if job["state"] == "processing" and self.platform == "instagram":
                try:
                    return self._instagram_status(
                        job, self._instagram_graph(self._check(job))
                    )
                except (ValueError, OSError):
                    job["state"] = "unknown"
                    return self._write(
                        job, "Refresh this Reel after checking Meta access and status."
                    )
            if job["state"] != "queued":
                return
            try:
                record = self._check(job, verify=True)
                path = media.snapshot_file(job)
            except (ValueError, OSError):
                job["state"] = "blocked"
                return self._write(
                    job,
                    "Restore the approved account and video, then resume this delivery.",
                )
            job["state"] = "uploading"
            self._write(job, "Waiting for the platform to accept the upload.")
            try:
                if self.platform == "instagram":
                    return self._instagram_upload(job, path, record)
                return self._tiktok_upload(job, path, record)
            except (MetaError, tt.TikTokError) as exc:
                if not exc.uncertain and not job.get("video_id"):
                    job["state"] = "failed"
                    return self._write(job, str(exc))
                return self._interrupted(job)
            except (ValueError, OSError, requests.RequestException):
                return self._interrupted(job)

    def _interrupted(self, job):
        if self.platform == "tiktok" and job.get("upload_url"):
            job["state"] = "paused"
        else:
            job["state"] = "unknown"
        return self._write(
            job,
            "Upload or publication was interrupted. Refresh the existing delivery before taking action.",
        )

    def refresh(self, jid):
        with self.lease(jid):
            job = self._get(jid)
            if job.get("video_id") and job["state"] in {
                "processing",
                "paused",
                "unknown",
                "inbox",
            }:
                record = self._check(job)
                if self.platform == "instagram":
                    return self._instagram_status(job, self._instagram_graph(record))
                self._tiktok_status(job, record)
            return self.get(jid)

    def resume(self, jid, reviewed=False):
        if reviewed is not True:
            raise ValueError("Confirm that you want to resume the reviewed delivery.")
        with self.lease(jid):
            job = self._get(jid)
            if job["state"] == "blocked" and not job.get("video_id"):
                job["state"] = "queued"
                self._write(job)
            elif (
                self.platform == "tiktok"
                and job["state"] == "paused"
                and job.get("upload_url")
            ):
                record = self._check(job)
                status = self._tiktok_status(job, record)
                if job["state"] != "paused":
                    return self.get(jid)
                offset = status.get("uploaded_bytes")
                if (
                    status.get("status") != "PROCESSING_UPLOAD"
                    or type(offset) is not int
                    or not 0 <= offset <= job["size"]
                    or time.time() >= job["upload_expires"]
                ):
                    raise ValueError(
                        "TikTok could not confirm a usable upload offset for this delivery."
                    )
                if offset == job["size"]:
                    job["state"] = "processing"
                    job.pop("upload_url", None)
                    return self._write(
                        job, "TikTok confirmed receipt of the full video."
                    )
                if (
                    offset % _CHUNK_SIZE
                    or offset // _CHUNK_SIZE >= job["size"] // _CHUNK_SIZE
                    and offset
                ):
                    raise ValueError(
                        "TikTok reported an unexpected chunk boundary. Refresh before continuing."
                    )
                job.update(offset=offset, state="uploading")
                self._write(job)
                try:
                    return self._tiktok_upload(
                        job, media.snapshot_file(job), record, replay=True
                    )
                except (ValueError, OSError, requests.RequestException):
                    return self._interrupted(job)
            else:
                raise ValueError(
                    "This delivery cannot be replayed. Refresh its existing status."
                )
        enqueue(self, jid)
        return self.get(jid)

    def recover(self):
        for job in self.jobs():
            if job["state"] == "queued" or (
                self.platform == "instagram" and job["state"] == "processing"
            ):
                enqueue(self, job["id"])
            elif job["state"] == "uploading":
                try:
                    with self.lease(job["id"]):
                        current = self._get(job["id"])
                        if current["state"] == "uploading":
                            self._interrupted(current)
                except ValueError:
                    continue

    def assert_disconnectable(self, ids):
        if ids and any(
            j["connection_id"] in ids and j["state"] in self.ACTIVE for j in self.jobs()
        ):
            raise ValueError(
                "Resolve the account's active short-video deliveries before disconnecting."
            )

    def remove_history(self, ids):
        if ids:
            for job in self.jobs():
                if job["connection_id"] in ids:
                    with self.lease(job["id"]):
                        self._path(job["id"]).unlink(missing_ok=True)


instagram = ShortVideoDeliveries("instagram")
tiktok = ShortVideoDeliveries("tiktok")


def _work():
    while True:
        try:
            service, jid = _QUEUE.get(timeout=20)
        except Empty:
            pass
        else:
            try:
                service.dispatch(jid)
            except (ValueError, OSError):
                pass
            finally:
                with _LOCK:
                    _BUSY.discard((service, jid))
                _QUEUE.task_done()
        try:
            for studio in (instagram, tiktok):
                for item in studio.jobs():
                    age = (
                        time.time()
                        - datetime.fromisoformat(item["updated_at"]).timestamp()
                    )
                    if item["state"] == "queued" or (
                        studio is instagram
                        and item["state"] == "processing"
                        and age >= 20
                    ):
                        enqueue(studio, item["id"])
        except (ValueError, OSError):
            continue


def enqueue(service, jid):
    global _STARTED
    with _LOCK:
        if (service, jid) in _BUSY:
            return
        if not _STARTED:
            threading.Thread(
                target=_work, name="short-video-delivery", daemon=True
            ).start()
            _STARTED = True
        try:
            _QUEUE.put_nowait((service, jid))
            _BUSY.add((service, jid))
        except Full:
            pass
