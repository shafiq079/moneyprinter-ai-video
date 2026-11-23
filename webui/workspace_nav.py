"""Navigate MoneyPrinter views without reopening the Streamlit session."""

from html import escape

import streamlit as st


def route(view=None, **params):
    current = st.query_params.get("view")
    if not current and not st.query_params.get("editor") and (view or params):
        st.session_state["restore_generator_after_navigation"] = True
    for key in ("editor_task_id", "scene_editor_task_id"):
        st.session_state.pop(key, None)
    if view != "campaign-settings":
        st.session_state.pop("campaign_settings_identity", None)
    st.session_state["settings_dialog_open"] = False
    st.query_params.from_dict(({"view": view} if view else {}) | params)


def button(label, key, view=None, *, primary=False, full_rerun=False, **params):
    pressed = st.button(
        label,
        key=key,
        type="primary" if primary else "secondary",
        on_click=route,
        args=(view,),
        kwargs=params,
    )
    if pressed and full_rerun:
        st.rerun(scope="app")


def anchor(label, url):
    st.html(
        '<a target="_self" class="mpt-same-tab-link" href="'
        + escape(url, quote=True)
        + '">'
        + escape(label)
        + "</a>"
    )


def navigation(tr):
    view = st.query_params.get("view")
    if view in {"youtube", "facebook", "youtube-legacy", "facebook-legacy"}:
        view = "social"
    if view == "campaign-settings":
        view = "campaigns"
    if st.query_params.get("editor"):
        view = "editor"
    with st.container(horizontal=True, gap="small"):
        for target, label in (
            (None, "Create"),
            ("campaigns", "Campaigns"),
            ("library", "Content Library"),
            ("publishing", "Publishing"),
            ("social", "Accounts"),
        ):
            button(tr(label), "workspace_nav:" + label, target, primary=view == target)
