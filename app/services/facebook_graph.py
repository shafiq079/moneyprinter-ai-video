"""Bounded official Meta Graph/Page video and Reel operations."""

from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import urlsplit

import requests

VIDEO_FIELDS = "id,from,title,description,status,published,scheduled_publish_time,permalink_url,updated_time"


class MetaError(ValueError):
    def __init__(self, status=None, code=None, *, uncertain=False, offsets=None):
        self.status, self.code, self.uncertain, self.offsets = (
            status,
            code,
            uncertain,
            offsets,
        )
        text = "Meta could not confirm the operation. Refresh the existing delivery before retrying."
        if code == 190:
            text = (
                "Facebook authorization expired or was revoked. Reconnect the account."
            )
        elif code in {10, 200, 294}:
            text = "Meta denied this operation. Check Page tasks, app permissions and App Review access."
        elif status == 429 or code in {4, 17, 32, 613}:
            text = "Meta rate limit reached. Wait before refreshing or resuming."
        elif status == 400 and not uncertain:
            text = "Meta rejected the settings or media. Check the selected Page, format and schedule."
        super().__init__(text)


def numeric_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,64}", value):
        raise ValueError("Invalid Facebook object ID.")
    return value


class Graph:
    def __init__(self, token, settings):
        self.token, self.settings = token, settings

    def request(self, method, path, *, video_upload=False, **kwargs):
        if not re.fullmatch(
            r"(?:me|[0-9]{1,64})(?:/(?:accounts|permissions|videos|video_reels))?", path
        ):
            raise ValueError("Invalid Meta API operation.")
        if video_upload and (method != "POST" or not path.endswith("/videos")):
            raise ValueError("Invalid Meta video operation.")
        host = "graph-video.facebook.com" if video_upload else "graph.facebook.com"
        params = dict(kwargs.pop("params", {}))
        params["appsecret_proof"] = hmac.new(
            self.settings["app_secret"].encode(), self.token.encode(), hashlib.sha256
        ).hexdigest()
        try:
            response = requests.request(
                method,
                "https://" + host + "/" + self.settings["version"] + "/" + path,
                headers={"Authorization": "Bearer " + self.token},
                params=params,
                timeout=(10, 120 if kwargs.get("files") else 30),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MetaError(uncertain=method != "GET") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise MetaError(response.status_code, uncertain=method != "GET") from exc
        if not isinstance(data, dict):
            raise MetaError(uncertain=method != "GET")
        error = data.get("error")
        if not 200 <= response.status_code < 300 or error:
            error = error if isinstance(error, dict) else {}
            offsets = (
                error.get("error_data")
                if error.get("error_subcode") == 1363037
                else None
            )
            raise MetaError(
                response.status_code,
                error.get("code"),
                uncertain=response.status_code >= 500
                or bool(error.get("is_transient"))
                or response.status_code == 429,
                offsets=offsets,
            )
        return data

    def pages(self):
        pages = []
        cursor = None
        seen = set()
        for _ in range(10):
            params = {"fields": "id,name,access_token,tasks", "limit": 100}
            if cursor:
                params["after"] = cursor
            data = self.request("GET", "me/accounts", params=params)
            for row in data.get("data", []):
                if not isinstance(row, dict):
                    continue
                identity = numeric_id(str(row.get("id", "")))
                token = row.get("access_token")
                if not isinstance(token, str) or not 1 <= len(token) <= 8192:
                    continue
                tasks = row.get("tasks") if isinstance(row.get("tasks"), list) else []
                publish = bool(
                    set(tasks)
                    & {
                        "CREATE_CONTENT",
                        "MANAGE",
                        "PROFILE_PLUS_CREATE_CONTENT",
                        "PROFILE_PLUS_FULL_CONTROL",
                        "PROFILE_PLUS_FACEBOOK_ACCESS",
                    }
                )
                pages.append(
                    {
                        "page_id": identity,
                        "name": str(row.get("name") or identity)[:200],
                        "token": token,
                        "can_publish": publish,
                    }
                )
            paging = data.get("paging") or {}
            cursor = (
                (paging.get("cursors") or {}).get("after")
                if paging.get("next")
                else None
            )
            if not cursor:
                return pages
            if not isinstance(cursor, str) or len(cursor) > 2048 or cursor in seen:
                raise MetaError()
            seen.add(cursor)
        raise ValueError(
            "More than 1000 Facebook Pages returned. Limit the Pages granted to this app."
        )


class FacebookPage:
    def __init__(self, cid):
        self.cid = cid

    def graph(self):
        from app.services import facebook_accounts as accounts

        record = accounts.credential_record(self.cid)
        return Graph(record["token"], accounts.settings())

    def verify_page(self, expected):
        from app.services import facebook_accounts as accounts

        record = accounts.credential_record(self.cid)
        accounts.refresh_pages(record["grant_id"])
        record = accounts.credential_record(self.cid)
        row = self.graph().request("GET", "me", params={"fields": "id,name"})
        if str(row.get("id")) != expected or record["page_id"] != expected:
            raise ValueError(
                "Meta returned a different Page. No publishing operation was sent."
            )
        return {
            "page_id": expected,
            "name": str(row.get("name") or record["name"])[:200],
        }

    def video(self, identity, expected=None):
        identity = numeric_id(identity)
        data = self.graph().request("GET", identity, params={"fields": VIDEO_FIELDS})
        if str(data.get("id")) != identity:
            raise MetaError()
        if expected is not None and str((data.get("from") or {}).get("id")) != expected:
            raise ValueError(
                "This video does not belong to the selected Facebook Page."
            )
        return data

    def content(self, media_type="VIDEO", after=None):
        from app.services import facebook_accounts as accounts

        record = accounts.credential_record(self.cid)
        self.verify_page(record["page_id"])
        if media_type not in {"VIDEO", "REELS"}:
            raise ValueError("Choose Page video or Reel.")
        params = {"fields": VIDEO_FIELDS, "limit": 25}
        if after:
            if not isinstance(after, str) or len(after) > 2048:
                raise ValueError("Invalid Page content cursor.")
            params["after"] = after
        edge = "/video_reels" if media_type == "REELS" else "/videos"
        data = self.graph().request("GET", record["page_id"] + edge, params=params)
        paging = data.get("paging") or {}
        return {
            "items": data.get("data", []),
            "next": (paging.get("cursors") or {}).get("after")
            if paging.get("next")
            else None,
        }

    def initiate(self, job):
        reel = job["options"]["media_type"] == "REELS"
        data = self.graph().request(
            "POST",
            job["page"]["page_id"] + ("/video_reels" if reel else "/videos"),
            video_upload=not reel,
            data={"upload_phase": "start"}
            if reel
            else {"upload_phase": "start", "file_size": str(job["size"])},
        )
        try:
            numeric_id(str(data.get("video_id", "")))
            if reel:
                data["upload_url"] = self.upload_url(
                    data.get("upload_url"), str(data["video_id"])
                )
            else:
                numeric_id(str(data.get("upload_session_id", "")))
        except (ValueError, TypeError) as exc:
            # A successful but malformed start response can still have created a
            # remote resource. Do not treat it as permission to start another.
            raise MetaError(uncertain=True) from exc
        return data

    @staticmethod
    def upload_url(value, identity):
        from app.services import facebook_accounts as accounts

        try:
            url = urlsplit(value or "")
            valid = (
                url.scheme == "https"
                and url.hostname == "rupload.facebook.com"
                and url.port in {None, 443}
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and url.path
                == "/video-upload/"
                + accounts.settings()["version"]
                + "/"
                + numeric_id(identity)
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("Meta returned an invalid upload endpoint.")
        return value

    def transfer(self, job, path):
        if job["options"]["media_type"] == "REELS":
            graph = self.graph()
            with path.open("rb") as stream:
                try:
                    response = requests.post(
                        self.upload_url(job["upload_url"], job["video_id"]),
                        headers={
                            "Authorization": "OAuth " + graph.token,
                            "offset": "0",
                            "file_size": str(job["size"]),
                            "Content-Type": "application/octet-stream",
                        },
                        data=stream,
                        timeout=(10, 300),
                        allow_redirects=False,
                    )
                except requests.RequestException as exc:
                    raise MetaError(uncertain=True) from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise MetaError(uncertain=True) from exc
            if (
                not 200 <= response.status_code < 300
                or not isinstance(data, dict)
                or data.get("success") is not True
            ):
                raise MetaError(response.status_code, uncertain=True)
            return {"complete": True}
        start, end = job["offset"], job["end_offset"]
        if not 0 <= start < end <= job["size"] or end - start > 32 * 1024 * 1024:
            raise ValueError("Meta returned an invalid or oversized video chunk range.")
        with path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(end - start)
        return self.graph().request(
            "POST",
            job["page"]["page_id"] + "/videos",
            video_upload=True,
            data={
                "upload_phase": "transfer",
                "upload_session_id": job["upload_session_id"],
                "start_offset": str(start),
            },
            files={"video_file_chunk": ("chunk.mp4", data, "application/octet-stream")},
        )

    def finish(self, job):
        settings = job["options"]
        data = {
            "upload_phase": "finish",
            "title": settings["title"],
            "description": settings["description"],
        }
        when = settings["scheduled_at"]
        if settings["media_type"] == "REELS":
            data.update(
                video_id=job["video_id"],
                video_state="SCHEDULED" if when else "PUBLISHED",
                is_ai_generated=str(settings["synthetic"]).lower(),
            )
            edge = "/video_reels"
        else:
            data.update(
                upload_session_id=job["upload_session_id"],
                published="false" if when else "true",
            )
            if when:
                data["unpublished_content_type"] = "SCHEDULED"
            edge = "/videos"
        if when:
            data["scheduled_publish_time"] = str(int(when))
        result = self.graph().request(
            "POST",
            job["page"]["page_id"] + edge,
            video_upload=settings["media_type"] == "VIDEO",
            data=data,
        )
        if result.get("success") is not True:
            raise MetaError(uncertain=True)
        return result

    def update(self, identity, **fields):
        result = self.graph().request("POST", numeric_id(identity), data=fields)
        if result.get("success") is not True:
            raise MetaError(uncertain=True)
        return result

    def delete(self, identity):
        result = self.graph().request("DELETE", numeric_id(identity))
        if result.get("success") is not True:
            raise MetaError(uncertain=True)
        return result
