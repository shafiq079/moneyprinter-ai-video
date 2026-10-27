"""YouTube Studio: connect → prepare → review → publish/schedule → track."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from app.config import config
from app.services import youtube_studio as studio
from app.services.youtube_publisher import publisher


def _error(exc):
    st.error(str(exc))


def _channels(tr):
    st.subheader(tr("Connected YouTube channels"))
    st.caption(
        tr(
            "One Upload-Post profile can connect one YouTube channel. Create another profile for another channel."
        )
    )
    if st.button(tr("Refresh channels"), key="yt_refresh_channels"):
        try:
            studio.refresh_channels()
            st.rerun()
        except ValueError as exc:
            _error(exc)
    cache = studio.cached_channels()
    if cache["checked_at"]:
        st.caption(tr("Last checked") + ": " + cache["checked_at"])
    channels = cache["channels"]
    if channels:
        chosen = st.selectbox(
            tr("Publishing profile"),
            [c["profile"] for c in channels],
            format_func=lambda p: next(
                c["profile_label"] for c in channels if c["profile"] == p
            ),
            key="yt_connect_profile",
        )
        channel = next(c for c in channels if c["profile"] == chosen)
        st.write(channel["name"] or tr("No channel connected"))
        if channel["connected"]:
            st.code(channel["channel_id"], language=None)
        st.caption(
            tr("Reconnect required")
            if channel["reauth_required"]
            else tr("Connected")
            if channel["connected"]
            else tr("Not connected")
        )
        if st.button(tr("Connect / reconnect YouTube"), key="yt_connect"):
            try:
                studio.assert_account_editable(chosen)
                st.session_state["yt_connect_link"] = {
                    "profile": chosen,
                    "credential": publisher.credential_id,
                    "url": publisher.connect_url(chosen),
                }
            except ValueError as exc:
                _error(exc)
        link = st.session_state.get("yt_connect_link", {})
        if (
            link.get("profile") == chosen
            and link.get("credential") == publisher.credential_id
        ):
            st.link_button(tr("Continue to YouTube sign-in"), link["url"])
            st.caption(
                tr(
                    "Complete sign-in in the new tab, return here, then refresh channels."
                )
            )
        with st.expander(tr("Disconnect channel")):
            confirmed = st.checkbox(
                tr("Disconnect this YouTube channel from this profile"),
                key="yt_disconnect_confirm",
            )
            if st.button(
                tr("Disconnect channel"), key="yt_disconnect", disabled=not confirmed
            ):
                try:
                    studio.assert_account_editable(chosen)
                    publisher.disconnect(chosen)
                    studio.refresh_channels()
                    st.session_state.pop("yt_connect_link", None)
                    st.rerun()
                except ValueError as exc:
                    _error(exc)
    else:
        st.info(
            tr(
                "Refresh existing profiles or create a publishing profile to connect your channel."
            )
        )
    with st.expander(tr("Add publishing profile")):
        with st.form("yt_profile_form"):
            name = st.text_input(
                tr("Profile identifier"),
                key="yt_profile_name",
                max_chars=128,
                help=tr(
                    "A permanent identifier, for example my_channel. This is not your Google email or channel name."
                ),
            )
            label = st.text_input(
                tr("Profile label"), key="yt_profile_label", max_chars=100
            )
            create = st.form_submit_button(tr("Create profile"))
        if create:
            try:
                publisher.create_profile(name, label)
                studio.refresh_channels()
                st.success(tr("Profile created. Select it above and connect YouTube."))
                st.rerun()
            except ValueError as exc:
                _error(exc)


def _compose(tr):
    st.subheader(tr("Prepare a YouTube post"))
    channels = [
        c
        for c in studio.cached_channels()["channels"]
        if c["connected"] and not c["reauth_required"]
    ]
    videos = studio.completed_videos()
    if not channels:
        st.info(tr("Connect and refresh a YouTube channel first."))
        return
    if not videos:
        st.info(tr("Complete a generated video or export a video from OpenCut first."))
        return
    index = st.selectbox(
        tr("Completed video"),
        range(len(videos)),
        format_func=lambda i: videos[i]["label"],
        key="yt_video",
    )
    source = videos[index]
    preview, composer = st.columns([1, 2], gap="large")
    with preview:
        st.video(str(studio.source_file(source["task_id"], source["asset"])), width=360)
    with composer:
        profile = st.selectbox(
            tr("Destination channel"),
            [c["profile"] for c in channels],
            format_func=lambda p: next(
                f"{c['name']} · {c['profile_label']}"
                for c in channels
                if c["profile"] == p
            ),
            key="yt_destination",
        )
        channel = next(c for c in channels if c["profile"] == profile)
        st.caption(tr("Channel ID") + ": " + channel["channel_id"])
        # Source changes create separate metadata widgets; ordinary reruns retain drafts.
        suffix = source["task_id"] + ":" + source["asset"]
        mode = st.radio(
            tr("Delivery time"),
            [tr("Publish after approval"), tr("Schedule")],
            key="yt_mode:" + suffix,
        )
        with st.form("yt_compose_form"):
            title = st.text_input(
                tr("YouTube title"),
                value=source["title"],
                max_chars=100,
                key="yt_title:" + suffix,
            )
            description = st.text_area(
                tr("YouTube description"),
                max_chars=5000,
                key="yt_description:" + suffix,
            )
            tags = st.text_input(
                tr("Tags, separated by commas"), key="yt_tags:" + suffix
            )
            privacy = st.selectbox(
                tr("Visibility"),
                ["private", "unlisted", "public"],
                key="yt_privacy:" + suffix,
            )
            audience = st.selectbox(
                tr("Audience declaration"),
                [None, False, True],
                format_func=lambda v: (
                    tr("Choose an audience")
                    if v is None
                    else tr("Made for children")
                    if v
                    else tr("Not made for children")
                ),
                key="yt_audience:" + suffix,
            )
            synthetic = st.checkbox(
                tr("Contains realistic altered or synthetic content"),
                value=True,
                key="yt_synthetic:" + suffix,
            )
            paid = st.checkbox(
                tr("Contains paid product placement"), key="yt_paid:" + suffix
            )
            date = time = None
            zone = "UTC"
            if mode == tr("Schedule"):
                date = st.date_input(
                    tr("Scheduled date"),
                    value=datetime.now().date() + timedelta(days=1),
                    key="yt_date:" + suffix,
                )
                time = st.time_input(
                    tr("Scheduled time"),
                    value=datetime.min.time().replace(hour=12),
                    key="yt_time:" + suffix,
                )
                zone = st.text_input(
                    tr("Timezone (IANA)"), value="UTC", key="yt_zone:" + suffix
                )
                st.caption(
                    tr("Date, time and timezone apply only when Schedule is selected.")
                )
            prepare = st.form_submit_button(tr("Prepare for review"), type="primary")
        if prepare:
            try:
                scheduled_at = (
                    studio.scheduled_utc(datetime.combine(date, time), zone)
                    if mode == tr("Schedule")
                    else None
                )
                job = studio.prepare(
                    source["task_id"],
                    source["asset"],
                    profile,
                    {
                        "title": title,
                        "description": description,
                        "tags": [t.strip() for t in tags.split(",") if t.strip()],
                        "privacy": privacy,
                        "made_for_kids": audience,
                        "synthetic": synthetic,
                        "paid_placement": paid,
                        "scheduled_at": scheduled_at,
                        "timezone": zone,
                    },
                )
                st.session_state["yt_review_job"] = job["id"]
                st.rerun()
            except ValueError as exc:
                _error(exc)
    selected = st.session_state.get("yt_review_job")
    if selected:
        _review(selected, tr)


def _review(job_id, tr, prefix="compose"):
    job = studio.get(job_id)
    if job["state"] != "draft":
        st.info(
            tr("This post is already submitted. Its status is in Delivery history.")
        )
        return
    st.divider()
    st.subheader(tr("Review before delivery"))
    st.video(str(studio.snapshot_file(job)), width=360)
    st.write(job["options"]["title"])
    st.write(job["channel"]["name"] + " · " + job["channel"]["channel_id"])
    settings = job["options"]
    st.write(tr("Visibility") + ": " + settings["privacy"])
    st.write(
        tr("Scheduled time (UTC)")
        + ": "
        + (settings["scheduled_at"] or tr("Immediately after approval"))
    )
    st.write(
        tr("Audience declaration")
        + ": "
        + (
            tr("Made for children")
            if settings["made_for_kids"]
            else tr("Not made for children")
        )
    )
    with st.expander(tr("All reviewed settings")):
        st.json(settings)
    reviewed = st.checkbox(
        tr("I reviewed this video, destination channel and publishing settings"),
        key="yt_reviewed:" + prefix + ":" + job_id,
    )
    if st.button(
        tr("Approve schedule")
        if settings["scheduled_at"]
        else tr("Approve YouTube upload"),
        type="primary",
        disabled=not reviewed,
        key="yt_approve:" + prefix + ":" + job_id,
    ):
        try:
            studio.approve(job_id, reviewed=reviewed)
            st.session_state.pop("yt_review_job", None)
            st.success(tr("Delivery approved. Track it in Delivery history."))
            st.rerun()
        except ValueError as exc:
            _error(exc)


def _history(tr):
    st.subheader(tr("Delivery history"))
    rows = studio.jobs()
    if not rows:
        st.info(tr("No publishing drafts or deliveries yet."))
        return
    choice = st.selectbox(
        tr("Post"),
        [r["id"] for r in rows],
        format_func=lambda jid: next(
            f"{r['options']['title']} · {r['state']} · {r['created_at'][:16]}"
            for r in rows
            if r["id"] == jid
        ),
        key="yt_history_post",
    )
    job = studio.get(choice)
    st.write(job["channel"]["name"] + " · " + job["channel"]["channel_id"])
    if job["state"] == "draft":
        _review(choice, tr, prefix="history")
        if st.button(tr("Cancel draft"), key="yt_cancel_draft:" + choice):
            studio.cancel(choice)
            st.rerun()
    if job["state"] != "draft":
        _delivery(choice, tr)
    with st.expander(tr("Delivery details")):
        st.json(
            {
                "source_task": job["task_id"],
                "source_video": job["source"],
                "sha256": job["sha256"],
                "channel_id": job["channel"]["channel_id"],
                "options": job["options"],
                "events": job["events"],
            }
        )


@st.fragment(run_every=10)
def _delivery(choice, tr):
    job = studio.get(choice)
    active = job["state"] in {"processing", "unknown", "scheduled"}
    due = not job["options"]["scheduled_at"] or datetime.fromisoformat(
        job["options"]["scheduled_at"]
    ) <= datetime.now(timezone.utc)
    if active and due:
        checked = datetime.fromisoformat(job.get("checked_at") or job["updated_at"])
        interval = 60 if job["state"] == "unknown" else 10
        if (datetime.now(timezone.utc) - checked).total_seconds() >= interval:
            try:
                job = studio.refresh(choice)
            except ValueError as exc:
                st.caption(str(exc))
    st.write(tr("Live delivery status") + ": " + job["state"])
    st.info(job["message"])
    if job["state"] in {"unknown", "failed", "rejected", "blocked"}:
        st.link_button(
            "Upload-Post",
            "https://app.upload-post.com/",
            key="yt_provider_dashboard:" + choice,
        )
    if job.get("post_url"):
        st.link_button(tr("Open YouTube video"), job["post_url"])
    if (
        job["state"] in studio._ACTIVE | {"failed", "blocked", "rejected"}
        and job["state"] != "queued"
    ):
        if st.button(tr("Refresh delivery status"), key="yt_history_refresh:" + choice):
            try:
                studio.refresh(choice)
                st.rerun()
            except ValueError as exc:
                _error(exc)
    if job["state"] in {"queued", "scheduled"} or (
        job["state"] in {"blocked", "rejected"} and not job.get("submitted_once")
    ):
        if st.button(tr("Cancel delivery"), key="yt_cancel:" + choice):
            try:
                studio.cancel(choice)
                st.rerun()
            except ValueError as exc:
                _error(exc)
    if job["state"] == "failed" or (
        job["state"] in {"blocked", "rejected"} and not job.get("submitted_once")
    ):
        reviewed = st.checkbox(
            tr("I reviewed the channel before retrying this failed delivery"),
            key="yt_retry_review:" + choice,
        )
        if st.button(
            tr("Retry failed delivery"), disabled=not reviewed, key="yt_retry:" + choice
        ):
            try:
                studio.retry(choice, reviewed=reviewed)
                st.rerun()
            except ValueError as exc:
                _error(exc)


def render(tr):
    if st.button(tr("Back To Generator"), key="yt_back"):
        st.query_params.clear()
        st.rerun()
    st.title("YouTube Studio")
    st.caption(
        tr(
            "Connect a channel, review a completed video, then publish or schedule it. TikTok and Instagram are planned for later."
        )
    )
    if not publisher.configured:
        st.info(
            tr(
                "This feature uses the existing Upload-Post provider. Configure its API key and enable the integration in Settings → Auto-Publish."
            )
        )
        st.link_button(
            tr("Upload-Post API keys"), "https://app.upload-post.com/api-keys"
        )
        st.caption(
            tr(
                "YouTube sign-in is completed on the provider connection page. MoneyPrinter does not collect your Google password."
            )
        )
        return
    if config.app.get("upload_post_auto_upload"):
        st.warning(
            tr(
                "Legacy automatic cross-posting is enabled. Turn it off in Settings if you want all videos to use this reviewed workflow."
            )
        )
    studio.recover()
    tabs = st.tabs([tr("Channels"), tr("Compose & review"), tr("Delivery history")])
    with tabs[0]:
        _channels(tr)
    with tabs[1]:
        _compose(tr)
    with tabs[2]:
        _history(tr)
