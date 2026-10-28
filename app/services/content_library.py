"""Durable final versions, reviewed batch drafts and account posting slots."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue, Full
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout
from loguru import logger

from app.services import youtube_accounts as crypto, youtube_direct as youtube
from app.services import facebook_accounts, facebook_direct as facebook
from app.services import publishing_seo as seo, youtube_studio as media
from app.utils import utils

UTC = timezone.utc
_queue = Queue(32)
_guard = threading.Lock()
_running = set()
_started = False
_last_poll = {}


def root():
    target = Path(utils.storage_dir("social/library", create=True))
    if target.is_symlink():
        raise ValueError("Invalid content library storage.")
    (target / "batches").mkdir(exist_ok=True)
    if (target / "batches").is_symlink():
        raise ValueError("Invalid publishing batch storage.")
    return target


def lock():
    return FileLock(root() / "catalog.lock")


def catalog():
    return crypto.read_secret(
        root() / "catalog.enc",
        {"finals": {}, "presets": {}, "auto": {}, "auto_prepare": False},
    )


def _save(data):
    crypto.write_secret(root() / "catalog.enc", data)


def _stamp(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def projects():
    groups = {}
    data = catalog()
    for row in media.completed_videos():
        if _processing(row["task_id"]):
            continue
        groups.setdefault(
            row["task_id"],
            {"task_id": row["task_id"], "title": row["title"], "versions": []},
        )["versions"].append(row)
    result = []
    for task_id, project in groups.items():
        versions = project["versions"]
        final = data["finals"].get(task_id)
        default = next(
            (v for v in versions if v["asset"] == "final-1.mp4"),
            next((v for v in versions if v["asset"].startswith("final-")), versions[0]),
        )
        selected = final["source"] if final else default["asset"]
        available = next((v for v in versions if v["asset"] == selected), None)
        ready = bool(
            final
            and final["ready"]
            and available
            and _stamp(media.source_file(task_id, selected)) == final["stamp"]
        )
        result.append(
            project
            | {
                "source": selected,
                "ready": ready,
                "revision": final["revision"] if final else 0,
                "available": bool(available),
                "summary": (final or {}).get("summary", ""),
            }
        )
    return result


def select_final(task_id, relative, reviewed=False, summary=""):
    from app.services import state as sm
    from app.models import const

    if (
        reviewed
        and (sm.state.get_task(task_id) or {}).get("state")
        == const.TASK_STATE_PROCESSING
    ):
        raise ValueError(
            "This video is still processing. Review it after rendering completes."
        )
    if not isinstance(summary, str) or len(summary) > 12000:
        raise ValueError("Use a video summary of at most 12000 characters.")
    summary = summary.strip()
    source = media.source_file(task_id, relative)
    before = _stamp(source)
    digest = media.gm.media_sha256(source)
    if before != _stamp(source):
        raise ValueError("Video changed during review. Wait for rendering to finish.")
    with lock():
        data = catalog()
        previous = data["finals"].get(task_id, {})
        # Saving the same reviewed selection does not invalidate existing batches.
        revision = previous.get("revision", 0) + (
            0
            if previous.get("source") == relative
            and previous.get("sha256") == digest
            and previous.get("ready") is bool(reviewed)
            and previous.get("summary", "") == summary
            else 1
        )
        data["finals"][task_id] = dict(
            source=relative,
            sha256=digest,
            stamp=before,
            ready=reviewed is True,
            revision=revision,
            summary=summary,
        )
        _save(data)
    completed(task_id)
    return data["finals"][task_id]


def _final(task_id, expected=None):
    value = catalog()["finals"].get(task_id)
    if _processing(task_id):
        raise ValueError(
            "This video is still processing. Review it after rendering completes."
        )
    if not value or not value["ready"]:
        raise ValueError("Review and mark the final video ready first.")
    source = media.source_file(task_id, value["source"])
    if (
        _stamp(source) != value["stamp"]
        or media.gm.media_sha256(source) != value["sha256"]
        or (
            expected
            and (
                expected["source"] != value["source"]
                or expected["revision"] != value["revision"]
                or expected["sha256"] != value["sha256"]
            )
        )
    ):
        raise ValueError(
            "Final video changed. Review the new version and prepare another draft."
        )
    return value


def destinations():
    result = []
    for platform, accounts in [("youtube", crypto), ("facebook", facebook_accounts)]:
        for c in accounts.connections():
            if not c.get("reauth_required"):
                result.append(
                    dict(
                        key=platform + ":" + c["id"],
                        platform=platform,
                        connection_id=c["id"],
                        name=c["name"],
                        identity=c.get("channel_id") or c.get("page_id"),
                    )
                )
    return result


def service(platform):
    if platform == "youtube":
        return youtube
    if platform == "facebook":
        return facebook
    raise ValueError("Unsupported publishing platform.")


def save_preset(
    key, timezone_name, times, days, defaults, language="auto", thumbnail=True
):
    target = next((d for d in destinations() if d["key"] == key), None)
    if not target:
        raise ValueError("Reconnect the destination account first.")
    try:
        ZoneInfo(timezone_name)
    except (ValueError, KeyError) as exc:
        raise ValueError("Enter a valid IANA timezone.") from exc
    if (
        not isinstance(times, list)
        or len(times) > 12
        or any(not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t) for t in times)
    ):
        raise ValueError("Use up to twelve posting times in HH:MM format.")
    if (
        not isinstance(days, list)
        or not days
        or any(type(d) is not int or d not in range(7) for d in days)
    ):
        raise ValueError("Choose posting weekdays.")
    if not isinstance(language, str) or not 1 <= len(language.strip()) <= 80:
        raise ValueError("Enter a publishing language or auto.")
    # Validate real declarations before saving reusable account defaults.
    normalized = service(target["platform"]).options(
        defaults
        | {"title": "Preset validation", "description": "", "scheduled_at": None}
    )
    value = target | dict(
        timezone=timezone_name,
        times=sorted(set(times)),
        days=sorted(set(days)),
        defaults=normalized,
        language=language.strip(),
        thumbnail=bool(thumbnail),
    )
    with lock():
        data = catalog()
        data["presets"][key] = value
        _save(data)
    if catalog()["auto_prepare"]:
        discover_automatic()
    return value


def set_automatic(enabled):
    with lock():
        data = catalog()
        data["auto_prepare"] = bool(enabled)
        _save(data)
    if enabled:
        recover()


def _path(bid):
    if not isinstance(bid, str) or not re.fullmatch("[a-f0-9]{32}", bid):
        raise ValueError("Invalid publishing batch.")
    return root() / "batches" / (bid + ".enc")


def batch(bid):
    data = crypto.read_secret(_path(bid))
    if not isinstance(data, dict):
        raise ValueError("Publishing batch is unavailable.")
    return data


def _write(data):
    data["revision"] += 1
    data["updated_at"] = datetime.now(UTC).isoformat()
    crypto.write_secret(_path(data["id"]), data)
    return data


def batches():
    return sorted(
        [batch(p.stem) for p in (root() / "batches").glob("*.enc")],
        key=lambda b: b["created_at"],
        reverse=True,
    )


def _lease(bid):
    return FileLock(str(_path(bid)) + ".lock", timeout=0)


def _when(value):
    if not value:
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Publication times need an explicit timezone.")
    return parsed.astimezone(UTC)


def _occupied(key, records=None):
    platform, cid = key.split(":", 1)
    taken = set()
    for j in service(platform).jobs():
        if j["connection_id"] == cid and j["state"] not in {
            "cancelled",
            "deleted",
            "failed",
        }:
            when = _when(j["options"].get("scheduled_at"))
            if when:
                taken.add(int(when.timestamp()))
    for b in records if records is not None else batches():
        for item in b["items"]:
            if item["destination"]["key"] == key and _reserves(item):
                when = _when(item["options"].get("scheduled_at"))
                if when:
                    taken.add(int(when.timestamp()))
    return taken


def next_slot(preset, taken, now=None):
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(preset["timezone"]))
    for offset in range(8):
        date = (local + timedelta(days=offset)).date()
        if date.weekday() not in preset["days"]:
            continue
        for clock in preset["times"]:
            naive = datetime.combine(date, datetime.strptime(clock, "%H:%M").time())
            try:
                candidate = datetime.fromisoformat(
                    media.scheduled_utc(naive, preset["timezone"])
                )
            except ValueError:
                continue  # Skip DST gaps/folds; never guess the hour.
            stamp = int(candidate.timestamp())
            if (
                now + timedelta(minutes=20) <= candidate <= now + timedelta(days=7)
                and stamp not in taken
            ):
                taken.add(stamp)
                return candidate.isoformat()
    raise ValueError(
        "No available posting slot within seven days. Add posting times or choose an exact time."
    )


def create_batch(task_ids, keys, mode="slots", exact=None, spacing_minutes=60):
    if (
        not task_ids
        or not keys
        or len(set(task_ids)) * len(set(keys)) > 50
        or mode not in {"slots", "exact", "now"}
    ):
        raise ValueError(
            "Choose videos and destinations, with at most fifty posts per batch."
        )
    if type(spacing_minutes) is not int or not 1 <= spacing_minutes <= 1440:
        raise ValueError("Choose a posting interval of 1–1440 minutes.")
    current = {d["key"]: d for d in destinations()}
    with lock():
        data = catalog()
        finals = {tid: _final(tid) for tid in dict.fromkeys(task_ids)}
        previous_batches = batches()
        if len(previous_batches) >= 250:
            raise ValueError("Publishing history reached its 250-batch limit.")
        items = []
        for key in dict.fromkeys(keys):
            preset = data["presets"].get(key)
            if (
                not preset
                or key not in current
                or preset["identity"] != current[key]["identity"]
            ):
                raise ValueError(
                    "Save posting defaults for every selected account first."
                )
            taken = _occupied(key, previous_batches)
            for position, (tid, final) in enumerate(finals.items()):
                # Another unapproved batch must not reserve the same final/account twice.
                if any(
                    i["task_id"] == tid
                    and i["destination"]["key"] == key
                    and i["final"]["sha256"] == final["sha256"]
                    and _reserves(i)
                    for b in previous_batches
                    for i in b["items"]
                ):
                    raise ValueError(
                        "This final video already has a publishing plan for this account. Open that batch instead."
                    )
                if mode == "slots":
                    when = next_slot(preset, taken)
                elif mode == "exact" and exact:
                    when = (
                        _when(exact) + timedelta(minutes=position * spacing_minutes)
                    ).isoformat()
                    if int(_when(when).timestamp()) in taken:
                        raise ValueError(
                            "This account already has a post at the requested time."
                        )
                    taken.add(int(_when(when).timestamp()))
                else:
                    when = None
                if mode == "exact" and not exact:
                    raise ValueError("Choose an exact publication time.")
                opts = copy.deepcopy(preset["defaults"]) | {
                    "scheduled_at": when,
                    "timezone": preset["timezone"],
                    "title": "Video " + tid[:60],
                }
                if preset["platform"] == "youtube" and when:
                    opts["privacy"] = "public"
                opts = service(preset["platform"]).options(opts)
                items.append(
                    dict(
                        id=uuid.uuid4().hex,
                        task_id=tid,
                        final=copy.deepcopy(final),
                        destination=current[key],
                        options=opts,
                        language=preset["language"],
                        thumbnail_requested=preset["thumbnail"],
                        state="queued",
                        delivery_id=None,
                        error="",
                    )
                )
        bid = uuid.uuid4().hex
        value = dict(
            id=bid, created_at=datetime.now(UTC).isoformat(), revision=0, items=items
        )
        _write(value)
    enqueue("batch", bid)
    return batch(bid)


def prepare_batch(bid):
    try:
        with _lease(bid):
            value = batch(bid)
            existing = {
                j.get("planner_reference"): j
                for platform in {i["destination"]["platform"] for i in value["items"]}
                for j in service(platform).jobs()
                if j.get("planner_reference")
            }
            for item in value["items"]:
                if item["state"] != "queued":
                    continue
                try:
                    _final(item["task_id"], item["final"])
                    found = existing.get(bid + ":" + item["id"])
                    if not found:
                        item["state"] = "preparing"
                        _write(value)
                        platform = item["destination"]["platform"]
                        relative = item["final"]["source"]
                        tid = item["task_id"]
                        summary = item["final"].get("summary", "")
                        package = seo.load(tid, relative, platform)
                        if (
                            not package
                            or package["language"] != item["language"]
                            or package.get("brief", "") != summary
                        ):
                            package = _generate_package(
                                tid,
                                relative,
                                platform,
                                language=item["language"],
                                brief=summary,
                            )
                        opts = item["options"] | {
                            "title": package["metadata"]["titles"][0],
                            "description": package["metadata"]["description"],
                        }
                        if platform == "youtube":
                            opts["tags"] = package["metadata"]["tags"]
                        kwargs = {
                            "publishing_package": package,
                            "planner_reference": bid + ":" + item["id"],
                        }
                        if platform == "youtube" and item["thumbnail_requested"]:
                            record = package.get("thumbnail") or seo.make_thumbnail(
                                tid, relative, package["metadata"]["thumbnail_text"]
                            )
                            kwargs["thumbnail"] = record
                        _final(tid, item["final"])
                        found = service(platform).prepare(
                            tid,
                            relative,
                            item["destination"]["connection_id"],
                            opts,
                            **kwargs,
                        )
                    item.update(
                        delivery_id=found["id"],
                        options=found["options"],
                        state="review" if found["state"] == "draft" else "submitted",
                        error="",
                    )
                except Exception as exc:
                    item.update(
                        state="error",
                        error=str(exc)
                        if isinstance(exc, ValueError)
                        else "Publishing preparation failed. Check the saved video, AI provider and connection, then retry.",
                    )
                _write(value)
            return value
    except Timeout:
        return batch(bid)


def retry_item(bid, iid):
    with _lease(bid):
        value = batch(bid)
        item = next(i for i in value["items"] if i["id"] == iid)
        if item["state"] not in {"error", "blocked"}:
            raise ValueError("Only blocked preparation can be retried here.")
        if item.get("delivery_id"):
            job = service(item["destination"]["platform"]).get(item["delivery_id"])
            if job["state"] != "draft":
                raise ValueError("Use delivery controls for an approved post.")
            item["state"] = "review"
        else:
            item["state"] = "queued"
        item["error"] = ""
        _write(value)
    enqueue("batch", bid)


def edit_item(bid, iid, options):
    with _lease(bid), lock():
        value = batch(bid)
        item = next(i for i in value["items"] if i["id"] == iid)
        svc = service(item["destination"]["platform"])
        if item["state"] not in {"review", "blocked"} or not item.get("delivery_id"):
            raise ValueError("Only prepared draft posts can be changed here.")
        normalized = svc.options(options)
        if (
            item["destination"]["platform"] == "facebook"
            and normalized["media_type"] != item["options"]["media_type"]
        ):
            raise ValueError(
                "Changing Facebook format requires excluding this post and preparing a new draft."
            )
        if normalized.get("scheduled_at"):
            wanted = int(_when(normalized["scheduled_at"]).timestamp())
            current = _when(item["options"].get("scheduled_at"))
            if (
                not current or wanted != int(current.timestamp())
            ) and wanted in _occupied(item["destination"]["key"]):
                raise ValueError("This account already has a post at that time.")
        with svc.lease(item["delivery_id"]):
            child = svc._get(item["delivery_id"])
            if child["state"] != "draft":
                raise ValueError(
                    "This post is already approved; use delivery controls."
                )
            child["options"] = normalized
            svc._write(
                child, "Publishing draft changed; batch review is required again."
            )
        item.update(options=normalized, state="review", error="")
        return _write(value)


def exclude_item(bid, iid):
    with _lease(bid), lock():
        value = batch(bid)
        item = next(i for i in value["items"] if i["id"] == iid)
        if item["state"] == "submitted":
            raise ValueError(
                "Cancel the actual delivery before removing an approved post."
            )
        if item.get("delivery_id"):
            svc = service(item["destination"]["platform"])
            with svc.lease(item["delivery_id"]):
                child = svc._get(item["delivery_id"])
                if child["state"] != "draft":
                    raise ValueError("This post is already approved.")
                child["state"] = "cancelled"
                svc._write(child, "Unapproved batch post excluded.")
        item.update(state="excluded", error="")
        return _write(value)


def approve_batch(bid, reviewed=False, revision=None):
    if reviewed is not True:
        raise ValueError(
            "Review the final videos, account-specific posts and exact times first."
        )
    with _lease(bid), lock():
        value = batch(bid)
        if revision != value["revision"]:
            raise ValueError(
                "The batch changed. Review its latest posts before approving."
            )
        for item in value["items"]:
            if item["state"] != "review":
                continue
            svc = service(item["destination"]["platform"])
            try:
                child = svc.get(item["delivery_id"])
                if child["state"] != "draft":
                    item.update(
                        state="cancelled"
                        if child["state"] in {"cancelled", "deleted"}
                        else "submitted",
                        error="",
                    )
                    _write(value)
                    continue
                _final(item["task_id"], item["final"])
                if child["options"] != item["options"]:
                    raise ValueError(
                        "Post settings changed outside the batch. Review it again."
                    )
                if child["state"] == "draft":
                    svc.approve(child["id"], True)
                item.update(state="submitted", error="")
            except Exception as exc:
                item.update(
                    state="blocked",
                    error=str(exc)
                    if isinstance(exc, ValueError)
                    else "Approval interrupted. Refresh the existing delivery; do not create a replacement.",
                )
            _write(value)
        return value


def delivery_rows():
    rows = []
    for b in batches():
        for item in b["items"]:
            row = item | {"batch_id": b["id"]}
            if item.get("delivery_id"):
                try:
                    row["delivery"] = service(item["destination"]["platform"]).get(
                        item["delivery_id"]
                    )
                except ValueError:
                    row["error"] = (
                        "Delivery history is unavailable. Check Accounts; no replacement was created."
                    )
            rows.append(row)
    return rows


def _auto_key(tid, relative, platform, language):
    context = seo.context(tid, relative)
    return hashlib.sha256(
        json.dumps(
            [
                tid,
                relative,
                platform,
                language,
                context["stamp"],
                context["script_sha256"],
                catalog()["finals"].get(tid, {}).get("summary", ""),
            ]
        ).encode()
    ).hexdigest()


def discover_automatic(task_id=None):
    data = catalog()
    if not data["auto_prepare"]:
        return
    profiles = {(p["platform"], p["language"]) for p in data["presets"].values()}
    for project in projects():
        if task_id and project["task_id"] != task_id:
            continue
        if not project["available"]:
            continue
        for platform, language in profiles:
            try:
                key = _auto_key(
                    project["task_id"], project["source"], platform, language
                )
            except (ValueError, OSError):
                continue
            with lock():
                data = catalog()
                if not data["auto_prepare"]:
                    return
                if key in data["auto"] or len(data["auto"]) >= 1000:
                    continue
                data["auto"][key] = dict(
                    task_id=project["task_id"],
                    source=project["source"],
                    platform=platform,
                    language=language,
                    summary=catalog()["finals"]
                    .get(project["task_id"], {})
                    .get("summary", ""),
                    state="queued",
                    error="",
                )
                _save(data)
            enqueue("seo", key)


def _prepare_auto(key):
    with FileLock(root() / ("auto-" + key + ".lock"), timeout=0):
        with lock():
            data = catalog()
            item = data["auto"].get(key)
            if not item or item["state"] != "queued" or not data["auto_prepare"]:
                return
            item["state"] = "preparing"
            _save(data)
        try:
            if (
                _auto_key(
                    item["task_id"], item["source"], item["platform"], item["language"]
                )
                != key
            ):
                raise ValueError(
                    "Video or script changed. Prepare the updated version."
                )
            package = seo.load(item["task_id"], item["source"], item["platform"])
            if (
                not package
                or package["language"] != item["language"]
                or package.get("brief", "") != item.get("summary", "")
            ):
                _generate_package(
                    item["task_id"],
                    item["source"],
                    item["platform"],
                    language=item["language"],
                    brief=item.get("summary", ""),
                )
            item.update(state="prepared", error="")
        except Exception as exc:
            item.update(
                state="error",
                error=str(exc)
                if isinstance(exc, ValueError)
                else "Automatic AI preparation failed. Use Create post to review the source and retry.",
            )
        with lock():
            data = catalog()
            data["auto"][key] = item
            _save(data)


def _pending():
    for b in batches():
        if any(i["state"] == "queued" for i in b["items"]):
            yield "batch", b["id"]
    data = catalog()
    if data["auto_prepare"]:
        for key, item in data["auto"].items():
            if item["state"] == "queued":
                yield "seo", key


def _work():
    failed = set()
    while True:
        kind, key = _queue.get()
        try:
            if kind == "batch":
                prepare_batch(key)
            elif kind == "status":
                refresh_pending()
            else:
                _prepare_auto(key)
        except Exception as exc:
            failed.add((kind, key))
            logger.warning(
                "Publishing preparation worker interrupted: {}", type(exc).__name__
            )
        finally:
            with _guard:
                _running.discard((kind, key))
            _queue.task_done()
        try:
            for job in _pending():
                if job not in failed:
                    enqueue(*job)
        except (ValueError, OSError):
            pass


def enqueue(kind, key):
    global _started
    with _guard:
        if (kind, key) in _running:
            return
        if not _started:
            threading.Thread(
                target=_work, name="publishing-preparation", daemon=True
            ).start()
            _started = True
        try:
            _queue.put_nowait((kind, key))
            _running.add((kind, key))
        except Full:
            pass  # Durable queue entries are picked up after a worker slot opens.


def recover():
    # Interrupted preparation is safe to repeat, but approvals are never replayed.
    for b in batches():
        try:
            with _lease(b["id"]):
                value = batch(b["id"])
                changed = False
                for item in value["items"]:
                    if item["state"] == "preparing":
                        item["state"] = "queued"
                        changed = True
                if changed:
                    _write(value)
        except Timeout:
            pass
    for key, item in catalog()["auto"].items():
        if item["state"] == "preparing":
            try:
                with FileLock(root() / ("auto-" + key + ".lock"), timeout=0), lock():
                    data = catalog()
                    if data["auto"].get(key, {}).get("state") == "preparing":
                        data["auto"][key]["state"] = "queued"
                        _save(data)
            except Timeout:
                pass
    for job in _pending():
        enqueue(*job)


def completed(task_id):
    """Best-effort hook: generation success never depends on optional AI preparation."""
    try:
        discover_automatic(task_id)
    except Exception as exc:
        logger.warning("Library preparation deferred: {}", type(exc).__name__)


def _reserves(item):
    if item["state"] in {"excluded", "cancelled"}:
        return False
    if item.get("delivery_id"):
        try:
            return service(item["destination"]["platform"]).get(item["delivery_id"])[
                "state"
            ] not in {"cancelled", "deleted"}
        except ValueError:
            return True
    return True


def delivery_action(bid, iid, action, reviewed=False, when=None):
    if reviewed is not True:
        raise ValueError("Review the existing delivery and requested action first.")
    with _lease(bid), lock():
        value = batch(bid)
        item = next(i for i in value["items"] if i["id"] == iid)
        if not item.get("delivery_id"):
            raise ValueError("This post has no prepared delivery yet.")
        svc = service(item["destination"]["platform"])
        jid = item["delivery_id"]
        if action == "refresh":
            result = svc.refresh(jid)
        elif action == "resume":
            result = svc.resume(jid, True)
        elif action == "cancel":
            result = (
                svc.cancel(jid)
                if item["destination"]["platform"] == "youtube"
                else svc.cancel(jid, True)
            )
        elif action == "reschedule":
            desired = _when(when)
            old = _when(item["options"].get("scheduled_at"))
            if not desired or (
                desired != old
                and int(desired.timestamp()) in _occupied(item["destination"]["key"])
            ):
                raise ValueError(
                    "This account already has a post at the requested time."
                )
            result = svc.reschedule(jid, when, True)
        else:
            raise ValueError("Unsupported delivery action.")
        item.update(
            options=result["options"],
            state="cancelled"
            if result["state"] == "cancelled"
            else "review"
            if result["state"] == "draft"
            else "submitted",
            error="",
        )
        _write(value)
        return result


def refresh_pending():
    checked = 0
    for item in delivery_rows():
        job = item.get("delivery", {})
        poll_key = item["destination"]["platform"] + ":" + str(job.get("id", ""))
        if (
            job.get("video_id")
            and job.get("state") in {"processing", "scheduled"}
            and time.time() - max(job.get("checked_at", 0), _last_poll.get(poll_key, 0))
            > 60
        ):
            if job["state"] == "scheduled" and _when(
                job["options"].get("scheduled_at")
            ) > datetime.now(UTC):
                continue
            _last_poll[poll_key] = time.time()
            if len(_last_poll) > 5000:
                for old_key in list(_last_poll):
                    if time.time() - _last_poll[old_key] > 3600:
                        _last_poll.pop(old_key, None)
            try:
                service(item["destination"]["platform"]).refresh(job["id"])
            except (ValueError, OSError):
                pass
            checked += 1
            if checked >= 5:
                break


def replace_thumbnail(bid, iid, text, seconds=0, font=None, remove=False):
    with _lease(bid):
        value = batch(bid)
        item = next(i for i in value["items"] if i["id"] == iid)
        if item["destination"]["platform"] != "youtube" or item["state"] != "review":
            raise ValueError("Choose an unapproved YouTube draft.")
        _final(item["task_id"], item["final"])
        record = (
            None
            if remove
            else seo.make_thumbnail(
                item["task_id"], item["final"]["source"], text, seconds, font
            )
        )
        with youtube.lease(item["delivery_id"]):
            child = youtube._get(item["delivery_id"])
            if child["state"] != "draft":
                raise ValueError("This delivery is already approved.")
            child["thumbnail"] = record
            youtube._write(
                child, "Thumbnail changed. Review the updated batch before approval."
            )
        return _write(value)


def _generate_package(task_id, relative, platform, **kwargs):
    from app.config import config

    # Generation temporarily applies a task configuration under this lock.
    # Capture the restored operator configuration; do not persist credentials.
    with config.runtime_config_lock():
        snapshot = copy.deepcopy(config.app)
    return seo.generate(task_id, relative, platform, app_config=snapshot, **kwargs)


def _processing(task_id):
    from app.services import state as sm
    from app.models import const

    return (sm.state.get_task(task_id) or {}).get(
        "state"
    ) == const.TASK_STATE_PROCESSING


def startup():
    from app.services import campaigns

    try:
        campaigns.recover()
    except Exception as exc:
        logger.warning("Campaign recovery deferred: {}", type(exc).__name__)
    for operation in (youtube.recover, facebook.recover, recover, discover_automatic):
        try:
            operation()
        except Exception as exc:
            logger.warning("Publishing recovery deferred: {}", type(exc).__name__)
