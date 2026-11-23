"""Instagram and TikTok on the same Accounts page as existing destinations."""

import streamlit as st

from app.services import content_library as library, facebook_accounts as meta
from app.services import short_video_direct, tiktok_accounts, youtube_studio as media
from webui.workspace_nav import anchor, button as navigate


def _instagram_accounts(tr):
    from webui.facebook_direct_dashboard import _setup

    st.caption(
        "Connect an Instagram professional account linked to a Facebook Page. Use a Facebook Login for Business configuration with the Instagram publishing permissions."
    )
    _setup(tr)
    if not meta.configured():
        return
    if st.button("Connect Meta for Instagram", key="connect_instagram", type="primary"):
        st.session_state["instagram_connect_url"] = meta.connect_ticket(instagram=True)
    if st.query_params.get("instagram_connected") == "1":
        st.session_state.pop("instagram_connect_url", None)
        st.query_params.pop("instagram_connected", None)
    if url := st.session_state.get("instagram_connect_url"):
        anchor("Continue with Meta", url)
    available = meta.instagram_available()
    if not available:
        st.info("Authorize Meta, then attach the Instagram account offered here.")
        return
    choice = st.selectbox(
        "Instagram account to attach",
        range(len(available)),
        index=None,
        format_func=lambda i: "@" + available[i]["name"],
    )
    if st.button("Attach Instagram account", disabled=choice is None):
        account = available[choice]
        meta.attach_instagram(account["grant_id"], account["page_id"], account["id"])
        st.rerun()


def _tiktok_accounts():
    st.caption(
        "Connect TikTok to upload approved videos to your creator inbox. You finish the caption, disclosures, visibility and posting in TikTok."
    )
    saved = tiktok_accounts.settings()
    with st.expander(
        "TikTok application setup", expanded=not tiktok_accounts.configured()
    ):
        st.caption(
            "Enable Login Kit for Web and Content Posting API Upload. Register this exact HTTPS callback and request user.info.basic and video.upload."
        )
        with st.form("tiktok_app_setup"):
            key = st.text_input("TikTok client key", value=saved["client_key"])
            secret = st.text_input(
                "TikTok client secret", type="password", key="tiktok_setup_secret"
            )
            callback = st.text_input(
                "TikTok callback URL",
                value=saved["redirect_uri"] or tiktok_accounts.suggested_callback(),
            )
            submit = st.form_submit_button("Save TikTok application")
        if submit:
            tiktok_accounts.configure(key, secret or saved["client_secret"], callback)
            st.rerun()
    if not tiktok_accounts.configured():
        return
    if st.button("Connect TikTok", key="connect_tiktok", type="primary"):
        st.session_state["tiktok_connect_url"] = tiktok_accounts.connect_ticket()
    if st.query_params.get("tiktok_connected") == "1":
        st.session_state.pop("tiktok_connect_url", None)
        st.query_params.pop("tiktok_connected", None)
    if url := st.session_state.get("tiktok_connect_url"):
        anchor("Continue with TikTok", url)


def _accounts(platform, tr):
    if platform == "instagram":
        _instagram_accounts(tr)
        records = meta.instagram_connections()
    else:
        _tiktok_accounts()
        records = tiktok_accounts.connections()
    for account in records:
        with st.container(border=True):
            st.write(account["name"])
            st.caption(
                "Reconnect required" if account["reauth_required"] else "Connected"
            )
            if platform == "instagram":
                st.caption("Manage the shared Meta authorization in Facebook Accounts.")
                if not account.get("detached") and st.button(
                    "Detach Instagram", key="instagram_detach:" + account["id"]
                ):
                    meta.detach_instagram(account["id"])
                    st.rerun()
            else:
                review = st.checkbox(
                    "Confirm disconnect", key="tiktok_revoke_review:" + account["id"]
                )
                if st.button(
                    "Disconnect TikTok",
                    disabled=not review,
                    key="tiktok_revoke:" + account["id"],
                ):
                    tiktok_accounts.disconnect(account["id"])
                    st.rerun()


def _compose(platform, studio, tr):
    accounts = [a for a in library.destinations() if a["platform"] == platform]
    projects = [p for p in library.projects() if p["ready"]]
    if not accounts:
        st.info("Connect an account first.")
        return
    if not projects:
        st.info("Review and save a final video in Content Library first.")
        navigate(tr("Content Library"), "short_to_library", "library")
        return
    videos = {p["task_id"]: p for p in projects}
    preferred = st.query_params.get("task")
    tid = st.selectbox(
        "Final video",
        list(videos),
        index=list(videos).index(preferred) if preferred in videos else 0,
        format_func=lambda key: videos[key]["title"],
        key="short_video:" + platform,
    )
    labels = {a["connection_id"]: a["name"] for a in accounts}
    cid = st.selectbox(
        "Destination account",
        list(labels),
        format_func=labels.get,
        key="short_destination:" + platform,
    )
    video = videos[tid]
    with st.form("short_prepare:" + platform):
        caption = st.text_area(
            "Caption" if platform == "instagram" else "Caption notes to copy in TikTok",
            max_chars=2200,
        )
        synthetic = platform == "instagram" and st.checkbox(
            "Disclose AI-generated content", value=True
        )
        submitted = st.form_submit_button("Prepare for review", type="primary")
    if submitted:
        job = studio.prepare(
            tid,
            video["source"],
            cid,
            dict(
                title=video["title"][:100].replace("\n", " "),
                description=caption,
                synthetic=synthetic,
            ),
        )
        st.session_state["short_review:" + platform] = job["id"]
        st.rerun()
    if jid := st.session_state.get("short_review:" + platform):
        try:
            job = studio.get(jid)
        except ValueError:
            st.session_state.pop("short_review:" + platform, None)
        else:
            if job["state"] == "draft":
                _review(platform, studio, job)


def _review(platform, studio, job, *, placement="compose"):
    jid = job["id"]
    st.subheader("Review delivery")
    st.caption(job["account_name"] + " · " + job["identity"])
    st.video(str(media.snapshot_file(job)), width=220)
    if job["options"]["description"]:
        st.write(job["options"]["description"])
    if platform == "instagram":
        st.caption(
            "AI content disclosure: " + ("On" if job["options"]["synthetic"] else "Off")
        )
        action = "Approve Instagram Reel"
    else:
        st.caption(
            "The video goes to the TikTok inbox. Caption notes are kept here for copying."
        )
        action = "Approve TikTok inbox upload"
    reviewed = st.checkbox(
        "I reviewed this video and destination account",
        key=f"short_review:{placement}:{jid}",
    )
    if st.button(
        action,
        disabled=not reviewed,
        key=f"short_approve:{placement}:{jid}",
        type="primary",
    ):
        studio.approve(jid, reviewed)
        st.rerun()


def _queue(platform, studio):
    jobs = studio.jobs()
    if not jobs:
        st.info("No deliveries for this platform.")
        return
    selected = st.selectbox(
        "Delivery",
        [j["id"] for j in jobs],
        format_func=lambda jid: next(
            f"{j['options']['title']} · {j['account_name']} · {j['state'].title()}"
            for j in jobs
            if j["id"] == jid
        ),
        key="short_queue:" + platform,
    )
    job = studio.get(selected)
    st.caption(job["message"])
    if job["state"] == "draft":
        _review(platform, studio, job, placement="queue")
    if (
        platform == "tiktok"
        and job["state"] == "inbox"
        and job["options"]["description"]
    ):
        st.code(job["options"]["description"], language=None)
    if st.button("Refresh delivery status", key="short_refresh:" + selected):
        studio.refresh(selected)
        st.rerun()
    can_resume = job["state"] == "blocked" or (
        platform == "tiktok" and job["state"] == "paused"
    )
    if can_resume or job["state"] in {"draft", "queued"}:
        confirmed = st.checkbox(
            "Confirm delivery action", key="short_action_review:" + selected
        )
        if can_resume and st.button("Resume delivery", disabled=not confirmed):
            studio.resume(selected, confirmed)
            st.rerun()
        if job["state"] in {"draft", "queued"} and st.button(
            "Cancel delivery", disabled=not confirmed
        ):
            studio.cancel(selected, confirmed)
            st.rerun()


def render(platform, tr):
    studio = getattr(short_video_direct, platform)
    try:
        studio.recover()
        sections = {
            "accounts": tr("Accounts"),
            "compose": tr("Create post"),
            "queue": tr("Calendar / Queue"),
        }
        current = st.query_params.get("section", "accounts")
        section = st.radio(
            "Platform tools",
            list(sections),
            format_func=sections.get,
            index=list(sections).index(current) if current in sections else 0,
            horizontal=True,
            key=f"short_section:{platform}:{current}",
        )
        if section == "accounts":
            _accounts(platform, tr)
        elif section == "compose":
            _compose(platform, studio, tr)
        else:
            _queue(platform, studio)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
