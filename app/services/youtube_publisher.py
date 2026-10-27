"""YouTube-only adapter over the existing Upload-Post provider.

OAuth credentials stay with Upload-Post. Only explicit account actions and
approved delivery jobs call this adapter; render/generation paths are unchanged.
"""

from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import quote, urlsplit

import requests

from app.config import config
from app.services.upload_post import UploadPostService


class ProviderError(ValueError):
    def __init__(self, status=None, *, uncertain=False):
        self.status = status
        self.uncertain = uncertain
        message = {
            0: "Upload-Post is disabled or its API key is missing.",
            400: "Upload-Post rejected the request. Check the post settings.",
            401: "Upload-Post API key is invalid or expired.",
            403: "Upload-Post denied this action. Check your plan and account permissions.",
            404: "The provider record is unavailable.",
            409: "The provider cannot perform this action in its current state.",
            429: "Upload-Post rate limit reached. Try refreshing later.",
        }.get(
            status,
            "Upload-Post could not confirm the result. Refresh delivery status before retrying.",
        )
        super().__init__(message)


class YouTubePublisher:
    BASE = UploadPostService.API_BASE

    def __init__(self, key=None):
        self._key = key

    @property
    def api_key(self):
        if self._key is not None:
            return self._key
        return os.environ.get("UPLOAD_POST_API_KEY") or config.app.get(
            "upload_post_api_key", ""
        )

    @property
    def configured(self):
        return bool(self.api_key and config.app.get("upload_post_enabled", False))

    @property
    def credential_id(self):
        return hashlib.sha256(self.api_key.encode()).hexdigest()

    def request(self, method, path, **kwargs):
        if not self.configured:
            raise ProviderError(0)
        headers = {
            "Authorization": "Apikey " + self.api_key,
            **kwargs.pop("headers", {}),
        }
        try:
            response = requests.request(
                method,
                self.BASE + path,
                headers=headers,
                timeout=kwargs.pop("timeout", (10, 45)),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ProviderError(uncertain=method != "GET") from exc
        if not 200 <= response.status_code < 300:
            raise ProviderError(
                response.status_code,
                uncertain=response.status_code >= 500
                or response.status_code in {408, 429},
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(uncertain=method != "GET") from exc
        if not isinstance(data, dict) or data.get("success") is False:
            raise ProviderError(uncertain=method != "GET")
        return data

    @staticmethod
    def profile_name(value):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9_@-]{1,128}", value
        ):
            raise ValueError(
                "Profile identifier must use letters, numbers, _, @ or - (up to 128 characters)."
            )
        return value

    @staticmethod
    def channel(profile):
        account = (profile.get("social_accounts") or {}).get("youtube") or {}
        if not isinstance(account, dict):
            account = {}
        account_id = account.get("username")
        # A display name alone is never sufficient to bind a publishing target.
        return {
            "profile": profile.get("username", ""),
            "profile_label": profile.get("display_name") or profile.get("username", ""),
            "channel_id": str(account_id or ""),
            "handle": str(account.get("handle") or ""),
            "name": str(
                account.get("display_name") or account.get("handle") or account_id or ""
            ),
            "connected": bool(account_id),
            "reauth_required": bool(
                account.get("reauth_required") or profile.get("reauth_required")
            ),
        }

    def profiles(self):
        data = self.request("GET", "/api/uploadposts/users")
        records = data.get("profiles")
        if not isinstance(records, list):
            raise ProviderError()
        return [self.channel(p) for p in records if isinstance(p, dict)]

    def get_channel(self, profile):
        name = self.profile_name(profile)
        data = self.request("GET", "/api/uploadposts/users/" + quote(name, safe=""))
        record = data.get("profile")
        if not isinstance(record, dict) or record.get("username") != name:
            raise ProviderError()
        return self.channel(record)

    def create_profile(self, name, label):
        self.profile_name(name)
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > 100
            or "\n" in label
        ):
            raise ValueError("Enter a profile label of up to 100 characters.")
        self.request(
            "POST",
            "/api/uploadposts/users",
            json={"username": name, "display_name": label.strip()},
        )

    def connect_url(self, profile):
        data = self.request(
            "POST",
            "/api/uploadposts/users/generate-jwt",
            json={
                "username": self.profile_name(profile),
                "platforms": ["youtube"],
                "show_calendar": False,
                "connect_title": "Connect your YouTube channel",
            },
        )
        url = data.get("access_url", "")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "app.upload-post.com"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise ProviderError()
        return url

    def disconnect(self, profile):
        self.request(
            "DELETE",
            "/api/uploadposts/users/social",
            json={
                "profile_username": self.profile_name(profile),
                "social_platform": "youtube",
            },
        )

    def upload(self, job, path):
        options = job["options"]
        data = [
            ("user", job["channel"]["profile"]),
            ("platform[]", "youtube"),
            ("title", options["title"]),
            ("youtube_title", options["title"]),
            ("youtube_description", options["description"]),
            ("privacyStatus", options["privacy"]),
            ("selfDeclaredMadeForKids", str(options["made_for_kids"]).lower()),
            ("containsSyntheticMedia", str(options["synthetic"]).lower()),
            ("hasPaidProductPlacement", str(options["paid_placement"]).lower()),
            ("async_upload", "true"),
            ("request_id", job["request_id"]),
            ("external_id", job["id"]),
        ]
        data.extend(("tags[]", tag) for tag in options["tags"])
        if options["scheduled_at"]:
            data.extend(
                [("scheduled_date", options["scheduled_at"]), ("timezone", "UTC")]
            )
        with path.open("rb") as stream:
            return self.request(
                "POST",
                "/api/upload",
                data=data,
                files={"video": (path.name, stream, job["mime"])},
                headers={
                    "Idempotency-Key": job["id"],
                    "X-Request-Id": job["request_id"],
                },
                timeout=(10, 300),
            )

    def status(self, job):
        key = "job_id" if job.get("provider_job_id") else "request_id"
        try:
            return self.request(
                "GET",
                "/api/uploadposts/status",
                params={key: job.get("provider_job_id") or job["request_id"]},
            )
        except ProviderError as exc:
            if exc.status != 404:
                raise
            # Status records can expire. Reconcile by immutable external ID and
            # profile, never by title, before considering a delivery unconfirmed.
            history = self.request(
                "GET",
                "/api/uploadposts/history",
                params={
                    "external_id": job["id"],
                    "profile_username": job["channel"]["profile"],
                    "platform": "youtube",
                    "limit": 10,
                },
            )
            for row in history.get("history", []):
                if (
                    isinstance(row, dict)
                    and row.get("external_id") == job["id"]
                    and row.get("profile_username") == job["channel"]["profile"]
                    and row.get("platform") == "youtube"
                    and type(row.get("success")) is bool
                ):
                    return {
                        "status": "completed" if row["success"] else "failed",
                        "results": [row],
                    }
            raise exc

    def cancel(self, job):
        return self.request(
            "DELETE",
            "/api/uploadposts/schedule/" + quote(job["provider_job_id"], safe=""),
        )

    def retry(self, job):
        key = "job_id" if job.get("provider_job_id") else "request_id"
        return self.request(
            "POST",
            "/api/uploadposts/posts/retry",
            json={key: job.get("provider_job_id") or job["request_id"]},
        )


publisher = YouTubePublisher()
