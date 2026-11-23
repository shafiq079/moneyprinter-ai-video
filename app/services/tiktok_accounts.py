"""Direct TikTok Login Kit grants for the reviewed inbox-upload workflow."""

import hashlib
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests
from filelock import FileLock

from app.services import youtube_accounts as crypto, youtube_studio as media
from app.utils import utils

CALLBACK = "/social/tiktok/oauth/callback"
SCOPES = {"user.info.basic", "video.upload"}
API = "https://open.tiktokapis.com"
FIELDS = {
    "client_key": "CLIENT_KEY",
    "client_secret": "CLIENT_SECRET",
    "redirect_uri": "REDIRECT_URI",
}


def directory():
    path = Path(utils.storage_dir("social/tiktok", create=True))
    if path.is_symlink():
        raise ValueError("Invalid TikTok storage directory.")
    return path


def lock():
    return FileLock(directory() / "accounts.lock")


def _read():
    return crypto.read_secret(
        directory() / "accounts.enc",
        {
            "settings": {},
            "flows": {},
            "connections": {},
            "epoch": 0,
        },
    )


def _write(data):
    crypto.write_secret(directory() / "accounts.enc", data)


def settings():
    saved = _read()["settings"]
    return {
        key: os.environ.get("MPT_TIKTOK_" + suffix) or saved.get(key, "")
        for key, suffix in FIELDS.items()
    }


def suggested_callback():
    url = crypto.suggested_callback().removesuffix(crypto.CALLBACK) + CALLBACK
    return url if url.startswith("https://") else ""


def _validate(value):
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value["client_key"])
        or not value["client_secret"]
    ):
        raise ValueError("Enter the TikTok Web application client key and secret.")
    url = urlsplit(value["redirect_uri"])
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != CALLBACK
        or url.port == 0
    ):
        raise ValueError("Register an HTTPS TikTok redirect URL ending in " + CALLBACK)
    return value


def configured():
    try:
        _validate(settings())
    except ValueError:
        return False
    return True


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _app(value):
    return _digest(value["client_key"] + "\0" + value["client_secret"])


def configure(client_key, client_secret, redirect_uri):
    value = _validate(
        dict(
            client_key=client_key.strip(),
            client_secret=client_secret.strip(),
            redirect_uri=redirect_uri.strip(),
        )
    )
    for key, suffix in FIELDS.items():
        env = os.environ.get("MPT_TIKTOK_" + suffix)
        if env and value[key] != env:
            raise ValueError(
                "Update the TikTok setting supplied by the server environment."
            )
    with lock():
        data = _read()
        if data["connections"] and _app(value) != _app(settings()):
            raise ValueError(
                "Disconnect TikTok accounts before changing the client key or secret."
            )
        data.update(settings=value, epoch=data["epoch"] + 1, flows={})
        _write(data)


def connect_ticket():
    value = _validate(settings())
    ticket = secrets.token_urlsafe(32)
    with lock():
        data = _read()
        data["flows"] = {
            k: v for k, v in data["flows"].items() if v["expires"] > time.time()
        }
        if len(data["flows"]) >= 32:
            raise ValueError("Too many pending TikTok connections. Wait ten minutes.")
        data["flows"][_digest(ticket)] = dict(
            kind="ticket", expires=time.time() + 600, settings=value_id(value)
        )
        _write(data)
    return (
        value["redirect_uri"].removesuffix(CALLBACK)
        + "/social/tiktok/oauth/start?ticket="
        + ticket
    )


def value_id(value):
    return _digest(_app(value) + "\0" + value["redirect_uri"])


def _flow(data, value, token, kind):
    record = data["flows"].get(_digest(token))
    if (
        not record
        or record["kind"] != kind
        or record["expires"] <= time.time()
        or record["settings"] != value_id(value)
    ):
        raise ValueError("TikTok connection expired. Start again from MoneyPrinter.")
    return record


def begin(ticket):
    if not ticket or len(ticket) > 128:
        raise ValueError("Invalid TikTok connection request.")
    value = _validate(settings())
    with lock():
        data = _read()
        _flow(data, value, ticket, "ticket")
        del data["flows"][_digest(ticket)]
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data["flows"][_digest(state)] = dict(
            kind="callback",
            browser=_digest(browser),
            settings=value_id(value),
            epoch=data["epoch"],
            expires=time.time() + 600,
        )
        _write(data)
    params = dict(
        client_key=value["client_key"],
        scope=",".join(sorted(SCOPES)),
        redirect_uri=value["redirect_uri"],
        state=state,
        response_type="code",
    )
    return (
        "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params),
        state,
        browser,
    )


class TikTokError(ValueError):
    def __init__(self, message, *, uncertain=False, auth=False):
        super().__init__(message)
        self.uncertain, self.auth = uncertain, auth


def request(method, path, *, token=None, **kwargs):
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        response = requests.request(
            method,
            API + path,
            headers=headers,
            timeout=(10, 30),
            allow_redirects=False,
            **kwargs,
        )
        if (
            path == "/v2/oauth/revoke/"
            and 200 <= response.status_code < 300
            and not response.content
        ):
            return {}
        result = response.json()
    except (requests.RequestException, ValueError):
        raise TikTokError(
            "TikTok did not confirm the request. Check the connection and refresh the existing delivery.",
            uncertain=True,
        ) from None
    if not isinstance(result, dict):
        raise TikTokError("TikTok returned an unexpected response.", uncertain=True)
    error = result.get("error") or {}
    code = error.get("code") if isinstance(error, dict) else error
    if not 200 <= response.status_code < 300 or code not in (None, "ok"):
        auth = response.status_code == 401 or code in {
            "access_token_invalid",
            "scope_not_authorized",
            "invalid_grant",
            "refresh_token_invalid",
        }
        message = (
            "Reconnect TikTok and grant profile and video upload access."
            if auth
            else "TikTok declined the request. Check the application access, media and account limits."
        )
        raise TikTokError(message, auth=auth, uncertain=response.status_code >= 500)
    return result


def _exchange(value, **params):
    data = request(
        "POST",
        "/v2/oauth/token/",
        data={
            "client_key": value["client_key"],
            "client_secret": value["client_secret"],
            **params,
        },
    )
    try:
        identity, access, refresh = (
            data[k] for k in ("open_id", "access_token", "refresh_token")
        )
        expires, refresh_expires = (
            int(data["expires_in"]),
            int(data["refresh_expires_in"]),
        )
        scopes = set(data["scope"].split(","))
        if (
            not all(
                isinstance(v, str) and 0 < len(v) <= 8192
                for v in (identity, access, refresh)
            )
            or not SCOPES <= scopes
            or min(expires, refresh_expires) <= 0
        ):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError(
            "TikTok did not grant both profile access and video upload access."
        ) from None
    return dict(
        identity=identity,
        token=access,
        refresh=refresh,
        expires=time.time() + expires,
        refresh_expires=time.time() + refresh_expires,
        app=_app(value),
        reauth_required=False,
    )


def finish(state, browser, code=None, error=None):
    if not state or not browser or max(len(state), len(browser)) > 128:
        raise ValueError("TikTok connection could not be verified.")
    value = _validate(settings())
    with lock():
        data = _read()
        record = _flow(data, value, state, "callback")
        if not secrets.compare_digest(record["browser"], _digest(browser)):
            raise ValueError("TikTok connection belongs to another browser.")
        del data["flows"][_digest(state)]
        _write(data)
    if error or not code or len(code) > 4096:
        raise ValueError("TikTok authorization was declined or incomplete.")
    grant = _exchange(
        value,
        grant_type="authorization_code",
        code=code,
        redirect_uri=value["redirect_uri"],
    )
    user = (
        request(
            "GET",
            "/v2/user/info/",
            token=grant["token"],
            params={"fields": "open_id,display_name"},
        )
        .get("data", {})
        .get("user", {})
    )
    if user.get("open_id") != grant["identity"] or not user.get("display_name"):
        raise ValueError("Could not verify the connected TikTok account.")
    cid = _digest(grant["identity"] + "\0" + grant["app"])[:32]
    with lock():
        data = _read()
        if (
            data["epoch"] != record["epoch"]
            or value_id(settings()) != record["settings"]
        ):
            raise ValueError("TikTok app settings changed. Connect again.")
        data["connections"][cid] = grant | {
            "id": cid,
            "name": str(user["display_name"])[:200],
        }
        _write(data)
    return cid


def _unavailable(record, value):
    return (
        not record
        or record.get("reauth_required")
        or record["app"] != _app(value)
        or record["refresh_expires"] <= time.time()
    )


def connections():
    value = settings()
    return [
        {key: record[key] for key in ("id", "name", "identity")}
        | {"reauth_required": _unavailable(record, value)}
        for record in _read()["connections"].values()
    ]


def credentials(cid):
    value = _validate(settings())
    with lock():
        data = _read()
        record = data["connections"].get(cid)
        if _unavailable(record, value):
            raise ValueError("Reconnect the intended TikTok account first.")
        if record["expires"] <= time.time() + 60:
            try:
                renewed = _exchange(
                    value, grant_type="refresh_token", refresh_token=record["refresh"]
                )
            except TikTokError as exc:
                if exc.auth:
                    record["reauth_required"] = True
                    _write(data)
                raise
            if renewed["identity"] != record["identity"]:
                raise ValueError(
                    "TikTok returned a different account. Reconnect before uploading."
                )
            record.update(renewed)
            _write(data)
        return record


def disconnect(cid):
    from app.services import short_video_direct

    with FileLock(media.root() / "catalog.lock"):
        studio = short_video_direct.tiktok
        studio.assert_disconnectable({cid})
        with lock():
            value = _validate(settings())
            data = _read()
            record = data["connections"].get(cid)
            if not record:
                raise ValueError("TikTok account is already disconnected.")
            request(
                "POST",
                "/v2/oauth/revoke/",
                data={
                    "client_key": value["client_key"],
                    "client_secret": value["client_secret"],
                    "token": record["token"],
                },
            )
            del data["connections"][cid]
            data.update(flows={}, epoch=data["epoch"] + 1)
            _write(data)
        studio.remove_history({cid})
