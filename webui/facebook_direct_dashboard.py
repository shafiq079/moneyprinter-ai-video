"""Facebook panels within MoneyPrinter's shared Social Dashboard."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from app.services import (
    facebook_accounts as accounts,
    facebook_direct as studio,
    youtube_studio as legacy,
)
from app.services.facebook_graph import FacebookPage


def _setup(tr):
    with st.expander(tr("Meta application setup"), expanded=not accounts.configured()):
        st.info(
            tr(
                "Configure one Meta app, then connect your Facebook account and explicitly attach the Pages you want to manage. Upload-Post is not required."
            )
        )
        st.link_button(
            tr("Meta developer applications"), "https://developers.facebook.com/apps/"
        )
        st.caption(
            tr(
                "Enable Facebook Login with Page permissions. Register this exact callback URL. Development mode uses app-role/test accounts; other users can require App Review and business verification."
            )
        )
        saved = accounts.settings()
        with st.form("meta_app_setup"):
            app_id = st.text_input(
                tr("Meta app ID"), value=saved["app_id"], key="meta_app_id"
            )
            secret = st.text_input(
                tr("Meta app secret"),
                type="password",
                key="meta_app_secret",
                help=tr(
                    "Leave blank to keep the saved secret. Credentials are encrypted on this server."
                ),
            )
            callback = st.text_input(
                tr("Facebook callback URL"),
                value=saved["redirect_uri"] or accounts.suggested_callback(),
                key="meta_callback",
            )
            version = st.text_input(
                tr("Meta Graph API version"), value=saved["version"], key="meta_version"
            )
            config_id = st.text_input(
                tr("Facebook Login for Business configuration ID (optional)"),
                value=saved["config_id"],
                key="meta_config_id",
                help=tr(
                    "If using a Business Login configuration, choose a user access token configuration with Page permissions."
                ),
            )
            submit = st.form_submit_button(tr("Save Meta application"))
        if submit:
            try:
                accounts.configure(
                    {
                        "app_id": app_id,
                        "app_secret": secret or saved["app_secret"],
                        "redirect_uri": callback,
                        "version": version,
                        "config_id": config_id,
                    }
                )
                st.session_state.pop("meta_app_secret", None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _accounts(tr):
    _setup(tr)
    if not accounts.configured():
        return
    if st.button(tr("Connect Facebook"), key="meta_connect", type="primary"):
        try:
            st.session_state["meta_connect_url"] = accounts.connect_ticket()
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get("meta_connect_url"):
        st.link_button(
            tr("Continue with Facebook"), st.session_state["meta_connect_url"]
        )
        st.caption(
            tr(
                "Authorize on Facebook, return here, refresh available Pages, then attach the intended Page. Connecting an account alone never approves a post."
            )
        )
    if st.button(tr("Refresh available Facebook Pages"), key="meta_refresh_pages"):
        try:
            for grant in accounts.grants():
                accounts.refresh_pages(grant["id"])
            st.session_state.pop("meta_connect_url", None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    available = [p for p in accounts.available_pages() if p["can_publish"]]
    if available:
        choice = st.selectbox(
            tr("Facebook Page to attach"),
            range(len(available)),
            index=None,
            placeholder=tr("Choose a Page"),
            format_func=lambda i: (
                available[i]["name"] + " · " + available[i]["page_id"]
            ),
            key="meta_attach_page",
        )
        if st.button(
            tr("Attach selected Facebook Page"),
            disabled=choice is None,
            key="meta_attach",
        ):
            try:
                page = available[choice]
                accounts.attach(page["grant_id"], page["page_id"])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    elif accounts.grants():
        st.info(
            tr(
                "No publishable Pages are available. Check Page selection, content creation tasks and app permissions, then reconnect."
            )
        )
    for connection in accounts.connections():
        with st.container(border=True):
            st.write(connection["name"] + " · " + connection["page_id"])
            st.caption(
                tr("Reconnect required")
                if connection["reauth_required"]
                else tr("Connected directly to Meta")
            )
            if st.button(
                tr("Check Facebook Page connection"),
                key="meta_check:" + connection["id"],
            ):
                try:
                    FacebookPage(connection["id"]).verify_page(connection["page_id"])
                    st.success(tr("Facebook Page identity verified."))
                except ValueError as exc:
                    st.error(str(exc))
    for grant in accounts.grants():
        with st.expander(
            tr("Disconnect Facebook account and its Pages") + " · " + grant["user_id"]
        ):
            st.caption(
                tr(
                    "This revokes this Meta app's Facebook access, removes its attached Pages and local delivery history, and retains your local videos. It does not disconnect YouTube."
                )
            )
            confirmed = st.checkbox(
                tr("Revoke Facebook access and remove these Page connections"),
                key="meta_disconnect_check:" + grant["id"],
            )
            if st.button(
                tr("Disconnect Facebook"),
                disabled=not confirmed,
                key="meta_disconnect:" + grant["id"],
            ):
                try:
                    revoked = accounts.disconnect(grant["id"])
                    for key in list(st.session_state):
                        if key.startswith("meta_content:"):
                            st.session_state.pop(key, None)
                    if not revoked:
                        st.warning(
                            tr(
                                "Expired credentials were removed locally. Revocation was not confirmed; remove the app in Facebook Business Integrations settings."
                            )
                        )
                    else:
                        st.success(
                            tr("Facebook access revoked and local connections removed.")
                        )
                    st.session_state.pop("meta_connect_url", None)
                except ValueError as exc:
                    st.error(str(exc))


def _page(tr, key):
    pages = [p for p in accounts.connections() if not p["reauth_required"]]
    if not pages:
        st.info(tr("Connect Facebook and attach a Page in Accounts first."))
        return None
    choice = st.selectbox(
        tr("Destination Facebook Page"),
        [p["id"] for p in pages],
        format_func=lambda cid: next(
            p["name"] + " · " + p["page_id"] for p in pages if p["id"] == cid
        ),
        key=key,
    )
    return next(p for p in pages if p["id"] == choice)


def _time_fields(tr, prefix):
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
    return date, clock, zone


def _when(values):
    return legacy.scheduled_utc(datetime.combine(values[0], values[1]), values[2])


def _compose(tr):
    page = _page(tr, "meta_compose_page")
    if not page:
        return
    videos = legacy.completed_videos()
    if not videos:
        st.info(tr("Complete a generated video or export a video from OpenCut first."))
        return
    choice = st.selectbox(
        tr("Completed video"),
        range(len(videos)),
        format_func=lambda i: videos[i]["label"],
        key="meta_source",
    )
    source = videos[choice]
    preview, form = st.columns([1, 2])
    with preview:
        st.video(str(legacy.source_file(source["task_id"], source["asset"])), width=360)
    with form:
        media = st.radio(
            tr("Facebook format"),
            ["VIDEO", "REELS"],
            format_func=lambda v: tr("Page video") if v == "VIDEO" else tr("Reel"),
            key="meta_media",
        )
        st.caption(
            tr(
                "Published Facebook Page videos are public. WebM exports are converted locally to MP4 before review."
            )
        )
        if media == "REELS":
            st.caption(
                tr(
                    "This app accepts Reels of 4–60 seconds, 9:16, at least 540×960 and 24–60 fps. Use Page video for other formats."
                )
            )
        mode = st.radio(
            tr("Delivery time"),
            [tr("Publish after approval"), tr("Schedule public release")],
            key="meta_mode",
        )
        if mode == tr("Schedule public release"):
            st.caption(
                tr(
                    "This app schedules Facebook publication 15 minutes to seven days ahead. Meta must confirm acceptance."
                )
            )
        suffix = source["task_id"] + source["asset"]
        with st.form("meta_compose"):
            title = st.text_input(
                tr("Facebook title"),
                value=source["title"],
                max_chars=100,
                key="meta_title:" + suffix,
            )
            description = st.text_area(
                tr("Facebook description"),
                max_chars=5000,
                key="meta_description:" + suffix,
            )
            synthetic = st.checkbox(
                tr("Label this Reel as AI-generated"),
                value=True,
                key="meta_synthetic:" + suffix,
                disabled=media != "REELS",
            )
            if media == "VIDEO":
                st.caption(
                    tr(
                        "The provider AI-generated label is available for Reels only. Add any needed disclosure to the description for Page videos."
                    )
                )
            timing = (
                _time_fields(tr, "meta_new:")
                if mode == tr("Schedule public release")
                else None
            )
            submit = st.form_submit_button(tr("Prepare for review"), type="primary")
        if submit:
            try:
                job = studio.prepare(
                    source["task_id"],
                    source["asset"],
                    page["id"],
                    {
                        "title": title,
                        "description": description,
                        "media_type": media,
                        "synthetic": synthetic,
                        "scheduled_at": _when(timing) if timing else None,
                        "timezone": timing[2] if timing else "UTC",
                    },
                )
                st.session_state["meta_review"] = job["id"]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if st.session_state.get("meta_review"):
        _review(st.session_state["meta_review"], tr, "compose:")


def _review(jid, tr, prefix):
    job = studio.get(jid)
    if job["state"] != "draft":
        return
    st.subheader(tr("Review direct Facebook delivery"))
    st.video(str(legacy.snapshot_file(job)), width=360)
    st.write(job["page"]["name"] + " · " + job["page"]["page_id"])
    st.json(job["options"])
    if job["options"]["scheduled_at"]:
        st.write(
            tr("Scheduled time (UTC)")
            + ": "
            + datetime.fromtimestamp(
                job["options"]["scheduled_at"], timezone.utc
            ).isoformat()
        )
    checked = st.checkbox(
        tr("I reviewed this video, Facebook Page and public publishing settings"),
        key="meta_" + prefix + "review:" + jid,
    )
    if st.button(
        tr("Approve direct Facebook delivery"),
        disabled=not checked,
        key="meta_" + prefix + "approve:" + jid,
        type="primary",
    ):
        try:
            studio.approve(jid, checked)
            st.session_state.pop("meta_review", None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _content(tr):
    page = _page(tr, "meta_content_page")
    if not page:
        return
    media = st.radio(
        tr("Facebook content type"), ["VIDEO", "REELS"], key="meta_content_media"
    )
    key = "meta_content:" + page["id"] + ":" + media
    if st.button(tr("Load Facebook Page videos"), key="meta_content_load"):
        try:
            st.session_state[key] = FacebookPage(page["id"]).content(media)
        except ValueError as exc:
            st.error(str(exc))
    data = st.session_state.get(key)
    if not data:
        return
    rows = data["items"]
    if data.get("next") and st.button(tr("Load more videos"), key="meta_more"):
        try:
            more = FacebookPage(page["id"]).content(media, data["next"])
            st.session_state[key] = {
                "items": rows + more["items"],
                "next": more["next"],
            }
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if not rows:
        st.info(tr("Meta returned no videos for this Page and content type."))
        return
    identity = st.selectbox(
        tr("Facebook video"),
        [r["id"] for r in rows],
        format_func=lambda v: next(
            r.get("title") or r.get("description", "")[:60] or v
            for r in rows
            if r["id"] == v
        ),
        key="meta_remote:" + page["id"] + media,
    )
    row = next(r for r in rows if r["id"] == identity)
    st.link_button(tr("Open Facebook post"), "https://www.facebook.com/" + identity)
    st.caption(
        tr(
            "Saves recheck Page ownership and the current video. Meta can restrict editing some published media."
        )
    )
    revision = str(row.get("updated_time") or "")[:128]
    with st.form("meta_edit:" + identity):
        title = st.text_input(
            tr("Facebook title"),
            value=row.get("title") or "Video",
            max_chars=100,
            key="meta_edit_title:" + identity + revision,
        )
        description = st.text_area(
            tr("Facebook description"),
            value=row.get("description", ""),
            max_chars=5000,
            key="meta_edit_description:" + identity + revision,
        )
        checked = st.checkbox(
            tr("I reviewed these changes to the Facebook video"),
            key="meta_edit_check:" + identity,
        )
        save = st.form_submit_button(tr("Save Facebook changes"))
    if save:
        try:
            studio.edit_video(
                page["id"], identity, title, description, checked, revision or None
            )
            st.session_state.pop(key, None)
            st.success(
                tr("Facebook changes saved. Reload Page videos for current values.")
            )
        except ValueError as exc:
            st.error(str(exc))
    with st.expander(tr("Permanently delete Facebook video")):
        st.warning(
            tr(
                "This permanently deletes the remote Facebook video. Your local MoneyPrinter video/project remains."
            )
        )
        confirmation = st.text_input(
            tr("Type the video ID to confirm deletion"),
            placeholder=identity,
            key="meta_delete_text:" + identity,
        )
        if st.button(
            tr("Delete Facebook video"),
            disabled=confirmation != identity,
            key="meta_delete:" + identity,
        ):
            try:
                studio.delete_video(page["id"], identity, confirmation)
                st.session_state.pop(key, None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _queue(tr):
    rows = studio.jobs()
    if not rows:
        st.info(tr("No direct Facebook drafts or deliveries yet."))
        return
    planned = [
        {
            "Video": j["options"]["title"],
            "Page": j["page"]["name"],
            "UTC": datetime.fromtimestamp(
                j["options"]["scheduled_at"], timezone.utc
            ).isoformat(),
            "State": j["state"],
        }
        for j in rows
        if j["options"]["scheduled_at"] and j["state"] in studio.ACTIVE
    ]
    if planned:
        st.dataframe(planned, hide_index=True, use_container_width=True)
    jid = st.selectbox(
        tr("Delivery"),
        [j["id"] for j in rows],
        format_func=lambda v: next(
            j["options"]["title"] + " · " + j["state"] for j in rows if j["id"] == v
        ),
        key="meta_job",
    )
    job = studio.get(jid)
    _review(jid, tr, "history:")
    _status(jid, tr)
    if job.get("video_id") and job["state"] in {
        "scheduled",
        "ready",
        "blocked",
        "unknown",
    }:
        with st.expander(tr("Change Facebook publication time")):
            with st.form("meta_reschedule:" + jid):
                timing = _time_fields(tr, "meta_reschedule:" + jid)
                checked = st.checkbox(
                    tr("I approve the new public publication time"),
                    key="meta_reschedule_check:" + jid,
                )
                submit = st.form_submit_button(tr("Update publication time"))
            if submit:
                try:
                    studio.reschedule(jid, _when(timing), checked)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with st.expander(tr("Delivery details")):
        st.json(job)


@st.fragment(run_every=15)
def _status(jid, tr):
    job = studio.get(jid)
    if (
        job["state"] in {"processing", "scheduled"}
        and time_since(job.get("checked_at", 0)) > 30
    ):
        try:
            job = studio.refresh(jid)
        except ValueError as exc:
            st.caption(str(exc))
    st.info(job.get("message", job["state"]))
    st.write(tr("Live delivery status") + ": " + job["state"])
    st.progress(min(1.0, job.get("offset", 0) / job["size"]))
    if job.get("post_url"):
        st.link_button(tr("Open Facebook post"), job["post_url"])
    if st.button(tr("Refresh delivery status"), key="meta_refresh:" + jid):
        try:
            studio.refresh(jid)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if job["state"] in {"paused", "ready", "unknown", "blocked"}:
        checked = st.checkbox(
            tr("I reviewed this Facebook delivery and approve resuming it"),
            key="meta_resume_check:" + jid,
        )
        if st.button(
            tr("Resume existing delivery"),
            disabled=not checked,
            key="meta_resume:" + jid,
        ):
            try:
                studio.resume(jid, checked)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if job["state"] in studio.ACTIVE | {"draft", "failed"} and job["state"] not in {
        "initiating",
        "uploading",
        "finalizing",
    }:
        checked = st.checkbox(
            tr("Cancel delivery and delete any confirmed unpublished Facebook upload"),
            key="meta_cancel_check:" + jid,
        )
        if st.button(
            tr("Cancel Facebook delivery"),
            disabled=not checked,
            key="meta_cancel:" + jid,
        ):
            try:
                studio.cancel(jid, checked)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def time_since(value):
    return datetime.now(timezone.utc).timestamp() - value


def render_panels(tr):
    try:
        accounts.settings()
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
                    "Existing Upload-Post records remain separate. They are never converted or resent through Meta automatically."
                )
            )
            st.link_button(tr("Legacy Facebook publishing"), "?view=facebook-legacy")
            st.link_button(tr("Legacy YouTube publishing"), "?view=youtube-legacy")
    except ValueError as exc:
        st.error(str(exc))
