"""Facebook Page destinations over Upload-Post's hosted account connection."""

from app.services.youtube_publisher import ProviderError, YouTubePublisher


class FacebookPublisher(YouTubePublisher):
    PLATFORM = "facebook"
    BRAND = "Facebook"
    POST_HOSTS = {"facebook.com", "www.facebook.com", "fb.watch", "www.fb.watch"}

    @staticmethod
    def channel(profile):
        account = (profile.get("social_accounts") or {}).get("facebook") or {}
        if not isinstance(account, dict):
            account = {}
        identity = str(account.get("username") or "")
        return {
            "profile": profile.get("username", ""),
            "profile_label": profile.get("display_name") or profile.get("username", ""),
            "channel_id": identity,
            "account_id": identity,
            "handle": str(account.get("handle") or ""),
            "name": str(account.get("display_name") or identity),
            "connected": bool(identity),
            "reauth_required": bool(
                account.get("reauth_required") or profile.get("reauth_required")
            ),
        }

    def pages(self, profile):
        data = self.request(
            "GET",
            "/api/uploadposts/users/facebook-page",
            params={"profile_username": self.profile_name(profile)},
        )
        rows = data.get("pages")
        if not isinstance(rows, list):
            raise ProviderError()
        pages = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = str(row.get("id") or "")
            if identity.isascii() and identity.isdigit() and len(identity) <= 64:
                pages.append(
                    {"id": identity, "name": str(row.get("name") or identity)[:200]}
                )
        pin = data.get("selected_page_id")
        if pin is not None and not isinstance(pin, (str, int)):
            raise ProviderError()
        return {"pages": pages, "selected_page_id": str(pin or "")}

    def profiles(self):
        records = super().profiles()
        for record in records:
            record.update(
                self.pages(record["profile"])
                if record["connected"] and not record["reauth_required"]
                else {"pages": [], "selected_page_id": ""}
            )
        return records

    def get_channel(self, profile, page_id=None):
        account = super().get_channel(profile)
        if page_id is None:
            return account
        destinations = self.pages(profile)
        pin = destinations["selected_page_id"]
        if pin and pin != page_id:
            raise ValueError(
                "The provider profile is pinned to another Facebook Page. Select that Page or use a separate profile; no upload was sent."
            )
        page = next((p for p in destinations["pages"] if p["id"] == page_id), None)
        if not page:
            raise ValueError(
                "The selected Facebook Page is no longer available. Reconnect and prepare a new post."
            )
        return {
            **account,
            "channel_id": page_id,
            "name": page["name"],
            "selected_page_id": pin,
        }

    def upload_fields(self, job):
        settings = job["options"]
        data = [
            ("user", job["channel"]["profile"]),
            ("platform[]", "facebook"),
            ("title", settings["title"]),
            ("facebook_title", settings["title"]),
            ("facebook_description", settings["description"]),
            ("facebook_page_id", job["channel"]["channel_id"]),
            ("facebook_media_type", settings["media_type"]),
            ("video_state", "PUBLISHED"),
            ("async_upload", "true"),
            ("request_id", job["request_id"]),
            ("external_id", job["id"]),
        ]
        if settings["media_type"] == "REELS":
            data.append(
                ("facebook_is_ai_generated", str(settings["synthetic"]).lower())
            )
        if settings["scheduled_at"]:
            data.extend(
                [("scheduled_date", settings["scheduled_at"]), ("timezone", "UTC")]
            )
        return data


publisher = FacebookPublisher()
