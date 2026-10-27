"""Direct Google OAuth, browser-bound grants and encrypted local credentials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock
from google_auth_oauthlib.flow import Flow

from app.utils import utils

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CALLBACK = "/social/youtube/oauth/callback"


def directory():
    target = Path(utils.storage_dir("social/youtube", create=True))
    if target.is_symlink():
        raise ValueError("Invalid social credential directory.")
    return target


def _cipher():
    key = os.environ.get("MPT_SOCIAL_ENCRYPTION_KEY")
    if not key:
        path = directory() / "encryption.key"
        if path.is_symlink():
            raise ValueError("Invalid social encryption key file.")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        key = path.read_bytes()
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Invalid social encryption key. Restore the original key."
        ) from exc


def read_secret(path, default=None):
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Invalid encrypted social record.")
    try:
        return json.loads(_cipher().decrypt(path.read_bytes()))
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            "Social records could not be unlocked. Restore the original encryption key."
        ) from exc


def write_secret(path, data):
    temporary = path.with_name("." + secrets.token_hex(16))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_cipher().encrypt(json.dumps(data).encode()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def vault():
    return read_secret(
        directory() / "accounts.enc", {"connections": {}, "flows": {}, "settings": {}}
    )


def save_vault(data):
    write_secret(directory() / "accounts.enc", data)


def lock():
    return FileLock(directory() / "accounts.lock")


def settings():
    saved = vault()["settings"]
    return {
        "client_id": os.environ.get("MPT_YOUTUBE_CLIENT_ID")
        or saved.get("client_id", ""),
        "client_secret": os.environ.get("MPT_YOUTUBE_CLIENT_SECRET")
        or saved.get("client_secret", ""),
        "redirect_uri": os.environ.get("MPT_YOUTUBE_REDIRECT_URI")
        or saved.get("redirect_uri", ""),
    }


def validate_settings(value):
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+\.apps\.googleusercontent\.com", value.get("client_id", "")
    ) or not value.get("client_secret"):
        raise ValueError("Enter a Google Web application client ID and client secret.")
    url = urlsplit(value.get("redirect_uri", ""))
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != CALLBACK
        or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"})
    ):
        raise ValueError(
            "Use an HTTPS callback URL ending in /social/youtube/oauth/callback (HTTP is allowed only on localhost)."
        )
    try:
        url.port
    except ValueError as exc:
        raise ValueError("Invalid callback port.") from exc
    return value


def fingerprint(value=None):
    value = value or settings()
    return hashlib.sha256(
        (value["client_id"] + "\0" + value["client_secret"]).encode()
    ).hexdigest()


def configured():
    try:
        validate_settings(settings())
        return True
    except ValueError:
        return False


def configure(client_id, client_secret, redirect_uri):
    value = validate_settings(
        {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "redirect_uri": redirect_uri.strip(),
        }
    )
    for field, env_name in (
        ("client_id", "MPT_YOUTUBE_CLIENT_ID"),
        ("client_secret", "MPT_YOUTUBE_CLIENT_SECRET"),
        ("redirect_uri", "MPT_YOUTUBE_REDIRECT_URI"),
    ):
        if os.environ.get(env_name) and value[field] != os.environ[env_name]:
            raise ValueError(
                "Google settings are supplied by the server environment. Update that environment value instead."
            )
    with lock():
        data = vault()
        if data["connections"] and fingerprint(value) != fingerprint():
            raise ValueError(
                "Disconnect existing channels before changing the Google client credentials."
            )
        data["settings"] = value
        data["epoch"] = data.get("epoch", 0) + 1
        data["flows"] = {}
        save_vault(data)


def _flow(value, state=None, verifier=None):
    return Flow.from_client_config(
        {
            "web": {
                "client_id": value["client_id"],
                "client_secret": value["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [value["redirect_uri"]],
            }
        },
        scopes=SCOPES,
        state=state,
        redirect_uri=value["redirect_uri"],
        code_verifier=verifier,
        autogenerate_code_verifier=not bool(verifier),
    )


def connect_ticket():
    value = validate_settings(settings())
    ticket = secrets.token_urlsafe(32)
    with lock():
        data = vault()
        data["flows"] = {
            k: v for k, v in data["flows"].items() if v["expires"] > time.time()
        }
        if len(data["flows"]) >= 32:
            raise ValueError(
                "Too many pending connections. Wait ten minutes before trying again."
            )
        data["flows"][hashlib.sha256(ticket.encode()).hexdigest()] = {
            "expires": time.time() + 600,
            "kind": "ticket",
            "app": fingerprint(value),
        }
        save_vault(data)
    origin = value["redirect_uri"].removesuffix(CALLBACK)
    return origin + "/social/youtube/oauth/start?ticket=" + ticket


def begin(ticket):
    if not isinstance(ticket, str) or len(ticket) > 128:
        raise ValueError("Invalid connection request.")
    value = validate_settings(settings())
    with lock():
        data = vault()
        record = data["flows"].pop(hashlib.sha256(ticket.encode()).hexdigest(), None)
        if (
            not record
            or record["kind"] != "ticket"
            or record["expires"] < time.time()
            or record["app"] != fingerprint(value)
        ):
            raise ValueError("Connection request expired. Click Connect YouTube again.")
        flow = _flow(value)
        url, state = flow.authorization_url(
            access_type="offline", prompt="consent select_account"
        )
        browser = secrets.token_urlsafe(32)
        key = hashlib.sha256(state.encode()).hexdigest()
        data["flows"][key] = {
            "kind": "callback",
            "expires": time.time() + 600,
            "app": fingerprint(value),
            "browser": hashlib.sha256(browser.encode()).hexdigest(),
            "verifier": flow.code_verifier,
            "epoch": data.get("epoch", 0),
        }
        save_vault(data)
    return url, state, browser


def finish(state, browser, code=None, error=None):
    if not state or len(state) > 256 or not browser or len(browser) > 128:
        raise ValueError(
            "Connection could not be verified. Start again from MoneyPrinter."
        )
    value = validate_settings(settings())
    with lock():
        data = vault()
        record = data["flows"].get(hashlib.sha256(state.encode()).hexdigest())
        if (
            not record
            or record["kind"] != "callback"
            or record["expires"] < time.time()
            or record["app"] != fingerprint(value)
            or record.get("epoch", 0) != data.get("epoch", 0)
            or not secrets.compare_digest(
                record["browser"], hashlib.sha256(browser.encode()).hexdigest()
            )
        ):
            raise ValueError(
                "Connection expired or belongs to another browser. Start again."
            )
        del data["flows"][hashlib.sha256(state.encode()).hexdigest()]
        save_vault(data)  # Consume before exchanging; callbacks can never replay.
    if error or not code or len(code) > 4096:
        raise ValueError(
            "Google authorization was declined or incomplete. No channel was connected."
        )
    try:
        flow = _flow(value, state, record["verifier"])
        flow.fetch_token(code=code, timeout=30)
        credentials = flow.credentials
        if not credentials.refresh_token or not set(SCOPES).issubset(
            set(credentials.granted_scopes or credentials.scopes or [])
        ):
            raise ValueError(
                "Required YouTube permission or offline access was not granted."
            )
        from app.services.youtube_google import GoogleYouTube

        channel = GoogleYouTube.with_credentials(credentials).channel()
    except Exception as exc:
        raise ValueError(
            "Google connection could not be completed. Check permissions and try again."
        ) from exc
    with lock():
        data = vault()
        if fingerprint(value) != fingerprint() or record.get("epoch", 0) != data.get(
            "epoch", 0
        ):
            raise ValueError(
                "Google settings changed during authorization. Connect again."
            )
        # Reconnecting the same verified channel never repoints another channel.
        existing = next(
            (
                c
                for c in data["connections"].values()
                if c["channel_id"] == channel["channel_id"]
                and c["app"] == fingerprint(value)
            ),
            None,
        )
        cid = existing["id"] if existing else secrets.token_hex(16)
        data["connections"][cid] = {
            **channel,
            "id": cid,
            "app": fingerprint(value),
            "credentials": json.loads(credentials.to_json()),
            "reauth_required": False,
            "checked_at": time.time(),
        }
        save_vault(data)
    return cid


def connections():
    data = vault()
    app = fingerprint()
    return [
        {k: v for k, v in c.items() if k not in {"credentials", "app"}}
        | {"reauth_required": c.get("reauth_required", False) or c["app"] != app}
        for c in data["connections"].values()
    ]


def credential_record(cid):
    data = vault()
    record = data["connections"].get(cid)
    if not record or record["app"] != fingerprint() or record.get("reauth_required"):
        raise ValueError("Reconnect this YouTube channel before continuing.")
    return record


def update_credentials(cid, credentials=None, reauth=False, channel=None):
    with lock():
        data = vault()
        record = data["connections"].get(cid)
        if not record:
            raise ValueError("This channel was disconnected.")
        if credentials:
            record["credentials"] = json.loads(credentials.to_json())
        if channel:
            if channel["channel_id"] != record["channel_id"]:
                raise ValueError(
                    "YouTube channel identity changed. Connect the intended channel again."
                )
            record.update(channel)
            record["checked_at"] = time.time()
        record["reauth_required"] = reauth
        save_vault(data)


def disconnect(cid):
    from app.services import youtube_direct as studio, youtube_studio as legacy
    import requests

    # Same catalogue lease as approval: a grant cannot be removed between its
    # pending-work check and another process approving a new delivery.
    with FileLock(legacy.root() / "catalog.lock"):
        if any(j["state"] in studio.ACTIVE for j in studio.jobs()):
            raise ValueError(
                "Cancel or finish pending deliveries before disconnecting this channel."
            )
        record = vault()["connections"].get(cid)
        if not record:
            raise ValueError("This channel is already disconnected.")
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": record["credentials"]["refresh_token"]},
                timeout=(10, 30),
                allow_redirects=False,
            )
            if response.status_code not in {200, 400}:
                raise ValueError(
                    "Google revocation is unconfirmed. Try again before removing credentials."
                )
        except requests.RequestException as exc:
            raise ValueError("Google revocation is unconfirmed. Try again.") from exc
        with lock():
            data = vault()
            data["connections"].pop(cid, None)
            data["flows"] = {}
            data["epoch"] = data.get("epoch", 0) + 1
            # Revocation may affect a shared Google grant. Other channels must
            # reconnect instead of continuing with potentially invalid tokens.
            for c in data["connections"].values():
                c["reauth_required"] = True
            save_vault(data)
        # Remove API-derived history on disconnection. Original user-created
        # videos/projects and their frozen local media are not API data.
        for job in studio.jobs():
            if job["connection_id"] == cid:
                with studio.lease(job["id"]):
                    studio._path(job["id"]).unlink(missing_ok=True)


def suggested_callback():
    port = os.environ.get("MPT_PUBLIC_PORT", "8501")
    name = os.environ.get("CODESPACE_NAME", "")
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "")
    if re.fullmatch(r"[A-Za-z0-9-]+", name) and re.fullmatch(r"[A-Za-z0-9.-]+", domain):
        return f"https://{name}-{port}.{domain}" + CALLBACK
    return f"http://127.0.0.1:{port}" + CALLBACK
