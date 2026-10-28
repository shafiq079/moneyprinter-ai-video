"""Direct YouTube API operations with resumable transfers and safe errors."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials

from app.services import youtube_accounts as accounts

BASE = "https://www.googleapis.com/youtube/v3/"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 8 * 1024 * 1024  # Google requires non-final chunks to be multiples of 256 KiB.


class YouTubeError(ValueError):
    def __init__(self, status=None, reason="", uncertain=False):
        self.status, self.reason, self.uncertain = status, reason, uncertain
        message = {
            401: "YouTube authorization expired. Reconnect the channel.",
            403: "YouTube denied the operation. Check channel permissions and API quota.",
            404: "The YouTube video or resumable session is unavailable.",
            429: "YouTube rate limit reached. Retry later.",
        }.get(
            status,
            "YouTube could not confirm this operation. Refresh status before retrying.",
        )
        if reason in {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}:
            message = "YouTube quota or channel upload limit reached. Retry after the limit resets."
        super().__init__(message)


def session_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Invalid YouTube resumable session.")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname not in {"www.googleapis.com", "youtube.googleapis.com"}
        or url.port not in {None, 443}
        or url.username
        or url.password
        or url.fragment
        or url.path != "/upload/youtube/v3/videos"
        or "upload_id=" not in url.query
    ):
        raise ValueError("Invalid YouTube resumable session.")
    return value


def video_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("Invalid YouTube video ID.")
    return value


class _RefreshRequest(Request):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 30
        return super().__call__(*args, **kwargs)


class GoogleYouTube:
    def __init__(self, connection_id=None, credentials=None):
        self.connection_id = connection_id
        self.credentials = credentials

    @classmethod
    def with_credentials(cls, credentials):
        return cls(credentials=credentials)

    def _credentials(self, force=False):
        if self.connection_id:
            record = accounts.credential_record(self.connection_id)
            value = accounts.settings()
            self.credentials = Credentials.from_authorized_user_info(
                record["credentials"]
                | {
                    "client_id": value["client_id"],
                    "client_secret": value["client_secret"],
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        credentials = self.credentials
        if credentials is None:
            raise ValueError("Connect a YouTube channel first.")
        if not credentials.valid or force:
            try:
                credentials.refresh(_RefreshRequest())
            except TransportError as exc:
                raise YouTubeError(uncertain=False) from exc
            except RefreshError as exc:
                if self.connection_id:
                    accounts.update_credentials(self.connection_id, reauth=True)
                raise YouTubeError(401) from exc
            if self.connection_id:
                accounts.update_credentials(self.connection_id, credentials)
        return credentials

    def request(
        self, method, endpoint, *, upload=False, thumbnail=False, raw=False, **kwargs
    ):
        if thumbnail:
            if upload or method != "POST" or endpoint != "thumbnails/set":
                raise ValueError("Invalid YouTube thumbnail upload operation.")
            url = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
        else:
            url = session_url(endpoint) if upload else BASE + endpoint
        credentials = self._credentials()
        try:
            response = requests.request(
                method,
                url,
                headers={
                    "Authorization": "Bearer " + credentials.token,
                    **kwargs.pop("headers", {}),
                },
                timeout=(10, 90 if upload or thumbnail else 30),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise YouTubeError(uncertain=method != "GET") from exc
        # No implicit resend of a write, including after token expiry.
        if response.status_code == 401 and self.connection_id:
            accounts.update_credentials(self.connection_id, reauth=True)
        if not 200 <= response.status_code < 300 and not (
            upload and response.status_code == 308
        ):
            reason = ""
            try:
                reason = response.json()["error"]["errors"][0]["reason"]
            except (ValueError, TypeError, KeyError, IndexError):
                pass
            raise YouTubeError(
                response.status_code,
                reason,
                response.status_code >= 500 or response.status_code in {408, 429},
            )
        if raw:
            return response
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError as exc:
            raise YouTubeError(uncertain=method != "GET") from exc

    def channel(self):
        data = self.request(
            "GET", "channels", params={"part": "snippet,contentDetails", "mine": "true"}
        )
        rows = data.get("items", [])
        if len(rows) != 1 or not re.fullmatch(
            r"UC[A-Za-z0-9_-]{22}", rows[0].get("id", "")
        ):
            raise ValueError(
                "Google did not return one usable channel. Choose the intended channel and connect again."
            )
        row = rows[0]
        return {
            "channel_id": row["id"],
            "name": str(row["snippet"]["title"])[:200],
            "picture": row["snippet"]
            .get("thumbnails", {})
            .get("default", {})
            .get("url", ""),
            "uploads": row["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def verify_channel(self, expected):
        channel = self.channel()
        if channel["channel_id"] != expected:
            raise ValueError("Google returned a different channel. No upload was sent.")
        if self.connection_id:
            accounts.update_credentials(self.connection_id, channel=channel)
        return channel

    @staticmethod
    def metadata(options):
        return {
            "snippet": {
                "title": options["title"],
                "description": options["description"],
                "tags": options["tags"],
                "categoryId": options.get("category", "22"),
            },
            "status": {
                "privacyStatus": options["privacy"],
                "selfDeclaredMadeForKids": options["made_for_kids"],
                "containsSyntheticMedia": options["synthetic"],
            },
            "paidProductPlacementDetails": {
                "hasPaidProductPlacement": options["paid_placement"]
            },
        }

    def initiate(self, job):
        # Create private media first. Public release is a separate, recoverable
        # metadata operation after processing and channel verification.
        metadata = self.metadata(job["options"])
        metadata["status"]["privacyStatus"] = "private"
        credentials = self._credentials()
        try:
            response = requests.post(
                UPLOAD,
                params={
                    "uploadType": "resumable",
                    "part": "snippet,status,paidProductPlacementDetails",
                    "notifySubscribers": "true",
                },
                headers={
                    "Authorization": "Bearer " + credentials.token,
                    "X-Upload-Content-Length": str(job["size"]),
                    "X-Upload-Content-Type": job["mime"],
                },
                json=metadata,
                timeout=(10, 30),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise YouTubeError(uncertain=True) from exc
        if response.status_code not in {200, 201}:
            reason = ""
            try:
                reason = response.json()["error"]["errors"][0]["reason"]
            except (ValueError, TypeError, KeyError, IndexError):
                pass
            raise YouTubeError(
                response.status_code,
                reason,
                uncertain=response.status_code >= 500
                or response.status_code in {408, 429},
            )
        return session_url(response.headers.get("Location"))

    def probe(self, job):
        return self.request(
            "PUT",
            job["upload_uri"],
            upload=True,
            raw=True,
            data=b"",
            headers={"Content-Length": "0", "Content-Range": f"bytes */{job['size']}"},
        )

    def chunk(self, job, path, offset):
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(CHUNK)
        if not data:
            raise ValueError(
                "YouTube upload has no remaining bytes. Refresh its result."
            )
        return self.request(
            "PUT",
            job["upload_uri"],
            upload=True,
            raw=True,
            data=data,
            headers={
                "Content-Type": job["mime"],
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{job['size']}",
            },
        )

    def videos(self, ids):
        if not ids:
            return []
        for value in ids:
            video_id(value)
        return self.request(
            "GET",
            "videos",
            params={
                "part": "snippet,status,processingDetails,paidProductPlacementDetails",
                "id": ",".join(ids),
            },
        ).get("items", [])

    def content(self, page_token=None):
        channel = self.channel()
        params = {
            "part": "contentDetails",
            "playlistId": channel["uploads"],
            "maxResults": 25,
        }
        if page_token:
            params["pageToken"] = page_token
        data = self.request("GET", "playlistItems", params=params)
        ids = [row["contentDetails"]["videoId"] for row in data.get("items", [])]
        return {"items": self.videos(ids), "next": data.get("nextPageToken")}

    def owned_video(self, identity, expected):
        self.verify_channel(expected)
        rows = self.videos([identity])
        if len(rows) != 1 or rows[0].get("snippet", {}).get("channelId") != expected:
            raise ValueError("This video is not available in the selected channel.")
        return rows[0]

    def update(self, identity, snippet=None, status=None):
        body = {"id": video_id(identity)}
        if snippet is not None:
            body["snippet"] = snippet
        if status is not None:
            body["status"] = status
        return self.request(
            "PUT",
            "videos",
            params={"part": ",".join(k for k in body if k != "id")},
            json=body,
        )

    def delete(self, identity):
        return self.request("DELETE", "videos", params={"id": video_id(identity)})
