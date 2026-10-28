"""Campaign planning and production, with existing library/publishing handoffs."""

import json

import streamlit as st
from filelock import Timeout

from app.models.schema import VideoParams
from app.services import campaigns as service, content_library as library
from webui.publishing_planner import navigation


def render(tr):
    navigation(tr)
    st.title(tr("Campaigns"))
    st.caption(
        tr(
            "Plan several videos, approve their scripts, then review the finished videos before publishing."
        )
    )
    try:
        service.recover()
        tabs = st.tabs([tr("Campaign dashboard"), tr("New campaign")])
        with tabs[1]:
            _create(tr)
        with tabs[0]:
            _dashboard(tr)
    except (ValueError, OSError) as exc:
        st.error(
            tr("Campaign is busy. Refresh shortly.")
            if isinstance(exc, Timeout)
            else str(exc)
        )


def _create(tr):
    projects = library.projects()
    templates = ["default"] + [p["task_id"] for p in projects]
    chosen = st.selectbox(
        tr("Generation settings template"),
        templates,
        format_func=lambda tid: (
            tr("Choose video settings below")
            if tid == "default"
            else next(p["title"] + " · " + tid for p in projects if p["task_id"] == tid)
        ),
        key="campaign_template",
    )
    defaults = VideoParams(
        video_subject="Campaign", voice_name="en-US-AriaNeural-Female"
    ).model_dump(mode="json")
    if chosen != "default":
        path = library.media.gm.resolve_asset(chosen, "script.json")
        data = json.loads(path.read_text())
        defaults = service.template(data["params"])
    with st.form("campaign_create"):
        brief = st.text_area(
            tr("Campaign brief"),
            max_chars=4000,
            key="campaign_brief",
            help=tr(
                "Include the niche, audience, target video length, tone and topics to include or avoid."
            ),
        )
        count = st.number_input(
            tr("Number of campaign videos"),
            min_value=1,
            max_value=20,
            value=5,
            key="campaign_count",
        )
        language = st.text_input(
            tr("Campaign language"),
            value=defaults.get("video_language") or "English",
            key="campaign_language:" + chosen,
        )
        sources = ["pexels", "pixabay", "wan22_local", "ltx25_local"]
        source = st.selectbox(
            tr("Campaign video source"),
            sources,
            index=sources.index(defaults.get("video_source"))
            if defaults.get("video_source") in sources
            else 0,
            key="campaign_source:" + chosen,
        )
        voice = st.text_input(
            tr("Narration voice name"),
            value=defaults.get("voice_name") or "en-US-AriaNeural-Female",
            key="campaign_voice:" + chosen,
        )
        if chosen == "default":
            defaults["match_materials_to_script"] = st.checkbox(
                tr("Match video clips to narration automatically"),
                value=True,
                key="campaign_match",
            )
            defaults["subtitle_enabled"] = st.checkbox(
                tr("Enable captions"), value=True, key="campaign_captions"
            )
        settings = defaults | {
            "video_source": source,
            "voice_name": voice,
            "video_language": language,
        }
        targets = library.destinations()
        destinations = st.multiselect(
            tr("Intended publishing accounts"),
            [d["key"] for d in targets],
            format_func=lambda k: next(
                d["platform"].title() + " · " + d["name"]
                for d in targets
                if d["key"] == k
            ),
            key="campaign_destinations",
        )
        st.caption(
            tr(
                "Planning never starts video generation. Source credentials and local AI compute must be configured before production."
            )
        )
        create = st.form_submit_button(tr("Create campaign"))
    if create:
        value = service.create(brief, int(count), language, settings, destinations)
        st.query_params["campaign"] = value["id"]
        st.session_state["campaign_selected"] = value["id"]
        st.rerun()


def _dashboard(tr):
    values = service.all_campaigns()
    if not values:
        st.info(tr("Create a campaign to begin."))
        return
    ids = [v["id"] for v in values]
    wanted = st.query_params.get("campaign")
    if st.session_state.get("campaign_route") != wanted:
        st.session_state["campaign_route"] = wanted
        if wanted in ids:
            st.session_state["campaign_selected"] = wanted
    cid = st.selectbox(
        tr("Campaign"),
        ids,
        index=ids.index(wanted) if wanted in ids else 0,
        format_func=lambda cid: next(
            v["brief"][:70] + " · " + cid[:8] for v in values if v["id"] == cid
        ),
        key="campaign_selected",
    )
    value = service.get(cid)
    st.write(value["brief"])
    with st.expander(tr("Campaign destination accounts")):
        accounts = library.destinations()
        keys = [d["key"] for d in accounts]
        selected = st.multiselect(
            tr("Intended publishing accounts"),
            keys,
            default=[k for k in value["destinations"] if k in keys],
            format_func=lambda k: next(
                d["platform"].title() + " · " + d["name"]
                for d in accounts
                if d["key"] == k
            ),
            key="campaign_accounts:" + cid,
        )
        if st.button(tr("Save campaign accounts"), key="campaign_save_accounts:" + cid):
            service.set_destinations(cid, selected)
            st.rerun()
    st.caption(tr("Campaign language") + ": " + value["language"])
    with st.expander(tr("Production settings")):
        st.json(value["template"])
    if not value["items"] or all(i["state"] == "planned" for i in value["items"]):
        if st.button(tr("Plan topics and scripts with AI"), key="campaign_plan:" + cid):
            with st.spinner(tr("Planning campaign scripts...")):
                service.plan(cid)
            st.rerun()
    if not value["items"]:
        return
    _status(cid, tr)
    iid = st.selectbox(
        tr("Campaign video"),
        [i["id"] for i in value["items"]],
        format_func=lambda iid: next(
            str(n + 1) + " · " + i["title"]
            for n, i in enumerate(value["items"])
            if i["id"] == iid
        ),
        key="campaign_item:" + cid,
    )
    item = next(i for i in value["items"] if i["id"] == iid)
    if item["state"] == "planned":
        with st.form("campaign_edit:" + iid):
            title = st.text_input(
                tr("Video topic"),
                value=item["title"],
                max_chars=100,
                key="campaign_title:" + iid,
            )
            script = st.text_area(
                tr("Video narration script"),
                value=item["script"],
                height=250,
                max_chars=12000,
                key="campaign_script:" + iid,
            )
            submit = st.form_submit_button(tr("Save campaign script"))
        if submit:
            service.edit(cid, iid, title, script, value["revision"])
            st.rerun()
    else:
        st.write(item["title"])
        st.text(item["script"])
        if item["error"]:
            st.error(item["error"])
        if item.get("task_id"):
            st.caption(tr("Generation task") + ": " + item["task_id"])
        if item.get("attempts"):
            with st.expander(tr("Earlier generation attempts")):
                st.json(item["attempts"])
    if all(i["state"] == "planned" for i in value["items"]):
        reviewed = st.checkbox(
            tr(
                "I reviewed every topic, script and generation setting and approve production"
            ),
            key="campaign_review:" + cid + ":" + str(value["revision"]),
        )
        if st.button(
            tr("Approve campaign production"),
            disabled=not reviewed,
            key="campaign_approve:" + cid,
            type="primary",
        ):
            service.approve(cid, reviewed, value["revision"])
            st.rerun()
    else:
        if st.button(
            tr("Resume queued campaign items")
            if value["paused"]
            else tr("Pause new campaign items"),
            key="campaign_pause:" + cid,
        ):
            service.pause(cid, not value["paused"])
            st.rerun()
        if any(i["state"] == "generating" for i in value["items"]):
            if st.button(
                tr("Cancel active generation and pause"), key="campaign_cancel:" + cid
            ):
                service.cancel_active(cid)
                st.rerun()
        if item["state"] == "attention":
            mode = st.radio(
                tr("Recovery method"),
                ["resume", "new"],
                format_func=lambda v: (
                    tr("Resume saved local AI task")
                    if v == "resume"
                    else tr("Start a new attempt; keep earlier files")
                ),
                key="campaign_retry_mode:" + iid,
            )
            checked = st.checkbox(
                tr("I reviewed this failed task and approve this recovery attempt"),
                key="campaign_retry_review:" + iid,
            )
            if st.button(
                tr("Accept retained final after review"),
                disabled=not checked,
                key="campaign_adopt:" + iid,
            ):
                service.adopt_final(cid, iid, checked)
                st.rerun()
            if st.button(
                tr("Retry campaign item"),
                disabled=not checked,
                key="campaign_retry:" + iid,
            ):
                service.retry(cid, iid, checked, mode)
                st.rerun()
        st.link_button(
            tr("Review campaign videos in Content Library"),
            "?view=library&campaign=" + cid,
        )
        st.link_button(tr("Inspect generation tasks"), "?view=tasks")
        timing = st.radio(
            tr("Campaign publishing timing"),
            ["slots", "now"],
            format_func=lambda v: (
                tr("Next available slots")
                if v == "slots"
                else tr("Publish after approval")
            ),
            key="campaign_timing:" + cid,
        )
        st.caption(
            tr(
                "Mark final videos ready in Content Library first. Publishing preparation creates drafts and does not approve uploading."
            )
        )
        if st.button(
            tr("Prepare publishing for ready campaign videos"),
            key="campaign_publish:" + cid,
        ):
            batch = service.prepare_publishing(cid, timing)
            st.query_params.update(view="publishing", batch=batch["id"])
            st.rerun()
        for bid in value["batches"]:
            st.link_button(
                tr("Open campaign publishing batch") + " · " + bid[:8],
                "?view=publishing&batch=" + bid,
            )


@st.fragment(run_every=5)
def _status(cid, tr):
    rows = service.progress(cid)
    st.dataframe(
        [
            {
                "Video": i["title"],
                "State": i["display_state"],
                "Progress": i["progress"],
                "Task": i["task_id"] or "",
                "Destinations": ", ".join(i["delivery_details"]),
            }
            for i in rows
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        tr(
            "Status refreshes automatically. Refresh the campaign to load updated controls."
        )
    )
    if st.button(tr("Refresh campaign"), key="campaign_refresh:" + cid):
        st.rerun(scope="app")
