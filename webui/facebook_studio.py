"""Facebook Pages: hosted connection, destination picker and reviewed delivery."""

from datetime import datetime, timedelta

import streamlit as st

from app.config import config
from app.services import facebook_studio as studio
from app.services.facebook_publisher import publisher
from webui.youtube_studio import _history, _review


def _channels(tr):
    st.subheader(tr("Connected Facebook Pages"))
    st.caption(
        tr(
            "Connect an account you manage, then choose a Facebook Page. Personal profiles are not supported."
        )
    )
    if st.button(tr("Refresh Facebook Pages"), key="fb_refresh_channels"):
        try:
            studio.refresh_channels()
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    cache = studio.cached_channels()
    if cache["checked_at"]:
        st.caption(tr("Last checked") + ": " + cache["checked_at"])
    channels = cache["channels"]
    if channels:
        profile = st.selectbox(
            tr("Publishing profile"),
            [c["profile"] for c in channels],
            format_func=lambda p: next(
                c["profile_label"] for c in channels if c["profile"] == p
            ),
            key="fb_connect_profile",
        )
        account = next(c for c in channels if c["profile"] == profile)
        st.write(account["name"] or tr("Not connected"))
        st.caption(
            tr("Reconnect required")
            if account["reauth_required"]
            else tr("Connected")
            if account["connected"]
            else tr("Not connected")
        )
        for page in account["pages"]:
            st.write(page["name"] + " · " + page["id"])
        if account["selected_page_id"]:
            st.caption(tr("Provider-pinned Page") + ": " + account["selected_page_id"])
        if st.button(tr("Connect / reconnect Facebook"), key="fb_connect"):
            try:
                studio.assert_account_editable(profile)
                st.session_state["fb_connect_link"] = {
                    "profile": profile,
                    "credential": publisher.credential_id,
                    "url": publisher.connect_url(profile),
                }
            except ValueError as exc:
                st.error(str(exc))
        link = st.session_state.get("fb_connect_link", {})
        if (
            link.get("profile") == profile
            and link.get("credential") == publisher.credential_id
        ):
            st.link_button(tr("Continue to Facebook sign-in"), link["url"])
            st.caption(
                tr(
                    "Complete sign-in in the new tab, return here, then refresh Facebook Pages."
                )
            )
        if account["connected"] and not account["pages"]:
            st.info(
                tr(
                    "No available Pages. Check your Page permissions on the provider connection page, then refresh."
                )
            )
        with st.expander(tr("Disconnect Facebook")):
            checked = st.checkbox(
                tr("Disconnect Facebook from this profile"),
                key="fb_disconnect_confirm:" + profile,
            )
            if st.button(
                tr("Disconnect Facebook"), key="fb_disconnect", disabled=not checked
            ):
                try:
                    studio.assert_account_editable(profile)
                    publisher.disconnect(profile)
                    studio.refresh_channels()
                    st.session_state.pop("fb_connect_link", None)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    else:
        st.info(
            tr(
                "Refresh existing profiles or create a publishing profile to connect Facebook."
            )
        )
    with st.expander(tr("Add publishing profile")):
        with st.form("fb_profile_form"):
            name = st.text_input(
                tr("Profile identifier"), max_chars=128, key="fb_profile_name"
            )
            label = st.text_input(
                tr("Profile label"), max_chars=100, key="fb_profile_label"
            )
            create = st.form_submit_button(tr("Create profile"))
        if create:
            try:
                publisher.create_profile(name, label)
                studio.refresh_channels()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _compose(tr):
    st.subheader(tr("Prepare a Facebook post"))
    destinations = [
        {**c, "page": p}
        for c in studio.cached_channels()["channels"]
        if c["connected"] and not c["reauth_required"]
        for p in c["pages"]
        if not c["selected_page_id"] or p["id"] == c["selected_page_id"]
    ]
    videos = studio.completed_videos()
    if not destinations:
        st.info(tr("Connect Facebook and refresh available Pages first."))
        return
    if not videos:
        st.info(tr("Complete a generated video or export a video from OpenCut first."))
        return
    selected = st.selectbox(
        tr("Completed video"),
        range(len(videos)),
        format_func=lambda i: videos[i]["label"],
        key="fb_video",
    )
    source = videos[selected]
    preview, composer = st.columns([1, 2], gap="large")
    with preview:
        st.video(str(studio.source_file(source["task_id"], source["asset"])), width=360)
    with composer:
        chosen = st.selectbox(
            tr("Destination Facebook Page"),
            range(len(destinations)),
            index=None,
            placeholder=tr("Choose a Page"),
            format_func=lambda i: (
                destinations[i]["page"]["name"]
                + " · "
                + destinations[i]["page"]["id"]
                + " · "
                + destinations[i]["profile_label"]
            ),
            key="fb_destination",
        )
        st.caption(
            tr("Facebook Page posts are public. Review your Page before approving.")
        )
        suffix = source["task_id"] + ":" + source["asset"]
        media = st.radio(
            tr("Facebook format"),
            ["VIDEO", "REELS"],
            format_func=lambda v: tr("Page video") if v == "VIDEO" else tr("Reel"),
            key="fb_media:" + suffix,
        )
        if media == "REELS":
            st.caption(
                tr(
                    "Reels: 3–90 seconds, 9:16, at least 540×960 and 24–60 fps. Use Page video for other formats."
                )
            )
        mode = st.radio(
            tr("Delivery time"),
            [tr("Publish after approval"), tr("Schedule")],
            key="fb_mode:" + suffix,
        )
        with st.form("fb_compose_form"):
            title = st.text_input(
                tr("Facebook title"),
                value=source["title"],
                max_chars=100,
                key="fb_title:" + suffix,
            )
            description = st.text_area(
                tr("Facebook description"),
                max_chars=5000,
                key="fb_description:" + suffix,
            )
            synthetic = st.checkbox(
                tr("Label this Reel as AI-generated"),
                value=True,
                key="fb_synthetic:" + suffix,
                disabled=media != "REELS",
            )
            if media == "VIDEO":
                st.caption(
                    tr(
                        "The provider AI-generated label is available for Reels only. Add any needed disclosure to the description for Page videos."
                    )
                )
            date = time = None
            zone = "UTC"
            if mode == tr("Schedule"):
                date = st.date_input(
                    tr("Scheduled date"),
                    value=datetime.now().date() + timedelta(days=1),
                    key="fb_date:" + suffix,
                )
                time = st.time_input(
                    tr("Scheduled time"),
                    value=datetime.min.time().replace(hour=12),
                    key="fb_time:" + suffix,
                )
                zone = st.text_input(
                    tr("Timezone (IANA)"), value="UTC", key="fb_zone:" + suffix
                )
            prepare = st.form_submit_button(tr("Prepare for review"), type="primary")
        if prepare:
            try:
                if chosen is None:
                    raise ValueError(tr("Choose a Page"))
                destination = destinations[chosen]
                schedule = (
                    studio.scheduled_utc(datetime.combine(date, time), zone)
                    if mode == tr("Schedule")
                    else None
                )
                job = studio.prepare(
                    source["task_id"],
                    source["asset"],
                    destination["profile"],
                    destination["page"]["id"],
                    {
                        "title": title,
                        "description": description,
                        "media_type": media,
                        "synthetic": synthetic,
                        "scheduled_at": schedule,
                        "timezone": zone,
                    },
                )
                st.session_state["fb_review_job"] = job["id"]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if st.session_state.get("fb_review_job"):
        _review(
            st.session_state["fb_review_job"], tr, service=studio, platform="facebook"
        )


def render(tr):
    if st.button(tr("Back To Generator"), key="fb_back"):
        st.query_params.clear()
        st.rerun()
    st.title("Facebook Studio")
    st.caption(
        tr(
            "Connect a Facebook Page, review a completed video, then publish or schedule it."
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
        return
    if config.app.get("upload_post_auto_upload"):
        st.warning(
            tr(
                "Legacy automatic cross-posting is enabled. Turn it off in Settings if you want all videos to use this reviewed workflow."
            )
        )
    studio.recover()
    tabs = st.tabs([tr("Pages"), tr("Compose & review"), tr("Delivery history")])
    with tabs[0]:
        _channels(tr)
    with tabs[1]:
        _compose(tr)
    with tabs[2]:
        _history(tr, service=studio, platform="facebook")
