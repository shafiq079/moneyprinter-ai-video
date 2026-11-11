"""CPU checks for the local VoiceStudio provider and its Streamlit selector."""
import math
from array import array
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import voice, voicestudio

KITTEN = "voicestudio:kittentts:expr-voice-2-f"
SUPERTONIC = "voicestudio:supertonic3:F3"
CATALOG = {
    "backends": [
        {"id": "kittentts", "display_name": "KittenTTS", "available": True,
         "preset_voices": ["expr-voice-2-f", "expr-voice-2-m"]},
        {"id": "supertonic3", "available": True, "preset_voices": ["F3"],
         "license_required": True, "license_accepted": True},
        {"id": "not-installed", "available": False, "preset_voices": ["voice"]},
        {"id": "unrunnable", "available": True, "routing_status": "unavailable",
         "preset_voices": ["voice"]},
        {"id": "unaccepted", "available": True, "license_required": True,
         "preset_voices": ["voice"]},
        {"id": "omnivoice", "available": True, "preset_voices": []},
    ],
}


def _mock_backend(monkeypatch, audio=b""):
    def request(method, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        if method == "GET":
            assert url.endswith("/engines/tts")
            response.json = lambda: CATALOG
        else:
            assert url.endswith("/v1/audio/speech")
            response.headers["Content-Type"] = "audio/pcm"
            response._content = audio
        return response

    mocked = Mock(side_effect=request)
    monkeypatch.setattr(voicestudio.requests, "request", mocked)
    return mocked


def test_catalog_exposes_only_available_real_presets(monkeypatch):
    backend = _mock_backend(monkeypatch)
    monkeypatch.setenv("MPT_VOICESTUDIO_URL", "http://localhost:3900/v1/")
    monkeypatch.setenv("MPT_VOICESTUDIO_API_KEY", "local-token")

    assert list(voicestudio.get_voices()) == [
        KITTEN, "voicestudio:kittentts:expr-voice-2-m", SUPERTONIC,
    ]
    assert backend.call_args.args == ("GET", "http://localhost:3900/engines/tts")
    assert backend.call_args.kwargs["headers"] == {"Authorization": "Bearer local-token"}
    assert backend.call_args.kwargs["allow_redirects"] is False


def test_synthesis_uses_stable_preset_and_renders_long_text_at_requested_speed(monkeypatch, tmp_path):
    # Two seconds of audible PCM per request. FFmpeg and MoviePy run for real.
    pcm = array("h", (round(8000 * math.sin(i * math.tau * 440 / 24000))
                      for i in range(48000))).tobytes()
    backend = _mock_backend(monkeypatch, pcm)
    monkeypatch.setattr(voicestudio, "MAX_INPUT_LENGTH", 25)
    script = "Listen to this sentence. Now listen to the next."
    output = tmp_path / "audio.mp3"

    maker = voice.tts(script, KITTEN, 2.0, str(output), voice_volume=0.8)

    assert output.is_file()
    assert 1.85 < voice.get_audio_duration(str(output)) < 2.2
    assert maker.timing_estimated is True
    payloads = [call.kwargs["json"] for call in backend.call_args_list if call.args[0] == "POST"]
    assert [payload["input"] for payload in payloads] == [
        "Listen to this sentence.", "Now listen to the next.",
    ]
    assert {(payload["model"], payload["voice"], payload["speed"]) for payload in payloads} == {
        ("kittentts", "expr-voice-2-f", 1.0),
    }


def test_failed_synthesis_preserves_output_and_never_uses_edge(monkeypatch, tmp_path):
    backend = _mock_backend(monkeypatch)
    edge = Mock(side_effect=AssertionError("unexpected Edge request"))
    monkeypatch.setattr(voice, "azure_tts_v1", edge)
    monkeypatch.setattr(voice, "azure_tts_v2", edge)
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous narration")
    unavailable = "voicestudio:kittentts:Voice-Female-V2"

    assert voice.parse_voice_name(unavailable) == unavailable
    assert voice.tts("Test.", unavailable, 1.0, str(output)) is None
    assert backend.call_count == 1
    assert voice.tts("Test.", KITTEN, 1.0, str(output)) is None
    assert output.read_bytes() == b"previous narration"
    edge.assert_not_called()


@pytest.mark.parametrize("online", [True, False])
def test_audio_panel_restores_the_provider_and_saved_voice(monkeypatch, online):
    monkeypatch.setenv("MPT_VOICESTUDIO_URL", f"http://localhost:{3940 + online}")
    monkeypatch.setattr(config, "ui", dict(config.ui, voice_mode="tts", tts_server="voicestudio",
                                          voice_name=SUPERTONIC))
    monkeypatch.setattr(config, "save_config", Mock())
    monkeypatch.setattr(config, "try_save_config", Mock(return_value=True))
    backend = _mock_backend(monkeypatch)
    if not online:
        backend.side_effect = requests.ConnectionError
    page = AppTest.from_file(str(Path(__file__).parents[2] / "webui/Main.py"), default_timeout=30)
    page.session_state["ui_language"] = "en"

    page.run()

    assert not page.exception
    service = next(widget for widget in page.selectbox if widget.key == "tts_server_select_en")
    assert service.value == "voicestudio"
    assert "Local Voices (VoiceStudio)" in service.options
    assert config.ui["voice_name"] == SUPERTONIC
    if online:
        picker = next(widget for widget in page.selectbox
                      if widget.key == "speech_synthesis_select_voicestudio_en")
        assert picker.value == SUPERTONIC
        assert picker.options == [
            "expr-voice-2-f · KittenTTS", "expr-voice-2-m · KittenTTS", "F3 · supertonic3",
        ]
        assert not next(widget for widget in page.selectbox
                        if widget.key == "voice_rate_select_en").disabled
    else:
        assert any("Start the local VoiceStudio backend" in str(item.value) for item in page.warning)
