"""Campaign planning and production, with existing library/publishing handoffs."""

import json

import streamlit as st
from filelock import Timeout

from app.models.schema import VideoParams
from app.services import (
    campaigns as service,
    content_library as library,
    campaign_production as production,
)
from webui.publishing_planner import navigation
from webui import campaign_composer as composer, production_summary


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
    composer.sync()
    projects = library.projects()
    templates = ["default"] + [p["task_id"] for p in projects]
    chosen = st.selectbox(
        tr("Generation settings template"),
        templates,
        index=templates.index(
            st.session_state.get("campaign_template_choice", "default")
        )
        if st.session_state.get("campaign_template_choice", "default") in templates
        else 0,
        format_func={
            "default": tr("Choose video settings below"),
            **{p["task_id"]: p["title"] + " · " + p["task_id"] for p in projects},
        }.get,
        key="campaign_template",
    )
    if chosen != st.session_state.get("campaign_template_choice", "default"):
        st.session_state.pop("campaign_draft_package", None)
    st.session_state["campaign_template_choice"] = chosen
    defaults = VideoParams(
        video_subject="Campaign", voice_name="en-US-AriaNeural-Female"
    ).model_dump(mode="json")
    if chosen != "default":
        path = library.media.gm.resolve_asset(chosen, "script.json")
        data = json.loads(path.read_text())
        try:
            defaults = service.template(data["params"])
        except ValueError as exc:
            st.warning(str(exc))
            st.caption(tr("Re-upload task inputs in shared production settings."))
    package = st.session_state.get("campaign_draft_package")
    if package:
        defaults = package["params"]
    if st.button(
        tr("Configure shared production settings"), key="campaign_configure_new"
    ):
        if not package:
            st.session_state["campaign_draft_package"] = {"params": defaults}
        if "campaign_brief" in st.session_state:
            st.session_state["campaign_new_fields"] = {
                "brief": st.session_state.get("campaign_brief", ""),
                "count": len(composer.rows()),
                "language": st.session_state.get(
                    "campaign_language:" + chosen, "English"
                ),
                "destinations": st.session_state.get("campaign_destinations", []),
            }
        st.query_params.clear()
        st.query_params["view"] = "campaign-settings"
        st.rerun()
    with st.expander(tr("Production settings")):
        production_summary.render(defaults, tr)
    cached = st.session_state.get("campaign_new_fields", {})
    brief = st.text_area(
        tr("Campaign brief"),
        value=cached.get("brief", ""),
        max_chars=4000,
        key="campaign_brief",
        help=tr(
            "Include the niche, audience, target video length, tone and topics to include or avoid."
        ),
    )
    composer.render_count(tr)
    language = st.text_input(
        tr("Campaign language"),
        value=cached.get("language", defaults.get("video_language") or "English"),
        key="campaign_language:" + chosen,
    )
    targets = library.destinations()
    destinations = st.multiselect(
        tr("Intended publishing accounts"),
        [d["key"] for d in targets],
        default=[
            k
            for k in cached.get("destinations", [])
            if k in {d["key"] for d in targets}
        ],
        format_func=lambda k: next(
            d["platform"].title() + " · " + d["name"] for d in targets if d["key"] == k
        ),
        key="campaign_destinations",
    )
    st.session_state["campaign_new_fields"] = {
        "brief": brief,
        "count": len(composer.rows()),
        "language": language,
        "destinations": destinations,
    }
    st.caption(
        tr(
            "Planning never starts video generation. Source credentials and local AI compute must be configured before production."
        )
    )
    cards = composer.render(tr, brief, language, defaults)
    complete = all(row["title"].strip() and row["script"].strip() for row in cards)
    if st.button(tr("Create campaign"), key="campaign_create", disabled=not complete):
        settings = package or defaults
        value = service.create(
            brief, len(cards), language, settings, destinations, items=cards
        )
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
        production_summary.render(value["template"], tr)
    editable = not value["items"] or all(
        i["state"] == "planned" for i in value["items"]
    )
    if editable and st.button(
        tr("Edit shared production settings"), key="campaign_settings:" + cid
    ):
        st.query_params.update(view="campaign-settings", campaign=cid)
        st.query_params.pop("item", None)
        st.rerun()
    if not value["items"]:
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
    package, effective_params = service.effective(value, item)
    with st.expander(tr("Effective video production settings")):
        st.caption(
            tr("Per-video override")
            if item.get("production")
            else tr("Inherits shared settings")
        )
        production_summary.render(effective_params, tr)
        if package.get("quote", {}).get("summary"):
            st.json(package["quote"]["summary"])
    if item["state"] == "planned":
        if st.button(
            tr("Edit this video production settings"),
            key="campaign_item_settings:" + iid,
        ):
            st.query_params.update(view="campaign-settings", campaign=cid, item=iid)
            st.rerun()
        if item.get("production") and st.button(
            tr("Reset to shared settings"), key="campaign_reset_settings:" + iid
        ):
            service.set_settings(cid, None, value["revision"], iid)
            st.rerun()
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
            keywords = st.text_area(
                tr("Visual keywords"),
                value=", ".join(
                    service.content.keywords(
                        item.get("keywords", effective_params.video_terms)
                    )
                ),
                key="campaign_keywords:" + iid,
                max_chars=5000,
            )
            submit = st.form_submit_button(tr("Save campaign script"))
        if submit:
            service.edit(cid, iid, title, script, value["revision"], keywords=keywords)
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
        effective_rows = [service.effective(value, i)[1] for i in value["items"]]
        with st.expander(tr("Review all video settings")):
            for i, params in zip(value["items"], effective_rows, strict=True):
                st.write(i["title"])
                production_summary.render(params, tr)
                quote = service.effective(value, i)[0].get("quote", {})
                if quote.get("summary"):
                    st.json(quote["summary"])
        paid = any(production.requires_charge(params) for params in effective_rows)
        charges_reviewed = (
            st.checkbox(
                tr("I approve paid provider charges for all listed campaign videos"),
                key="campaign_charges:" + cid + ":" + str(value["revision"]),
            )
            if paid
            else False
        )
        reviewed = st.checkbox(
            tr(
                "I reviewed every topic, script and generation setting and approve production"
            ),
            key="campaign_review:" + cid + ":" + str(value["revision"]),
        )
        if st.button(
            tr("Approve campaign production"),
            disabled=not reviewed or (paid and not charges_reviewed),
            key="campaign_approve:" + cid,
            type="primary",
        ):
            service.approve(
                cid, reviewed, value["revision"], charges_reviewed=charges_reviewed
            )
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
