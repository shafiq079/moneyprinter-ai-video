"""Readable settings summaries with optional technical detail."""

import streamlit as st


def render(params, tr):
    value = params.model_dump(mode="json") if hasattr(params, "model_dump") else params
    source = str(value.get("video_source") or "").replace("_", " ").title()
    automatic = value.get("local_ai_duration_mode") == "auto"
    st.table(
        {
            tr("Setting"): [
                tr("Video Source"),
                tr("Aspect ratio"),
                tr("Clip Duration"),
                tr("Voice"),
                tr("Background Music"),
                tr("Subtitles"),
            ],
            tr("Value"): [
                source,
                value.get("video_aspect", "9:16"),
                tr("Automatic Clip Duration")
                if automatic
                else str(value.get("video_clip_duration", 5)) + " s",
                value.get("voice_name") or tr("Upload Voiceover"),
                str(value.get("bgm_type") or tr("None")),
                (
                    str(value.get("font_name") or "")
                    + " · "
                    + str(value.get("font_size", 60))
                    + " · "
                    + str(value.get("text_fore_color", ""))
                )
                if value.get("subtitle_enabled")
                else tr("Disabled"),
            ],
        }
    )
    with st.expander(tr("Advanced production details")):
        st.json(value)
