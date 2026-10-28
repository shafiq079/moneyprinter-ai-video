"""Shared AI preparation inside the existing direct publishing composers."""

import streamlit as st

from app.services import publishing_seo as seo


def render(tr, source, platform, title_key, description_key, tags_key=None):
    task, relative = source["task_id"], source["asset"]
    prefix = "publishing_ai:" + platform + ":" + task + ":" + relative + ":"
    package, thumbnail = None, None
    try:
        package = seo.load(task, relative, platform)
    except (ValueError, OSError):
        pass  # Manual composition remains available if the task lacks a script.
    with st.expander(tr("AI publishing preparation"), expanded=True):
        st.caption(
            tr(
                "Uses your configured LLM and saved script. Accurate titles, descriptions and hashtags help viewers understand the video; ranking is not guaranteed."
            )
        )
        st.caption(
            tr(
                "For edited OpenCut exports, supply an updated summary if the saved script no longer matches the video."
            )
        )
        language = st.text_input(
            tr("Publishing language"),
            value=(package or {}).get("language", "auto"),
            key=prefix + "language",
            help=tr(
                "Use auto for the script language, or enter a language such as English or Urdu."
            ),
        )
        brief = st.text_area(
            tr("Video summary override (optional)"),
            value=(package or {}).get("brief", ""),
            max_chars=12000,
            key=prefix + "brief",
            help=tr(
                "Leave blank to use the saved script. Include only what the finished video actually contains."
            ),
        )
        if st.button(
            tr("Generate AI publishing package"),
            key=prefix + "generate",
            type="primary",
        ):
            try:
                with st.spinner(tr("Preparing publishing copy with AI...")):
                    package = seo.generate(
                        task, relative, platform, language=language, brief=brief
                    )
                _apply(package, title_key, description_key, tags_key)
                st.session_state[prefix + "applied"] = package["id"]
                st.success(
                    tr(
                        "AI copy filled in below. Review it before preparing the delivery."
                    )
                )
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        if not package:
            if st.session_state.get(prefix + "applied"):
                st.warning(
                    tr(
                        "The video or saved script changed. Regenerate AI copy and review any text remaining in the form."
                    )
                )
            st.caption(
                tr(
                    "AI preparation runs only when requested. Reloading this page never calls the model or approves a post."
                )
            )
            return None, None
        metadata = package["metadata"]
        # A fresh session restores the saved AI draft; existing field edits survive reruns.
        if title_key not in st.session_state:
            _apply(package, title_key, description_key, tags_key)
            st.session_state[prefix + "applied"] = package["id"]
        title = st.selectbox(
            tr("Suggested title"),
            metadata["titles"],
            key=prefix + package["id"] + ":title",
        )
        if st.button(tr("Use selected title and AI copy"), key=prefix + "apply"):
            _apply(package, title_key, description_key, tags_key, title)
            st.session_state[prefix + "applied"] = package["id"]
        st.caption(tr("Main topic") + ": " + metadata["focus"])
        st.write(tr("Thumbnail idea") + ": " + metadata["thumbnail_concept"])
        if platform == "youtube":
            text = st.text_input(
                tr("Thumbnail overlay text"),
                value=metadata["thumbnail_text"],
                max_chars=60,
                key=prefix + package["id"] + ":thumbnail_text",
            )
            fonts = seo.thumbnail_fonts()
            font_name = (
                st.selectbox(
                    tr("Thumbnail font"),
                    fonts,
                    index=fonts.index("BeVietnamPro-Bold.ttf")
                    if "BeVietnamPro-Bold.ttf" in fonts
                    else 0,
                    key=prefix + "font",
                )
                if fonts
                else None
            )
            st.caption(
                tr(
                    "Preview the text and choose an installed font that supports your language."
                )
            )
            seconds = st.number_input(
                tr("Thumbnail frame time (seconds)"),
                min_value=0.0,
                max_value=3600.0,
                value=0.0,
                step=0.1,
                key=prefix + "frame",
            )
            if st.button(
                tr("Build thumbnail from video"), key=prefix + "build_thumbnail"
            ):
                try:
                    record = seo.make_thumbnail(
                        task, relative, text, seconds, font_name
                    )
                    package = seo.save_thumbnail(task, relative, package["id"], record)
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
            if package.get("thumbnail"):
                try:
                    st.image(str(seo.thumbnail_file(package["thumbnail"])), width=400)
                    if st.checkbox(
                        tr("Include this thumbnail in the reviewed YouTube delivery"),
                        value=True,
                        key=prefix + "include_thumbnail",
                    ):
                        thumbnail = package["thumbnail"]
                except ValueError as exc:
                    st.error(str(exc))
        else:
            st.caption(
                tr(
                    "Facebook uses the description and hashtags below. Thumbnail ideas are advisory; this uploader does not set a Facebook cover."
                )
            )
    if st.session_state.get(prefix + "applied") != package["id"]:
        return None, thumbnail
    return package, thumbnail


def _apply(package, title_key, description_key, tags_key, title=None):
    data = package["metadata"]
    st.session_state[title_key] = title or data["titles"][0]
    st.session_state[description_key] = data["description"]
    if tags_key:
        st.session_state[tags_key] = ", ".join(data["tags"])
