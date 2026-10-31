"""Full-page campaign settings using the actual single-video controls."""

import copy
from io import BytesIO

from app.config import config

import streamlit as st

from app.models.schema import VideoParams
from app.services import campaigns as service, campaign_production as production


class RetainedUpload(BytesIO):
    def __init__(self, filename):
        super().__init__(filename.read_bytes())
        self.name = filename.name


def render(
    tr,
    *,
    apply_params,
    script_panel,
    video_panel,
    audio_panel,
    subtitle_panel,
    controls,
    settings_dialog,
):
    cid = st.query_params.get("campaign")
    iid = st.query_params.get("item")
    value = service.get(cid) if cid else None
    if value and any(i["state"] != "planned" for i in value["items"]):
        st.error(tr("Production settings are locked after approval."))
        return
    item = (
        next((i for i in value["items"] if i["id"] == iid), None)
        if value and iid
        else None
    )
    if iid and item is None:
        st.error(tr("Campaign video is unavailable."))
        return
    package, params = (
        service.effective(value, item)
        if value
        else (st.session_state.get("campaign_draft_package", {}), None)
    )
    if params is None:
        params = VideoParams.model_validate(
            package.get("params")
            or {
                "video_subject": "Campaign video",
                "voice_name": "en-US-AriaNeural-Female",
            }
        )
    params.video_count = 1
    if not item:
        params.video_subject = "Campaign video"
        params.video_script = ""
    identity = (
        cid,
        iid,
        value["revision"]
        if value
        else st.session_state.get("campaign_draft_revision", 0),
    )
    if st.session_state.get("campaign_settings_identity") != identity:
        if "campaign_generator_backup" not in st.session_state:
            fallback = VideoParams(
                video_subject="",
                voice_name=config.ui.get("voice_name") or "en-US-AriaNeural-Female",
            ).model_dump(mode="json")
            fallback.update(
                {k: v for k, v in config.ui.items() if k in VideoParams.model_fields}
            )
            fallback["video_source"] = config.app.get("video_source", "pexels")
            st.session_state["campaign_generator_backup"] = copy.deepcopy(
                st.session_state.get("generator_last_params") or fallback
            )
            lang = st.session_state.get("ui_language", "en")
            st.session_state["campaign_generator_widget_backup"] = {
                "video_encoder_select_" + lang: config.app.get(
                    "video_codec", "__default__"
                ),
                "elevenlabs_model_select_" + lang: config.elevenlabs.get("model_id"),
                "fish_audio_model_select_" + lang: config.fish_audio.get("model"),
                "minimax_tts_model_select_" + lang: config.minimax_tts.get("model_id"),
                "voxcpm_model_id_input": config.voxcpm.get("model_id"),
                "kokoro_model_input": config.kokoro.get("model_id"),
                "chatterbox_model_input": config.chatterbox.get("model_id"),
            }
        apply_params(params.model_dump(mode="json"))
        st.session_state["campaign_runtime_draft"] = copy.deepcopy(
            package.get("runtime", {})
        )
        model_widgets = {
            "elevenlabs": "elevenlabs_model_select",
            "fish_audio": "fish_audio_model_select",
            "minimax_tts": "minimax_tts_model_select",
            "voxcpm": "voxcpm_model_id_input",
            "kokoro": "kokoro_model_input",
            "chatterbox": "chatterbox_model_input",
        }
        lang = st.session_state.get("ui_language", "en")
        for section, widget in model_widgets.items():
            values = package.get("runtime", {}).get(section, {})
            chosen = values.get("model_id", values.get("model"))
            if chosen is not None:
                st.session_state[
                    widget + "_" + lang if widget.endswith("_select") else widget
                ] = chosen
            else:
                st.session_state.pop(
                    widget + "_" + lang if widget.endswith("_select") else widget, None
                )
        codec = package.get("runtime", {}).get("app", {}).get("video_codec")
        if codec:
            st.session_state["video_encoder_select_" + lang] = codec
        st.session_state["campaign_settings_identity"] = identity
        st.session_state["campaign_retained_reference"] = None
        st.session_state["campaign_retained_prompt"] = None
        # Upload widgets cannot be programmatically populated. Retained files are
        # checked and explicitly reused until the operator supplies replacements.
        if params.video_materials:
            st.session_state["local_video_materials"] = [
                m.model_dump(mode="json") for m in params.video_materials
            ]
        if package.get("inputs", {}).get("reference"):
            content = production.asset(package["inputs"]["reference"]).read_bytes()
            st.session_state["campaign_retained_reference"] = content
            st.session_state["voxcpm_reference_audio"] = {
                "audio_bytes": content,
                "audio_digest": package["inputs"]["reference"]["sha256"],
                "upload_digest": "retained",
            }
        if package.get("inputs", {}).get("prompt"):
            content = production.asset(package["inputs"]["prompt"]).read_bytes()
            st.session_state["campaign_retained_prompt"] = content
            st.session_state["voxcpm_prompt_audio"] = {
                "audio_bytes": content,
                "audio_digest": package["inputs"]["prompt"]["sha256"],
                "upload_digest": "retained",
            }
            st.session_state["voxcpm_prompt_text_input"] = package.get(
                "prompt_text", ""
            )
            st.session_state["voxcpm_high_fidelity_enabled"] = bool(
                package.get("prompt_text")
            )
            st.session_state["voxcpm_separate_prompt_audio_enabled"] = True
            st.session_state["voxcpm_prompt_example_mode"] = True
        for quote_key, empty in {
            "loomloom_video_batch": None,
            "loomloom_video_quote": None,
            "loomloom_video_input_signature": "",
            "loomloom_video_client_request_id": "",
        }.items():
            st.session_state[quote_key] = empty
        for name in (
            "wavespeed",
            "volcengine_seedance",
            "ofox",
            "metaso_minimax",
            "muapi",
            "loomloom_video",
        ):
            st.session_state[name + "_confirm_charge"] = False
    st.title(tr("Campaign production settings"))
    st.caption(
        tr(
            "These are the same controls as the single-video generator. Saving settings does not generate videos."
        )
    )
    st.info(
        tr(
            "Shared settings apply to inherited videos. Per-video overrides remain independent. Campaign count controls the number of outputs."
        )
    )
    if not item:
        st.caption(
            tr(
                "Shared topic and script fields are examples only. Campaign planning creates the individual scripts using your language and script instructions."
            )
        )
    if st.button(tr("Back to campaign"), key="campaign_settings_back"):
        back(cid)
    if st.session_state.get("settings_dialog_open"):
        settings_dialog()
    if package.get("inputs"):
        st.caption(
            tr("Saved uploads are retained. Upload a replacement to change them.")
        )
    panels = st.tabs(
        [
            tr("Video Script Settings"),
            tr("Video Settings"),
            tr("Audio Settings"),
            tr("Subtitle Settings"),
        ]
    )
    # Uploaded paths are reattached only for the currently selected modes. A
    # switch back to TTS/stock must not silently retain an old recording/footage.
    params.custom_audio_file = None
    params.video_materials = None
    params.bgm_file = ""
    script_panel(panels[0], params)
    videos = video_panel(panels[1], params)
    audio, music, mode = audio_panel(panels[2], params)
    subtitle_panel(panels[3], params)
    # Preserve durable input references across a simple settings-only edit.
    if mode == "upload" and audio is None and package.get("inputs", {}).get("audio"):
        audio = RetainedUpload(production.asset(package["inputs"]["audio"]))
    if (
        params.video_source == "local"
        and not videos
        and package.get("params", {}).get("video_materials")
    ):
        for record in package.get("inputs", {}).get("materials", []):
            production.asset(record)
    params.video_count = 1

    def save(staging_task, prepared, **kwargs):
        if value and not prepared.video_language:
            prepared.video_language = value["language"]
        captured = production.capture(prepared, staging_task, **kwargs)
        for section, values in st.session_state.get(
            "campaign_runtime_draft", {}
        ).items():
            captured["runtime"].setdefault(section, {}).update(values)
        if cid:
            service.set_settings(cid, captured, value["revision"], iid)
        else:
            captured["params"] = service.template(captured["params"], retained=True)
            captured.pop("quote", None)
            st.session_state["campaign_draft_package"] = captured
            st.session_state["campaign_draft_revision"] = (
                st.session_state.get("campaign_draft_revision", 0) + 1
            )
        back(cid)

    try:
        controls(
            params,
            videos,
            audio,
            music,
            mode,
            on_prepared=save,
            shared_capture=not bool(item),
        )
    except (ValueError, OSError) as exc:
        st.error(str(exc))


def back(cid):
    st.session_state.pop("campaign_settings_identity", None)
    st.query_params.clear()
    st.query_params["view"] = "campaigns"
    if cid:
        st.query_params["campaign"] = cid
    st.rerun()
