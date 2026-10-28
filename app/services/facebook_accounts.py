"""Direct Meta login grants and explicit Page attachment; secrets stay encrypted."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import requests
from filelock import FileLock
from oauthlib.oauth2 import WebApplicationClient

from app.services import youtube_accounts as crypto
from app.services.facebook_graph import Graph, MetaError, numeric_id
from app.utils import utils

CALLBACK = "/social/facebook/oauth/callback"
SCOPES = {"pages_show_list", "pages_read_engagement", "pages_manage_posts"}


def directory():
    from pathlib import Path

    target = Path(utils.storage_dir("social/facebook", create=True))
    if target.is_symlink():
        raise ValueError("Invalid Facebook storage directory.")
    return target


def vault():
    return crypto.read_secret(
        directory() / "accounts.enc",
        {"settings": {}, "grants": {}, "connections": {}, "flows": {}, "epoch": 0},
    )


def save(data):
    crypto.write_secret(directory() / "accounts.enc", data)


def lock():
    return FileLock(directory() / "accounts.lock")


def settings():
    saved = vault()["settings"]
    return {
        key: os.environ.get(env) or saved.get(key, default)
        for key, env, default in (
            ("app_id", "MPT_FACEBOOK_APP_ID", ""),
            ("app_secret", "MPT_FACEBOOK_APP_SECRET", ""),
            ("redirect_uri", "MPT_FACEBOOK_REDIRECT_URI", ""),
            ("version", "MPT_FACEBOOK_GRAPH_VERSION", "v26.0"),
            ("config_id", "MPT_FACEBOOK_LOGIN_CONFIG_ID", ""),
        )
    }


def validate(value):
    numeric_id(value.get("app_id", ""))
    if not value.get("app_secret") or not re.fullmatch(
        r"v[0-9]{2}\.0", value.get("version", "")
    ):
        raise ValueError(
            "Enter the Meta app secret and a supported Graph API version, for example v26.0."
        )
    if value.get("config_id"):
        numeric_id(value["config_id"])
    url = urlsplit(value.get("redirect_uri", ""))
    try:
        valid = (
            url.scheme in {"https", "http"}
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path == CALLBACK
            and url.port != 0
            and (url.scheme == "https" or url.hostname in {"localhost", "127.0.0.1"})
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "Use an HTTPS Facebook callback ending in /social/facebook/oauth/callback. HTTP is only allowed on localhost."
        )
    return value


def fingerprint(value=None):
    value = value or settings()
    return hashlib.sha256(
        (
            value["app_id"] + "\0" + value["app_secret"] + "\0" + value["version"]
        ).encode()
    ).hexdigest()


def configured():
    try:
        validate(settings())
        return True
    except ValueError:
        return False


def configure(value):
    value = validate({k: str(v).strip() for k, v in value.items()})
    for key, env in (
        ("app_id", "MPT_FACEBOOK_APP_ID"),
        ("app_secret", "MPT_FACEBOOK_APP_SECRET"),
        ("redirect_uri", "MPT_FACEBOOK_REDIRECT_URI"),
        ("version", "MPT_FACEBOOK_GRAPH_VERSION"),
        ("config_id", "MPT_FACEBOOK_LOGIN_CONFIG_ID"),
    ):
        if os.environ.get(env) and value.get(key, "") != os.environ[env]:
            raise ValueError(
                "Meta settings are supplied by the server environment. Update that value instead."
            )
    with lock():
        data = vault()
        if data["grants"] and fingerprint(value) != fingerprint():
            raise ValueError(
                "Disconnect Facebook accounts before changing the Meta app credentials or API version."
            )
        data["settings"] = value
        data["epoch"] += 1
        data["flows"] = {}
        save(data)


def suggested_callback():
    return crypto.suggested_callback().removesuffix(crypto.CALLBACK) + CALLBACK


def connect_ticket():
    value = validate(settings())
    ticket = secrets.token_urlsafe(32)
    with lock():
        data = vault()
        data["flows"] = {
            k: v for k, v in data["flows"].items() if v["expires"] > time.time()
        }
        if len(data["flows"]) >= 32:
            raise ValueError("Too many pending Facebook connections. Wait ten minutes.")
        data["flows"][hashlib.sha256(ticket.encode()).hexdigest()] = {
            "kind": "ticket",
            "expires": time.time() + 600,
            "app": fingerprint(value),
        }
        save(data)
    return (
        value["redirect_uri"].removesuffix(CALLBACK)
        + "/social/facebook/oauth/start?ticket="
        + ticket
    )


def begin(ticket):
    if not isinstance(ticket, str) or len(ticket) > 128:
        raise ValueError("Invalid Facebook connection request.")
    value = validate(settings())
    with lock():
        data = vault()
        record = data["flows"].pop(hashlib.sha256(ticket.encode()).hexdigest(), None)
        if (
            not record
            or record["kind"] != "ticket"
            or record["expires"] < time.time()
            or record["app"] != fingerprint(value)
        ):
            raise ValueError(
                "Facebook connection expired. Start again from MoneyPrinter."
            )
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data["flows"][hashlib.sha256(state.encode()).hexdigest()] = {
            "kind": "callback",
            "expires": time.time() + 600,
            "app": fingerprint(value),
            "browser": hashlib.sha256(browser.encode()).hexdigest(),
            "epoch": data["epoch"],
        }
        save(data)
    params = (
        {"config_id": value["config_id"]}
        if value.get("config_id")
        else {"scope": sorted(SCOPES), "auth_type": "rerequest"}
    )
    url = WebApplicationClient(value["app_id"]).prepare_request_uri(
        "https://www.facebook.com/" + value["version"] + "/dialog/oauth",
        redirect_uri=value["redirect_uri"],
        state=state,
        **params,
    )
    return url, state, browser


def _exchange(value, params):
    # Meta's server-side authorization-code and long-lived token exchanges use
    # this fixed endpoint. Never expose its query to app logs or the browser.
    try:
        response = requests.get(
            "https://graph.facebook.com/" + value["version"] + "/oauth/access_token",
            params={
                "client_id": value["app_id"],
                "client_secret": value["app_secret"],
                **params,
            },
            timeout=(10, 30),
            allow_redirects=False,
        )
        result = response.json()
        if (
            not 200 <= response.status_code < 300
            or not isinstance(result, dict)
            or not isinstance(result.get("access_token"), str)
        ):
            raise ValueError()
        return result
    except (requests.RequestException, ValueError) as exc:
        raise ValueError(
            "Meta token exchange failed. Check the app, callback and permissions, then connect again."
        ) from exc


def _permissions(graph):
    result = graph.request("GET", "me/permissions")
    granted = {
        r.get("permission")
        for r in result.get("data", [])
        if isinstance(r, dict) and r.get("status") == "granted"
    }
    if not SCOPES <= granted:
        raise ValueError(
            "Facebook Page permissions were not all granted. Reconnect and approve Page listing, reading and publishing access."
        )


def finish(state, browser, code=None, error=None):
    if not state or len(state) > 256 or not browser or len(browser) > 128:
        raise ValueError("Facebook connection could not be verified.")
    value = validate(settings())
    with lock():
        data = vault()
        record = data["flows"].get(hashlib.sha256(state.encode()).hexdigest())
        if (
            not record
            or record["kind"] != "callback"
            or record["expires"] < time.time()
            or record["epoch"] != data["epoch"]
            or record["app"] != fingerprint(value)
            or not secrets.compare_digest(
                record["browser"], hashlib.sha256(browser.encode()).hexdigest()
            )
        ):
            raise ValueError(
                "Facebook connection expired or belongs to another browser."
            )
        del data["flows"][hashlib.sha256(state.encode()).hexdigest()]
        save(data)
    if error or not code or len(code) > 4096:
        raise ValueError("Facebook authorization was declined or incomplete.")
    token = _exchange(value, {"code": code, "redirect_uri": value["redirect_uri"]})
    token = _exchange(
        value,
        {"grant_type": "fb_exchange_token", "fb_exchange_token": token["access_token"]},
    )
    graph = Graph(token["access_token"], value)
    _permissions(graph)
    user = graph.request("GET", "me", params={"fields": "id"})
    user_id = numeric_id(str(user.get("id", "")))
    pages = graph.pages()
    with lock():
        data = vault()
        if data["epoch"] != record["epoch"] or fingerprint(value) != fingerprint():
            raise ValueError(
                "Meta settings changed during authorization. Connect again."
            )
        gid = hashlib.sha256((user_id + fingerprint(value)).encode()).hexdigest()[:32]
        data["grants"][gid] = {
            "id": gid,
            "user_id": user_id,
            "token": token["access_token"],
            "expires_at": time.time() + int(token.get("expires_in", 3600)),
            "pages": pages,
            "app": fingerprint(value),
            "reauth_required": False,
        }
        _update_connections(data, gid)
        save(data)
    return gid


def _update_connections(data, gid):
    grant = data["grants"][gid]
    for c in data["connections"].values():
        if c["grant_id"] == gid:
            page = next(
                (p for p in grant["pages"] if p["page_id"] == c["page_id"]), None
            )
            c["reauth_required"] = (
                not page
                or not page["can_publish"]
                or grant.get("reauth_required", False)
            )
            if page:
                c["name"] = page["name"]
                c["checked_at"] = time.time()


def refresh_pages(gid):
    data = vault()
    grant = data["grants"].get(gid)
    if (
        not grant
        or grant["app"] != fingerprint()
        or grant.get("reauth_required")
        or grant["expires_at"] <= time.time()
    ):
        raise ValueError("Reconnect this Facebook account before refreshing its Pages.")
    graph = Graph(grant["token"], settings())
    try:
        _permissions(graph)
        pages = graph.pages()
    except MetaError as exc:
        if exc.code == 190:
            with lock():
                data = vault()
                if gid in data["grants"]:
                    data["grants"][gid]["reauth_required"] = True
                    _update_connections(data, gid)
                    save(data)
        raise
    with lock():
        data = vault()
        if gid not in data["grants"] or data["grants"][gid]["token"] != grant["token"]:
            raise ValueError("Facebook account changed during refresh. Try again.")
        data["grants"][gid]["pages"] = pages
        _update_connections(data, gid)
        save(data)
    return pages


def available_pages():
    result = []
    for grant in vault()["grants"].values():
        if (
            grant["app"] == fingerprint()
            and not grant.get("reauth_required")
            and grant["expires_at"] > time.time()
        ):
            result.extend(
                {
                    "grant_id": grant["id"],
                    "page_id": p["page_id"],
                    "name": p["name"],
                    "can_publish": p["can_publish"],
                }
                for p in grant["pages"]
            )
    return result


def attach(gid, page_id):
    pages = refresh_pages(gid)
    page = next(
        (p for p in pages if p["page_id"] == page_id and p["can_publish"]), None
    )
    if not page:
        raise ValueError("This Page is unavailable or lacks content creation tasks.")
    with lock():
        data = vault()
        grant = data["grants"].get(gid)
        if not grant or grant["app"] != fingerprint() or grant.get("reauth_required"):
            raise ValueError(
                "Facebook authorization changed. Refresh available Pages again."
            )
        cid = next(
            (
                c["id"]
                for c in data["connections"].values()
                if c["page_id"] == page_id and c["app"] == fingerprint()
            ),
            secrets.token_hex(16),
        )
        data["connections"][cid] = {
            "id": cid,
            "grant_id": gid,
            "page_id": page_id,
            "name": page["name"],
            "app": fingerprint(),
            "checked_at": time.time(),
            "reauth_required": False,
        }
        save(data)
    return cid


def connections():
    data = vault()
    result = []
    for c in data["connections"].values():
        grant = data["grants"].get(c["grant_id"], {})
        result.append(
            {k: v for k, v in c.items() if k != "app"}
            | {
                "reauth_required": bool(
                    c.get("reauth_required")
                    or grant.get("reauth_required")
                    or grant.get("expires_at", 0) <= time.time()
                    or c["app"] != fingerprint()
                )
            }
        )
    return result


def credential_record(cid):
    data = vault()
    c = data["connections"].get(cid)
    if not c or c.get("reauth_required") or c["app"] != fingerprint():
        raise ValueError("Reconnect and attach the intended Facebook Page.")
    grant = data["grants"].get(c["grant_id"])
    if not grant or grant.get("reauth_required") or grant["expires_at"] <= time.time():
        raise ValueError("Facebook authorization expired. Reconnect the account.")
    page = next(
        (
            p
            for p in grant["pages"]
            if p["page_id"] == c["page_id"] and p["can_publish"]
        ),
        None,
    )
    if not page:
        raise ValueError("Page publishing access is no longer available.")
    return c | {"token": page["token"]}


def disconnect(gid):
    from app.services import facebook_direct as studio, youtube_studio as legacy

    with FileLock(legacy.root() / "catalog.lock"):
        data = vault()
        cids = {c["id"] for c in data["connections"].values() if c["grant_id"] == gid}
        if any(
            j["connection_id"] in cids and j["state"] in studio.ACTIVE
            for j in studio.jobs()
        ):
            raise ValueError(
                "Cancel or finish this Facebook account's pending deliveries before disconnecting."
            )
        grant = data["grants"].get(gid)
        if not grant:
            raise ValueError("Facebook account is already disconnected.")
        revoked = True
        try:
            result = Graph(grant["token"], settings()).request(
                "DELETE", grant["user_id"] + "/permissions"
            )
            if result.get("success") is not True:
                raise MetaError(uncertain=True)
        except MetaError as exc:
            if exc.code != 190:
                raise
            revoked = (
                False  # Expired credentials removed locally; no false revocation claim.
            )
        with lock():
            data = vault()
            data["grants"].pop(gid, None)
            data["connections"] = {
                k: c for k, c in data["connections"].items() if c["grant_id"] != gid
            }
            data["flows"] = {}
            data["epoch"] += 1
            save(data)
        for job in studio.jobs():
            if job["connection_id"] in cids:
                with studio.lease(job["id"]):
                    studio._path(job["id"]).unlink(missing_ok=True)
    return revoked


def grants():
    return [
        {
            "id": g["id"],
            "user_id": g["user_id"],
            "reauth_required": bool(
                g.get("reauth_required")
                or g["expires_at"] <= time.time()
                or g["app"] != fingerprint()
            ),
        }
        for g in vault()["grants"].values()
    ]
