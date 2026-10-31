"""Browser-session video cards before a campaign is committed."""

import copy
import uuid

import streamlit as st
from app.services import campaign_content as content

STATE = "campaign_content_cards"


def blank():
    return {"id": uuid.uuid4().hex, "title": "", "script": "", "keywords": []}


def rows():
    if STATE not in st.session_state:
        st.session_state[STATE] = [blank()]
        st.session_state["campaign_count"] = 1
    return st.session_state[STATE]


def key(row, field):
    return "campaign_card_" + field + ":" + row["id"]


def sync():
    for row in rows():
        for field in ("title", "script", "keywords"):
            if key(row, field) in st.session_state:
                row[field] = st.session_state[key(row, field)]
    return rows()


def populated(row):
    return any(
        value.strip() if isinstance(value, str) else bool(value)
        for field, value in row.items()
        if field != "id"
    )


def add():
    values = sync()
    if len(values) < 20:
        values.append(blank())
    st.session_state["campaign_count"] = len(values)
    st.session_state.pop("campaign_pending_resize", None)


def resize():
    values = sync()
    count = int(st.session_state["campaign_count"])
    if count < len(values) and any(populated(row) for row in values[count:]):
        st.session_state["campaign_pending_resize"] = count
        st.session_state["campaign_count"] = len(values)
        return
    st.session_state[STATE] = values[:count] + [
        blank() for _ in range(max(0, count - len(values)))
    ]
    st.session_state.pop("campaign_pending_resize", None)


def confirm_resize():
    values = sync()
    count = st.session_state.get("campaign_pending_resize")
    if count is not None and st.session_state.get("campaign_confirm_resize"):
        st.session_state[STATE] = values[:count]
        st.session_state["campaign_count"] = count
        st.session_state.pop("campaign_pending_resize", None)
        st.session_state.pop("campaign_confirm_resize", None)


def remove(sid):
    values = sync()
    row = next(row for row in values if row["id"] == sid)
    if len(values) > 1 and (
        not populated(row) or st.session_state.get("campaign_confirm_remove:" + sid)
    ):
        st.session_state[STATE] = [row for row in values if row["id"] != sid]
        st.session_state["campaign_count"] = len(values) - 1
        st.session_state.pop("campaign_pending_resize", None)


def _generate(tr, brief, language, settings, *, replace=False, selected=None):
    before = copy.deepcopy(sync())
    try:
        with st.spinner(tr("Generating video scripts and keywords...")):
            generated = content.generate(
                brief, language, settings, before, replace=replace, selected=selected
            )
        if content.fingerprint(sync()) != content.fingerprint(before):
            raise ValueError(
                "Video cards changed during AI generation. Your latest edits were retained; generate again."
            )
        # Callers place AI actions before the corresponding input widgets. No
        # widget is mutated after it was instantiated in this run.
        by_id = {row["id"]: row for row in generated}
        originals = {row["id"]: row for row in before}
        for row in rows():
            if selected is not None and row["id"] not in selected:
                continue
            changed = by_id[row["id"]]
            for field in ("title", "script", "keywords"):
                old = originals[row["id"]][field]
                authorized = (
                    replace or not old or (isinstance(old, str) and not old.strip())
                )
                if authorized and row[field] != changed[field]:
                    row[field] = changed[field]
                    st.session_state[key(row, field)] = (
                        ", ".join(changed[field])
                        if field == "keywords"
                        else changed[field]
                    )
    except (ValueError, OSError) as exc:
        st.error(str(exc))


def render_count(tr):
    sync()
    st.number_input(
        tr("Number of campaign videos"),
        min_value=1,
        max_value=20,
        value=len(rows()),
        key="campaign_count",
        on_change=resize,
    )
    pending = st.session_state.get("campaign_pending_resize")
    if pending is not None:
        st.warning(
            tr(
                "Reducing the count would remove video content. Confirm before removing it."
            )
        )
        confirmed = st.checkbox(
            tr("I approve removing the last video cards"), key="campaign_confirm_resize"
        )
        st.button(
            tr("Confirm video count"),
            disabled=not confirmed,
            on_click=confirm_resize,
            key="campaign_apply_count",
        )


def render(tr, brief, language, settings):
    sync()
    st.subheader(tr("Video scripts and keywords"))
    st.caption(
        tr(
            "Each card belongs to one video. Keywords guide visual searches; they are not publishing tags. Empty keywords use automatic per-video search terms."
        )
    )
    mode = st.radio(
        tr("AI content update mode"),
        ["empty", "replace"],
        key="campaign_ai_mode",
        format_func={
            "empty": tr("Fill empty fields only"),
            "replace": tr("Replace all video content"),
        }.get,
        horizontal=True,
    )
    consent = (
        st.checkbox(
            tr("I approve replacing existing content in all video cards"),
            key="campaign_ai_replace_confirm",
        )
        if mode == "replace"
        else False
    )
    if st.button(
        tr("Generate all scripts and keywords with AI"),
        key="campaign_generate_all",
        disabled=mode == "replace" and not consent,
    ):
        _generate(tr, brief, language, settings, replace=mode == "replace")
    for index, row in enumerate(rows()):
        with st.container(border=True):
            st.markdown("**" + tr("Video") + " " + str(index + 1) + "**")
            actions = st.columns(2)
            if actions[0].button(
                tr("Generate with AI"), key="campaign_card_generate:" + row["id"]
            ):
                _generate(tr, brief, language, settings, selected=[row["id"]])
            replace = actions[1].checkbox(
                tr("Replace this video content"),
                key="campaign_card_replace:" + row["id"],
            )
            if actions[1].button(
                tr("Regenerate this video"),
                disabled=not replace,
                key="campaign_card_regenerate:" + row["id"],
            ):
                _generate(
                    tr, brief, language, settings, selected=[row["id"]], replace=True
                )
            row["title"] = st.text_input(
                tr("Video subject"),
                value=row["title"],
                max_chars=100,
                key=key(row, "title"),
            )
            with st.expander(
                tr("Script and visual keywords"), expanded=len(rows()) == 1
            ):
                row["script"] = st.text_area(
                    tr("Video narration script"),
                    value=row["script"],
                    height=200,
                    max_chars=12000,
                    key=key(row, "script"),
                )
                terms = (
                    row["keywords"]
                    if isinstance(row["keywords"], str)
                    else ", ".join(row["keywords"])
                )
                row["keywords"] = st.text_area(
                    tr("Visual keywords"),
                    value=terms,
                    max_chars=5000,
                    key=key(row, "keywords"),
                )
            confirm = (
                st.checkbox(
                    tr("Confirm removing this video content"),
                    key="campaign_confirm_remove:" + row["id"],
                )
                if populated(row) and len(rows()) > 1
                else False
            )
            st.button(
                tr("Remove video"),
                key="campaign_card_remove:" + row["id"],
                on_click=remove,
                args=(row["id"],),
                disabled=len(rows()) == 1 or (populated(row) and not confirm),
            )
    st.button(
        tr("+ Add video"),
        key="campaign_add_video",
        on_click=add,
        disabled=len(rows()) >= 20,
    )
    return sync()
