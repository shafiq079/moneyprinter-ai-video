"""MoneyPrinter's direct YouTube account/content/publishing dashboard."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from app.config import config
from app.services import (
    youtube_accounts as accounts,
    youtube_direct as studio,
    youtube_studio as legacy,
)
from app.services.youtube_google import GoogleYouTube


def _error(exc):
    st.error(str(exc))


def _setup(tr):
    with st.expander(
        tr("Google application setup"), expanded=not accounts.configured()
    ):
        st.info(
            tr(
                "The operator configures one Google Web application. Channel owners then use Connect YouTube; no Upload-Post account is required."
            )
        )
        st.link_button(
            tr("Google Cloud credentials"),
            "https://console.cloud.google.com/apis/credentials",
        )
        st.caption(
            tr(
                "Enable YouTube Data API v3, configure the consent screen, and register this exact callback URL in your Web application client."
            )
        )
        existing = accounts.settings()
        with st.form("social_google_setup"):
            client = st.text_input(
                tr("Google client ID"),
                value=existing["client_id"],
                key="social_client_id",
            )
            secret = st.text_input(
                tr("Google client secret"),
                type="password",
                help=tr(
                    "Leave blank to keep the saved secret. Credentials are encrypted on this server."
                ),
                key="social_client_secret",
            )
            callback = st.text_input(
                tr("Google callback URL"),
                value=existing["redirect_uri"] or accounts.suggested_callback(),
                placeholder="https://your-host/social/youtube/oauth/callback",
                key="social_callback",
            )
            save = st.form_submit_button(tr("Save Google application"))
        if save:
            try:
                accounts.configure(
                    client, secret or existing["client_secret"], callback
                )
                st.session_state.pop("social_client_secret", None)
                st.success(
                    tr("Google application saved. You can now connect a channel.")
                )
                st.rerun()
            except ValueError as exc:
                _error(exc)
        st.caption(
            tr(
                "External Google apps in Testing may require reconnection after seven days. Production use can require Google verification and YouTube compliance review."
            )
        )


def _accounts(tr):
    _setup(tr)
    if not accounts.configured():
        return
    if st.button(tr("Connect YouTube"), key="social_connect", type="primary"):
        try:
            st.session_state["social_connect_url"] = accounts.connect_ticket()
        except ValueError as exc:
            _error(exc)
    if st.session_state.get("social_connect_url"):
        st.link_button(
            tr("Continue with Google"), st.session_state["social_connect_url"]
        )
        st.caption(
            tr(
                "Google opens in a new tab. Authorize the intended channel, then return and refresh accounts."
            )
        )
    if st.button(tr("Refresh accounts"), key="social_accounts_refresh"):
        st.session_state.pop("social_connect_url", None)
        st.rerun()
    for connection in accounts.connections():
        cid = connection["id"]
        with st.container(border=True):
            st.write(connection["name"])
            st.code(connection["channel_id"], language=None)
            st.caption(
                tr("Reconnect required")
                if connection["reauth_required"]
                else tr("Connected directly to Google")
            )
            if st.button(tr("Check channel connection"), key="social_check:" + cid):
                try:
                    GoogleYouTube(cid).verify_channel(connection["channel_id"])
                    st.success(tr("Channel identity verified."))
                except ValueError as exc:
                    _error(exc)
            with st.expander(tr("Disconnect and remove credentials")):
                st.caption(
                    tr(
                        "Google revocation can affect other channels authorized with the same Google app. They may need reconnection. Uploaded videos are not deleted."
                    )
                )
                agreed = st.checkbox(
                    tr("Revoke Google access and remove this connection"),
                    key="social_disconnect_check:" + cid,
                )
                if st.button(
                    tr("Disconnect channel"),
                    disabled=not agreed,
                    key="social_disconnect:" + cid,
                ):
                    try:
                        accounts.disconnect(cid)
                        st.rerun()
                    except ValueError as exc:
                        _error(exc)


def _select_channel(tr, key):
    channels = [c for c in accounts.connections() if not c["reauth_required"]]
    if not channels:
        st.info(tr("Connect a YouTube channel in Accounts first."))
        return None
    cid = st.selectbox(
        tr("YouTube channel"),
        [c["id"] for c in channels],
        format_func=lambda v: next(
            c["name"] + " · " + c["channel_id"] for c in channels if c["id"] == v
        ),
        key=key,
    )
    return next(c for c in channels if c["id"] == cid)


def _fields(tr, prefix, defaults, schedule=True, remote=False):
    title = st.text_input(
        tr("YouTube title"),
        value=defaults.get("title", ""),
        max_chars=100,
        key=prefix + "title",
    )
    description = st.text_area(
        tr("YouTube description"),
        value=defaults.get("description", ""),
        max_chars=5000,
        key=prefix + "description",
    )
    tags = st.text_input(
        tr("Tags, separated by commas"),
        value=", ".join(defaults.get("tags", [])),
        key=prefix + "tags",
    )
    privacy = st.selectbox(
        tr("Visibility"),
        ["private", "unlisted", "public"],
        index=["private", "unlisted", "public"].index(
            defaults.get("privacy", "private")
        ),
        key=prefix + "privacy",
    )
    category = st.text_input(
        tr("YouTube category ID"),
        value=defaults.get("category", "22"),
        key=prefix + "category",
        help=tr("22 is People & Blogs. Use a YouTube video category ID."),
    )
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
        key=prefix + "audience",
    )
    synthetic = st.checkbox(
        tr("Contains realistic altered or synthetic content"),
        value=defaults.get("synthetic", True),
        key=prefix + "synthetic",
    )
    paid = defaults.get("paid_placement", False)
    if not remote:
        paid = st.checkbox(
            tr("Contains paid product placement"), value=paid, key=prefix + "paid"
        )
    when = None
    zone = "UTC"
    if schedule:
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
        zone = st.text_input(
            tr("Timezone (IANA)"), value="Asia/Karachi", key=prefix + "zone"
        )
        # Conversion is performed on form submission, avoiding errors mid-edit.
        when = (date, clock, zone)
    return {
        "title": title,
        "description": description,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "privacy": privacy,
        "category": category,
        "made_for_kids": audience,
        "synthetic": synthetic,
        "paid_placement": paid,
        "scheduled_at": None,
        "timezone": zone,
    }, when


def _schedule(value, when):
    if when:
        value["scheduled_at"] = legacy.scheduled_utc(
            datetime.combine(when[0], when[1]), when[2]
        )
    return value


def _review(jid, tr, prefix):
    job = studio.get(jid)
    if job["state"] != "draft":
        return
    st.subheader(tr("Review direct YouTube delivery"))
    st.video(str(legacy.snapshot_file(job)), width=360)
    st.write(job["channel"]["name"] + " · " + job["channel"]["channel_id"])
    st.json(job["options"])
    st.caption(
        tr(
            "A scheduled publication goes public at the reviewed UTC time. Uploads begin privately; YouTube controls processing and publication eligibility."
        )
    )
    reviewed = st.checkbox(
        tr("I reviewed this video, destination channel and publishing settings"),
        key=prefix + "review:" + jid,
    )
    if st.button(
        tr("Approve direct YouTube delivery"),
        disabled=not reviewed,
        key=prefix + "approve:" + jid,
        type="primary",
    ):
        try:
            studio.approve(jid, reviewed)
            st.session_state.pop("social_review", None)
            st.rerun()
        except ValueError as exc:
            _error(exc)


def _compose(tr):
    channel = _select_channel(tr, "social_compose_channel")
    if not channel:
        return
    videos = legacy.completed_videos()
    if not videos:
        st.info(tr("Complete a generated video or export a video from OpenCut first."))
        return
    index = st.selectbox(
        tr("Completed video"),
        range(len(videos)),
        format_func=lambda v: videos[v]["label"],
        key="social_source",
    )
    source = videos[index]
    preview, form = st.columns([1, 2])
    with preview:
        st.video(str(legacy.source_file(source["task_id"], source["asset"])), width=360)
    with form:
        mode = st.radio(
            tr("Delivery time"),
            [tr("Publish after approval"), tr("Schedule public release")],
            key="social_delivery_mode",
        )
        suffix = source["task_id"] + source["asset"]
        with st.form("social_compose"):
            value, when = _fields(
                tr,
                "social_new:" + suffix,
                {"title": source["title"]},
                schedule=mode == tr("Schedule public release"),
            )
            prepare = st.form_submit_button(tr("Prepare for review"), type="primary")
        if prepare:
            try:
                job = studio.prepare(
                    source["task_id"],
                    source["asset"],
                    channel["id"],
                    _schedule(value, when),
                )
                st.session_state["social_review"] = job["id"]
                st.rerun()
            except ValueError as exc:
                _error(exc)
    if st.session_state.get("social_review"):
        _review(st.session_state["social_review"], tr, "compose:")


def _content(tr):
    channel = _select_channel(tr, "social_content_channel")
    if not channel:
        return
    cid = channel["id"]
    key = "social_content:" + cid
    if st.button(tr("Load channel videos"), key="social_content_load"):
        try:
            st.session_state[key] = GoogleYouTube(cid).content()
        except ValueError as exc:
            _error(exc)
    data = st.session_state.get(key)
    if not data:
        st.caption(
            tr(
                "Load existing videos directly from YouTube. This does not upload or change anything."
            )
        )
        return
    rows = data["items"]
    if data.get("next") and st.button(
        tr("Load more videos"), key="social_content_more"
    ):
        try:
            more = GoogleYouTube(cid).content(data["next"])
            st.session_state[key] = {
                "items": rows + more["items"],
                "next": more["next"],
            }
            st.rerun()
        except ValueError as exc:
            _error(exc)
    if not rows:
        st.info(tr("No channel videos returned by YouTube."))
        return
    identity = st.selectbox(
        tr("YouTube video"),
        [r["id"] for r in rows],
        format_func=lambda v: next(r["snippet"]["title"] for r in rows if r["id"] == v),
        key="social_remote_video:" + cid,
    )
    row = next(r for r in rows if r["id"] == identity)
    st.link_button(
        tr("Open YouTube video"), "https://www.youtube.com/watch?v=" + identity
    )
    st.write(tr("Visibility") + ": " + row.get("status", {}).get("privacyStatus", ""))
    st.caption(
        tr(
            "YouTube data last loaded in this session. Reload before making changes; saves verify the current channel and video again."
        )
    )
    if row.get("status", {}).get("publishAt"):
        st.write(tr("Scheduled time (UTC)") + ": " + row["status"]["publishAt"])
        st.caption(
            tr(
                "Metadata edits retain an existing private video schedule. Changing visibility can remove that schedule."
            )
        )
    # Video bytes are never fetched/downloaded by this dashboard.
    defaults = {
        "title": row["snippet"]["title"],
        "description": row["snippet"].get("description", ""),
        "tags": row["snippet"].get("tags", []),
        "category": row["snippet"].get("categoryId", "22"),
        "privacy": row["status"]["privacyStatus"],
        "made_for_kids": row["status"].get("selfDeclaredMadeForKids"),
        "synthetic": row["status"].get("containsSyntheticMedia", False),
    }
    with st.form("social_remote_edit:" + identity):
        value, _ = _fields(
            tr,
            "social_edit:" + identity + ":" + str(row.get("etag", ""))[:128] + ":",
            defaults,
            schedule=False,
            remote=True,
        )
        reviewed = st.checkbox(
            tr("I reviewed these changes to the existing YouTube video"),
            key="social_edit_review:" + identity,
        )
        save = st.form_submit_button(tr("Save YouTube changes"))
    if save:
        try:
            studio.edit_video(cid, identity, value, reviewed, etag=row.get("etag"))
            st.session_state.pop(key, None)
            st.success(
                tr(
                    "YouTube changes saved. Reload channel videos to see current values."
                )
            )
        except ValueError as exc:
            _error(exc)
    with st.expander(tr("Custom thumbnail")):
        thumbnail = st.file_uploader(
            tr("JPG or PNG thumbnail, up to 10 MiB"),
            type=["jpg", "jpeg", "png"],
            key="social_thumbnail:" + identity,
        )
        if thumbnail and thumbnail.size <= 10 * 1024 * 1024:
            st.image(thumbnail.getvalue(), width=320)
        confirmed = st.checkbox(
            tr("I reviewed this thumbnail for the selected YouTube video"),
            key="social_thumbnail_review:" + identity,
        )
        if st.button(
            tr("Upload thumbnail"),
            disabled=not (thumbnail and confirmed),
            key="social_thumbnail_save:" + identity,
        ):
            try:
                studio.set_thumbnail(cid, identity, thumbnail.getvalue(), confirmed)
                st.success(tr("Thumbnail submitted to YouTube."))
            except ValueError as exc:
                _error(exc)
    with st.expander(tr("Permanently delete YouTube video")):
        st.warning(
            tr(
                "This deletes the remote YouTube video permanently. The local MoneyPrinter project is retained."
            )
        )
        confirm = st.text_input(
            tr("Type the video ID to confirm deletion"),
            key="social_delete_text:" + identity,
            placeholder=identity,
        )
        if st.button(
            tr("Delete YouTube video"),
            disabled=confirm != identity,
            key="social_delete:" + identity,
        ):
            try:
                studio.delete_video(cid, identity, confirm)
                st.session_state.pop(key, None)
                st.rerun()
            except ValueError as exc:
                _error(exc)


def _queue(tr):
    records = studio.jobs()
    if not records:
        st.info(tr("No direct YouTube drafts or deliveries yet."))
        return
    planned = [
        {
            "Video": j["options"]["title"],
            "Channel": j["channel"]["name"],
            "UTC": j["options"]["scheduled_at"],
            "State": j["state"],
        }
        for j in records
        if j["options"]["scheduled_at"] and j["state"] in studio.ACTIVE
    ]
    if planned:
        st.dataframe(planned, hide_index=True, use_container_width=True)
    jid = st.selectbox(
        tr("Delivery"),
        [j["id"] for j in records],
        format_func=lambda v: next(
            j["options"]["title"] + " · " + j["state"] for j in records if j["id"] == v
        ),
        key="social_job",
    )
    job = studio.get(jid)
    if job["state"] == "draft":
        _review(jid, tr, "history:")
    _status(jid, tr)
    if job["state"] in {"scheduled", "release_pending"} and job.get("video_id"):
        with st.expander(tr("Change publication time")):
            with st.form("social_reschedule:" + jid):
                date = st.date_input(
                    tr("Scheduled date"),
                    value=datetime.now(ZoneInfo("Asia/Karachi")).date()
                    + timedelta(days=1),
                    key="social_reschedule_date:" + jid,
                )
                clock = st.time_input(
                    tr("Scheduled time"), key="social_reschedule_time:" + jid
                )
                zone = st.text_input(
                    tr("Timezone (IANA)"),
                    value="Asia/Karachi",
                    key="social_reschedule_zone:" + jid,
                )
                reviewed = st.checkbox(
                    tr("I approve the new public publication time"),
                    key="social_reschedule_check:" + jid,
                )
                save = st.form_submit_button(tr("Update publication time"))
            if save:
                try:
                    studio.reschedule(
                        jid,
                        legacy.scheduled_utc(datetime.combine(date, clock), zone),
                        reviewed,
                    )
                    st.rerun()
                except ValueError as exc:
                    _error(exc)
    with st.expander(tr("Delivery details")):
        st.json(job)


@st.fragment(run_every=15)
def _status(jid, tr):
    job = studio.get(jid)
    if (
        job["state"] in {"processing", "scheduled"}
        and datetime.now(timezone.utc).timestamp() - job.get("checked_at", 0) > 30
    ):
        try:
            job = studio.refresh(jid)
        except ValueError as exc:
            st.caption(str(exc))
    st.info(job.get("message", job["state"]))
    st.write(tr("Live delivery status") + ": " + job["state"])
    if job.get("size"):
        st.progress(min(1.0, job.get("offset", 0) / job["size"]))
    if job.get("post_url"):
        st.link_button(tr("Open YouTube video"), job["post_url"])
    if st.button(tr("Refresh delivery status"), key="social_refresh:" + jid):
        try:
            studio.refresh(jid)
            st.rerun()
        except ValueError as exc:
            _error(exc)
    if job["state"] in {"paused", "blocked", "release_pending"}:
        reviewed = st.checkbox(
            tr("I reviewed this delivery and approve resuming it"),
            key="social_resume_review:" + jid,
        )
        if st.button(
            tr("Resume existing delivery"),
            disabled=not reviewed,
            key="social_resume:" + jid,
        ):
            try:
                studio.resume(jid, reviewed)
                st.rerun()
            except ValueError as exc:
                _error(exc)
    if job["state"] in studio.ACTIVE | {"draft"} and job["state"] not in {
        "initiating",
        "uploading",
    }:
        checked = st.checkbox(
            tr("Cancel delivery; keep any uploaded video private"),
            key="social_cancel_check:" + jid,
        )
        if st.button(
            tr("Cancel delivery"), disabled=not checked, key="social_cancel:" + jid
        ):
            try:
                studio.cancel(jid)
                st.rerun()
            except ValueError as exc:
                _error(exc)


def render(tr):
    if st.button(tr("Back To Generator"), key="social_back"):
        st.query_params.clear()
        st.rerun()
    st.title(tr("Social Dashboard"))
    route = (
        st.query_params.get("view", "social")
        + ":"
        + st.query_params.get("platform", "")
    )
    if st.session_state.get("social_platform_route") != route:
        st.session_state["social_platform_route"] = route
        st.session_state["social_platform"] = (
            "Facebook"
            if route.startswith("facebook:")
            or st.query_params.get("platform") == "facebook"
            else "YouTube"
        )
    platform = st.radio(
        tr("Social platform"),
        ["YouTube", "Facebook"],
        horizontal=True,
        key="social_platform",
    )
    st.caption(
        tr(
            "YouTube connects directly to Google; Facebook Pages connect directly to Meta. Upload-Post is only used by legacy publishing."
        )
    )
    if config.app.get("upload_post_auto_upload"):
        st.warning(
            tr(
                "Legacy automatic cross-posting is enabled. Turn it off in Settings if you want all videos to use this reviewed workflow."
            )
        )
    if platform == "Facebook":
        from webui.facebook_direct_dashboard import render_panels

        render_panels(tr)
        return
    try:
        accounts.settings()  # Surface a lost encryption key without overwriting records.
        if accounts.configured():
            studio.recover()
        tabs = st.tabs(
            [
                tr("Accounts"),
                tr("Content"),
                tr("Create post"),
                tr("Calendar / Queue"),
                tr("Legacy publishing"),
            ]
        )
        with tabs[0]:
            _accounts(tr)
        with tabs[1]:
            if accounts.configured():
                _content(tr)
        with tabs[2]:
            if accounts.configured():
                _compose(tr)
        with tabs[3]:
            _queue(tr)
        with tabs[4]:
            st.info(
                tr(
                    "Existing Upload-Post records remain separate. They are never converted or resent through Google automatically."
                )
            )
            st.link_button(tr("Legacy YouTube publishing"), "?view=youtube-legacy")
            st.link_button(tr("Legacy Facebook publishing"), "?view=facebook-legacy")
    except ValueError as exc:
        _error(exc)
