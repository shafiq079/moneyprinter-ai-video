"""Central content library and reviewed batch publishing in the existing WebUI."""

from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo

import streamlit as st
from filelock import Timeout

from app.config import config
from app.services import (
    content_library as lib,
    youtube_studio as media,
    publishing_seo as seo,
)


def navigation(tr):
    with st.container(horizontal=True):
        st.link_button(tr("Create"), "?")
        st.link_button(tr("Campaigns"), "?view=campaigns")
        st.link_button(tr("Content Library"), "?view=library")
        st.link_button(tr("Publishing"), "?view=publishing")
        st.link_button(tr("Accounts"), "?view=social")


def _error(exc):
    st.error(
        "Batch preparation or approval is in progress. Refresh shortly."
        if isinstance(exc, Timeout)
        else str(exc)
    )


def _render_library(tr):
    navigation(tr)
    st.title(tr("Content Library"))
    st.caption(
        tr(
            "Review completed videos here. Editing is optional; choose an original or an OpenCut export as the final version."
        )
    )
    lib.recover()
    lib.discover_automatic()
    projects = lib.projects()
    if st.query_params.get("campaign"):
        from app.services import campaigns

        task_ids = {
            i["task_id"] for i in campaigns.get(st.query_params["campaign"])["items"]
        }
        projects = [p for p in projects if p["task_id"] in task_ids]
    if not projects:
        st.info(tr("Complete a video to add it to your library."))
        return
    query = st.text_input(tr("Find a video"), key="library_search")
    status = st.radio(
        tr("Library filter"),
        [tr("All videos"), tr("Ready to publish"), tr("Needs review")],
        horizontal=True,
        key="library_filter",
    )
    visible = [
        p
        for p in projects
        if query.casefold() in (p["title"] + " " + p["task_id"]).casefold()
        and (
            status == tr("All videos")
            or p["ready"] == (status == tr("Ready to publish"))
        )
    ]
    st.caption(tr("Videos found") + ": " + str(len(visible)))
    page = st.number_input(
        tr("Library page"),
        min_value=1,
        max_value=max(1, (len(visible) + 11) // 12),
        value=1,
        step=1,
        key="library_page",
    )
    deliveries = lib.delivery_rows()
    for offset in range(0, len(visible[(page - 1) * 12 : page * 12]), 2):
        columns = st.columns(2)
        for col, p in zip(
            columns, visible[(page - 1) * 12 : page * 12][offset : offset + 2]
        ):
            with col, st.container(border=True):
                tid = p["task_id"]
                st.subheader(p["title"])
                st.caption(tid)
                choices = [v["asset"] for v in p["versions"]]
                chosen = st.selectbox(
                    tr("Final video version"),
                    choices,
                    index=choices.index(p["source"]) if p["source"] in choices else 0,
                    key="library_version:" + tid,
                )
                st.video(str(media.source_file(tid, chosen)))
                st.caption(
                    tr("Ready to publish")
                    if p["ready"] and chosen == p["source"]
                    else tr("Needs review")
                )
                if not p["available"]:
                    st.warning(
                        tr(
                            "The selected final version is unavailable. Select and review another version."
                        )
                    )
                with st.expander(tr("Video summary for AI (optional)")):
                    summary = st.text_area(
                        tr("Updated video summary"),
                        value=p.get("summary", ""),
                        max_chars=12000,
                        key="library_summary:"
                        + tid
                        + ":"
                        + chosen
                        + ":"
                        + str(p["revision"]),
                    )
                    st.caption(
                        tr(
                            "Use this if an edited export changes the saved script. Leave blank to use the original script."
                        )
                    )
                for delivery in [r for r in deliveries if r["task_id"] == tid]:
                    state = delivery.get("delivery", {}).get("state", delivery["state"])
                    st.caption(
                        delivery["destination"]["platform"].title()
                        + " · "
                        + delivery["destination"]["name"]
                        + " · "
                        + state
                    )
                if any(r["task_id"] == tid for r in deliveries):
                    batch_id = next(
                        r["batch_id"] for r in deliveries if r["task_id"] == tid
                    )
                    st.link_button(
                        tr("Manage publishing"), "?view=publishing&batch=" + batch_id
                    )
                    st.caption(
                        tr(
                            "Changing the final version does not replace already-approved posts. Manage or cancel those deliveries in Publishing."
                        )
                    )
                reviewed = st.checkbox(
                    tr("I reviewed this final video"),
                    value=p["ready"] and chosen == p["source"],
                    key="library_review:"
                    + tid
                    + ":"
                    + chosen
                    + ":"
                    + str(p["revision"]),
                )
                if st.button(tr("Save final version"), key="library_save:" + tid):
                    try:
                        lib.select_final(tid, chosen, reviewed, summary)
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        _error(exc)
                if config.app.get("upload_post_auto_upload"):
                    st.warning(
                        tr(
                            "Legacy automatic cross-posting is enabled. Turn it off in Settings if you want all videos to use this reviewed workflow."
                        )
                    )
                if os.environ.get("MPT_OPENCUT") == "1":
                    from webui.opencut_launch import launch_url

                    st.link_button(tr("Edit in OpenCut"), launch_url(tid))
                else:
                    st.link_button(tr("Edit in OpenCut"), "?editor=" + tid)
    st.subheader(tr("Prepare selected videos"))
    ready = [p for p in projects if p["ready"]]
    if st.button(
        tr("Select all ready videos"), disabled=not ready, key="library_select_all"
    ):
        st.session_state["library_batch_videos"] = [p["task_id"] for p in ready]
    selected = st.multiselect(
        tr("Ready videos"),
        [p["task_id"] for p in ready],
        format_func=lambda tid: next(
            p["title"] + " · " + tid[:8] for p in ready if p["task_id"] == tid
        ),
        key="library_batch_videos",
    )
    destinations = lib.destinations()
    presets = lib.catalog()["presets"]
    eligible = [d for d in destinations if d["key"] in presets]
    if not eligible:
        st.info(
            tr(
                "Connect accounts, then save their posting defaults in Publishing before preparing a batch."
            )
        )
    keys = st.multiselect(
        tr("Publishing destinations"),
        [d["key"] for d in eligible],
        format_func=lambda key: next(
            d["platform"].title() + " · " + d["name"]
            for d in eligible
            if d["key"] == key
        ),
        key="library_batch_accounts",
    )
    mode = st.radio(
        tr("Batch timing"),
        [
            tr("Next available slots"),
            tr("Choose start time"),
            tr("Publish after approval"),
        ],
        key="library_batch_mode",
        horizontal=True,
    )
    exact = None
    spacing = 60
    if mode == tr("Choose start time"):
        exact = _time(tr, "library_batch:")
        spacing = st.number_input(
            tr("Minutes between videos per account"),
            min_value=1,
            max_value=1440,
            value=60,
            key="library_batch_spacing",
        )
    st.caption(
        tr(
            "Preparation creates separate drafts for every video and destination. Nothing is uploaded until you review and approve the prepared posts."
        )
    )
    if st.button(
        tr("Prepare publishing batch"),
        disabled=not (selected and keys),
        key="library_prepare",
        type="primary",
    ):
        try:
            batch = lib.create_batch(
                selected,
                keys,
                "slots"
                if mode == tr("Next available slots")
                else "exact"
                if mode == tr("Choose start time")
                else "now",
                _convert(exact) if exact else None,
                int(spacing),
            )
            st.query_params.update(view="publishing", batch=batch["id"])
            st.rerun()
        except (ValueError, OSError) as exc:
            _error(exc)


def _time(tr, prefix):
    zone = st.text_input(
        tr("Timezone (IANA)"), value="Asia/Karachi", key=prefix + "zone"
    )
    date = st.date_input(
        tr("Scheduled date"),
        value=datetime.now(ZoneInfo("Asia/Karachi")).date() + timedelta(days=1),
        key=prefix + "date",
    )
    clock = st.time_input(
        tr("Scheduled time"),
        value=datetime.min.time().replace(hour=12),
        key=prefix + "time",
    )
    return date, clock, zone


def _convert(values):
    return media.scheduled_utc(datetime.combine(values[0], values[1]), values[2])


def _presets(tr):
    st.subheader(tr("Account posting defaults"))
    targets = lib.destinations()
    if not targets:
        st.info(tr("Connect YouTube or Facebook in Accounts first."))
        return
    key = st.selectbox(
        tr("Account to configure"),
        [d["key"] for d in targets],
        format_func=lambda k: next(
            d["platform"].title() + " · " + d["name"] for d in targets if d["key"] == k
        ),
        key="planner_preset_account",
    )
    target = next(d for d in targets if d["key"] == key)
    saved = lib.catalog()["presets"].get(key, {})
    defaults = saved.get("defaults", {})
    with st.form("planner_preset:" + key):
        zone = st.text_input(
            tr("Timezone (IANA)"),
            value=saved.get("timezone", "Asia/Karachi"),
            key="preset_zone:" + key,
        )
        times = st.text_input(
            tr("Posting times (HH:MM, comma separated)"),
            value=", ".join(saved.get("times", ["12:00", "19:00"])),
            key="preset_times:" + key,
        )
        names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        days = st.multiselect(
            tr("Posting weekdays"),
            range(7),
            default=saved.get("days", list(range(7))),
            format_func=lambda d: tr(names[d]),
            key="preset_days:" + key,
        )
        language = st.text_input(
            tr("Publishing language"),
            value=saved.get("language", "auto"),
            key="preset_language:" + key,
        )
        if target["platform"] == "youtube":
            audience = st.selectbox(
                tr("Audience declaration"),
                [None, False, True],
                index=[None, False, True].index(defaults.get("made_for_kids")),
                format_func=lambda v: (
                    tr("Choose an audience")
                    if v is None
                    else tr("Made for children")
                    if v
                    else tr("Not made for children")
                ),
                key="preset_audience:" + key,
            )
            privacy = st.selectbox(
                tr("Visibility"),
                ["private", "unlisted", "public"],
                index=["private", "unlisted", "public"].index(
                    defaults.get("privacy", "public")
                ),
                key="preset_privacy:" + key,
            )
            category = st.text_input(
                tr("YouTube category ID"),
                value=defaults.get("category", "22"),
                key="preset_category:" + key,
            )
            synthetic = st.checkbox(
                tr("Contains realistic altered or synthetic content"),
                value=defaults.get("synthetic", True),
                key="preset_synthetic:" + key,
            )
            paid = st.checkbox(
                tr("Contains paid product placement"),
                value=defaults.get("paid_placement", False),
                key="preset_paid:" + key,
            )
            thumbnail = st.checkbox(
                tr("Build video-frame thumbnails automatically"),
                value=saved.get("thumbnail", True),
                key="preset_thumbnail:" + key,
            )
            values = dict(
                privacy=privacy,
                category=category,
                made_for_kids=audience,
                synthetic=synthetic,
                paid_placement=paid,
                tags=[],
            )
            st.caption(
                tr(
                    "Scheduled YouTube posts use public release, even if the immediate-upload default is private. Review the exact settings in each batch."
                )
            )
        else:
            media_type = st.selectbox(
                tr("Facebook format"),
                ["VIDEO", "REELS"],
                index=["VIDEO", "REELS"].index(defaults.get("media_type", "REELS")),
                key="preset_format:" + key,
            )
            synthetic = st.checkbox(
                tr("Label this Reel as AI-generated"),
                value=defaults.get("synthetic", True),
                key="preset_synthetic:" + key,
            )
            values = dict(media_type=media_type, synthetic=synthetic)
            thumbnail = False
        reviewed = st.checkbox(
            tr("I reviewed these reusable publishing defaults"),
            key="preset_review:" + key,
        )
        save = st.form_submit_button(tr("Save posting defaults"))
    if save:
        try:
            if not reviewed:
                raise ValueError(tr("Review these defaults before saving."))
            lib.save_preset(
                key,
                zone,
                [t.strip() for t in times.split(",") if t.strip()],
                list(days),
                values,
                language,
                thumbnail,
            )
            st.success(tr("Posting defaults saved."))
        except (ValueError, OSError) as exc:
            _error(exc)
    st.divider()
    automatic = st.checkbox(
        tr("Automatically prepare AI copy for completed videos (no publishing)"),
        value=lib.catalog()["auto_prepare"],
        key="planner_auto_prepare",
    )
    if st.button(tr("Save preparation automation"), key="planner_save_auto"):
        lib.set_automatic(automatic)
        lib.discover_automatic()
        st.success(tr("Preparation automation saved."))
    st.caption(
        tr(
            "Automatic preparation uses your configured LLM and saved account languages. It never marks videos ready, approves posts, or uploads them."
        )
    )
    failures = [a for a in lib.catalog()["auto"].values() if a["state"] == "error"]
    if failures:
        st.warning(
            tr(
                "Some automatic AI preparations failed. Batch preparation retries missing copy; an edited export may need an updated summary in the individual composer."
            )
        )
        st.dataframe(
            [
                {"Video": a["task_id"], "Platform": a["platform"], "Error": a["error"]}
                for a in failures
            ],
            hide_index=True,
        )


def _batch(tr):
    values = lib.batches()
    if not values:
        st.info(tr("Prepare a batch from Content Library first."))
        return
    wanted = st.query_params.get("batch")
    ids = [v["id"] for v in values]
    if st.session_state.get("planner_requested_batch") != wanted:
        st.session_state["planner_requested_batch"] = wanted
        if wanted in ids:
            st.session_state["planner_batch"] = wanted
    bid = st.selectbox(
        tr("Publishing batch"),
        ids,
        index=ids.index(wanted) if wanted in ids else 0,
        format_func=lambda b: next(
            v["created_at"][:16]
            + " · "
            + str(len(v["items"]))
            + " "
            + tr("posts")
            + " · "
            + v["id"][:8]
            for v in values
            if v["id"] == b
        ),
        key="planner_batch",
    )
    value = lib.batch(bid)
    if any(i["state"] in {"queued", "preparing"} for i in value["items"]):
        _preparation_progress(
            bid,
            value["revision"],
            any(i["state"] == "review" for i in value["items"]),
            tr,
        )
    st.dataframe(
        [
            {
                "Video": i["task_id"],
                "Account": i["destination"]["name"],
                "Platform": i["destination"]["platform"],
                "Title": i["options"]["title"],
                "Description": i["options"]["description"],
                "YouTube tags": ", ".join(i["options"].get("tags", [])),
                "State": i["state"],
                "Time (UTC)": lib._when(i["options"]["scheduled_at"]).isoformat()
                if i["options"].get("scheduled_at")
                else tr("After approval"),
                "Issue": i["error"],
            }
            for i in value["items"]
        ],
        hide_index=True,
        width="stretch",
    )
    if any(i["state"] in {"queued", "preparing"} for i in value["items"]):
        st.info(
            tr(
                "AI copy and frozen delivery drafts are being prepared. Refresh this batch to see progress."
            )
        )
    if st.button(tr("Refresh batch"), key="planner_refresh_batch"):
        st.rerun()
    iid = st.selectbox(
        tr("Post to review"),
        [i["id"] for i in value["items"]],
        format_func=lambda v: next(
            i["task_id"]
            + " · "
            + i["destination"]["platform"]
            + " · "
            + i["destination"]["name"]
            for i in value["items"]
            if i["id"] == v
        ),
        key="planner_item:" + bid,
    )
    item = next(i for i in value["items"] if i["id"] == iid)
    if item["error"]:
        st.error(item["error"])
    if item.get("delivery_id"):
        svc = lib.service(item["destination"]["platform"])
        try:
            child = svc.get(item["delivery_id"])
            st.video(str(media.snapshot_file(child)))
            if child.get("thumbnail"):
                st.image(str(seo.thumbnail_file(child["thumbnail"])), width=400)
            st.json(child["options"])
            if child["state"] == "draft" and item["state"] in {"review", "blocked"}:
                _edit(tr, bid, item)
                if item["destination"]["platform"] == "youtube":
                    with st.expander(tr("Change this thumbnail")):
                        text = st.text_input(
                            tr("Thumbnail overlay text"),
                            value=(child.get("thumbnail") or {}).get("text", ""),
                            max_chars=60,
                            key="planner_thumb_text:" + iid,
                        )
                        seconds = st.number_input(
                            tr("Thumbnail frame time (seconds)"),
                            min_value=0.0,
                            value=0.0,
                            step=0.1,
                            key="planner_thumb_time:" + iid,
                        )
                        fonts = seo.thumbnail_fonts()
                        font = (
                            st.selectbox(
                                tr("Thumbnail font"),
                                fonts,
                                key="planner_thumb_font:" + iid,
                            )
                            if fonts
                            else None
                        )
                        if st.button(
                            tr("Rebuild thumbnail"), key="planner_thumb_build:" + iid
                        ):
                            try:
                                lib.replace_thumbnail(bid, iid, text, seconds, font)
                                st.rerun()
                            except (ValueError, OSError) as exc:
                                _error(exc)
                        if child.get("thumbnail") and st.button(
                            tr("Remove this thumbnail"),
                            key="planner_thumb_remove:" + iid,
                        ):
                            try:
                                lib.replace_thumbnail(bid, iid, "", remove=True)
                                st.rerun()
                            except (ValueError, OSError) as exc:
                                _error(exc)

            elif child["state"] != "draft":
                _delivery(tr, bid, item, child)
        except (ValueError, OSError) as exc:
            _error(exc)
    if item["state"] in {"error", "blocked"} and st.button(
        tr("Retry this preparation"), key="planner_retry:" + iid
    ):
        try:
            lib.retry_item(bid, iid)
            st.rerun()
        except (ValueError, OSError) as exc:
            _error(exc)
    if item["state"] not in {"submitted", "excluded", "cancelled", "preparing"}:
        if st.button(tr("Exclude this unapproved post"), key="planner_exclude:" + iid):
            try:
                lib.exclude_item(bid, iid)
                st.rerun()
            except (ValueError, OSError) as exc:
                _error(exc)
    prepared = [i for i in value["items"] if i["state"] == "review"]
    blocked = [
        i
        for i in value["items"]
        if i["state"] in {"error", "blocked", "queued", "preparing"}
    ]
    st.subheader(tr("Approve prepared posts"))
    st.write(
        tr("Prepared posts")
        + ": "
        + str(len(prepared))
        + " · "
        + tr("Not included yet")
        + ": "
        + str(len(blocked))
    )
    st.caption(
        tr(
            "Only prepared posts listed for review are approved. Blocked or unfinished posts stay unapproved. Each destination uploads independently."
        )
    )
    checked = st.checkbox(
        tr(
            "I reviewed the final videos, destination accounts, metadata, thumbnails and exact publishing times"
        ),
        key="planner_approve_check:" + bid + ":" + str(value["revision"]),
    )
    if st.button(
        tr("Approve prepared posts"),
        disabled=not (checked and prepared),
        key="planner_approve:" + bid,
        type="primary",
    ):
        try:
            lib.approve_batch(bid, checked, value["revision"])
            st.rerun()
        except (ValueError, OSError) as exc:
            _error(exc)


def _edit(tr, bid, item):
    iid = item["id"]
    opts = item["options"]
    platform = item["destination"]["platform"]
    with st.expander(tr("Edit this publishing draft")):
        timing = st.radio(
            tr("Delivery time"),
            [
                tr("Keep planned time"),
                tr("Choose a new time"),
                tr("Publish after approval"),
            ],
            key="planner_edit_mode:" + iid,
        )
        with st.form("planner_edit:" + iid):
            if platform == "youtube":
                from webui.social_dashboard import _fields

                edited, _ = _fields(
                    tr, "planner_fields:" + iid + ":", opts, schedule=False
                )
            else:
                edited = opts | dict(
                    title=st.text_input(
                        tr("Facebook title"),
                        value=opts["title"],
                        max_chars=100,
                        key="planner_title:" + iid,
                    ),
                    description=st.text_area(
                        tr("Facebook description"),
                        value=opts["description"],
                        max_chars=5000,
                        key="planner_description:" + iid,
                    ),
                )
                edited["media_type"] = st.selectbox(
                    tr("Facebook format"),
                    ["VIDEO", "REELS"],
                    index=["VIDEO", "REELS"].index(opts["media_type"]),
                    key="planner_format:" + iid,
                )
                edited["synthetic"] = st.checkbox(
                    tr("Label this Reel as AI-generated"),
                    value=opts["synthetic"],
                    key="planner_synthetic:" + iid,
                )
            when = (
                _time(tr, "planner_edit_time:" + iid)
                if timing == tr("Choose a new time")
                else None
            )
            submit = st.form_submit_button(tr("Save draft changes"))
        if submit:
            try:
                # Changing format requires fresh media validation instead of trusting a VIDEO snapshot as a Reel.
                if (
                    platform == "facebook"
                    and edited["media_type"] != opts["media_type"]
                ):
                    raise ValueError(
                        tr(
                            "Changing Facebook format requires a new batch after excluding this post."
                        )
                    )
                edited["scheduled_at"] = (
                    _convert(when)
                    if when
                    else opts.get("scheduled_at")
                    if timing == tr("Keep planned time")
                    else None
                )
                edited["timezone"] = when[2] if when else opts.get("timezone", "UTC")
                lib.edit_item(bid, iid, edited)
                st.rerun()
            except (ValueError, OSError) as exc:
                _error(exc)


def _delivery(tr, bid, item, child):
    st.info(tr("Delivery state") + ": " + child["state"])
    if child.get("message"):
        st.caption(child["message"])
    if child.get("post_url"):
        st.link_button(tr("Open published post"), child["post_url"])
    if st.button(
        tr("Refresh delivery status"), key="planner_delivery_refresh:" + item["id"]
    ):
        try:
            lib.delivery_action(bid, item["id"], "refresh", True)
            st.rerun()
        except (ValueError, OSError) as exc:
            _error(exc)
    checked = st.checkbox(
        tr("I reviewed this existing delivery and the action below"),
        key="planner_delivery_check:" + item["id"],
    )
    if child["state"] in {"paused", "blocked", "release_pending", "ready", "unknown"}:
        if st.button(
            tr("Resume existing delivery"),
            disabled=not checked,
            key="planner_delivery_resume:" + item["id"],
        ):
            try:
                lib.delivery_action(bid, item["id"], "resume", checked)
                st.rerun()
            except (ValueError, OSError) as exc:
                _error(exc)
    if child["state"] in lib.service(item["destination"]["platform"]).ACTIVE:
        st.caption(
            tr(
                "YouTube cancellation keeps the upload private. Facebook cancellation deletes only a confirmed unpublished upload."
            )
        )
        if st.button(
            tr("Cancel existing delivery"),
            disabled=not checked,
            key="planner_delivery_cancel:" + item["id"],
        ):
            try:
                lib.delivery_action(bid, item["id"], "cancel", checked)
                st.rerun()
            except (ValueError, OSError) as exc:
                _error(exc)
    if child.get("video_id") and child["state"] in {
        "scheduled",
        "release_pending",
        "ready",
        "blocked",
        "unknown",
    }:
        with st.expander(tr("Change publication time")):
            with st.form("planner_reschedule:" + item["id"]):
                timing = _time(tr, "planner_reschedule:" + item["id"])
                submit = st.form_submit_button(tr("Update publication time"))
            if submit:
                try:
                    lib.delivery_action(
                        bid, item["id"], "reschedule", checked, _convert(timing)
                    )
                    st.rerun()
                except (ValueError, OSError) as exc:
                    _error(exc)


@st.fragment(run_every=30)
def _calendar(tr):
    lib.enqueue("status", "all")
    rows = lib.delivery_rows()
    if not rows:
        st.info(tr("No planned posts yet."))
        return
    account = st.multiselect(
        tr("Filter by account"),
        sorted({r["destination"]["key"] for r in rows}),
        key="planner_calendar_accounts",
    )
    states = st.multiselect(
        tr("Filter by delivery state"),
        sorted({r.get("delivery", {}).get("state", r["state"]) for r in rows}),
        key="planner_calendar_states",
    )
    display = []
    for r in rows:
        status = r.get("delivery", {}).get("state", r["state"])
        if (
            account
            and r["destination"]["key"] not in account
            or states
            and status not in states
        ):
            continue
        when = lib._when(
            r.get("delivery", {}).get("options", r["options"]).get("scheduled_at")
        )
        display.append(
            {
                "Video": r["options"]["title"],
                "Account": r["destination"]["name"],
                "Platform": r["destination"]["platform"],
                "UTC": when.isoformat() if when else tr("After approval"),
                "State": status,
                "Batch": r["batch_id"],
            }
        )
    st.caption(
        tr(
            "Times are shown in UTC. Each account has its own timezone and posting schedule. Open a batch to review or manage a delivery."
        )
    )
    view = st.radio(
        tr("Planner view"),
        [tr("Calendar"), tr("List")],
        horizontal=True,
        key="planner_calendar_view",
    )
    if view == tr("Calendar"):
        week = st.date_input(tr("Week containing"), key="planner_week")
        first = week - timedelta(days=week.weekday())
        for day, col in enumerate(st.columns(7)):
            date = first + timedelta(days=day)
            with col, st.container(border=True):
                st.caption(date.strftime("%a %d %b"))
                for r in display:
                    if r["UTC"].startswith(date.isoformat()):
                        st.link_button(
                            r["UTC"][11:16]
                            + " · "
                            + r["Platform"]
                            + " · "
                            + r["Video"][:35],
                            "?view=publishing&batch=" + r["Batch"],
                        )
                        st.caption(r["State"])
    st.dataframe(
        sorted(display, key=lambda r: r["UTC"]),
        hide_index=True,
        width="stretch",
    )
    if st.button(tr("Refresh planner"), key="planner_calendar_refresh"):
        st.rerun()


def _render_publishing(tr):
    navigation(tr)
    st.title(tr("Publishing"))
    lib.recover()
    lib.discover_automatic()
    tabs = st.tabs(
        [tr("Batches and review"), tr("Calendar / Queue"), tr("Posting schedules")]
    )
    with tabs[0]:
        _batch(tr)
    with tabs[1]:
        _calendar(tr)
    with tabs[2]:
        _presets(tr)


def render_library(tr):
    try:
        _render_library(tr)
    except (ValueError, OSError) as exc:
        _error(exc)


def render_publishing(tr):
    try:
        _render_publishing(tr)
    except (ValueError, OSError) as exc:
        _error(exc)


@st.fragment(run_every=5)
def _preparation_progress(bid, revision, had_review, tr):
    current = lib.batch(bid)
    remaining = sum(i["state"] in {"queued", "preparing"} for i in current["items"])
    st.caption(tr("Posts still preparing") + ": " + str(remaining))
    if not remaining and not had_review and current["revision"] != revision:
        st.rerun(scope="app")
