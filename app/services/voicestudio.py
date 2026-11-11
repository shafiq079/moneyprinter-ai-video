"""VoiceStudio's local preset catalog and speech API."""
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import requests
from moviepy import AudioFileClip

from app.utils import utils

PREFIX = "voicestudio:"
DEFAULT_URL = "http://127.0.0.1:3900"
MAX_INPUT_LENGTH = 4096
_ENGINE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_BREAK = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])\s*|\n+")


def connection() -> tuple[str, str]:
    # Operator settings apply to previews, jobs and scene edits on this host.
    base_url = os.environ.get("MPT_VOICESTUDIO_URL", DEFAULT_URL).strip().rstrip("/")
    token = os.environ.get("MPT_VOICESTUDIO_API_KEY", "").strip()
    return base_url.removesuffix("/v1"), token


def _request(method: str, path: str, *, timeout: tuple[int, int], **kwargs) -> requests.Response:
    base_url, token = connection()
    address = urlsplit(base_url)
    if (
        address.scheme not in {"http", "https"}
        or not address.hostname
        or address.username
        or address.password
        or address.query
        or address.fragment
    ):
        raise ValueError("Invalid VoiceStudio server URL")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.request(
        method, base_url + path, headers=headers, timeout=timeout,
        allow_redirects=False, **kwargs,
    )
    if response.status_code != 200:
        raise ValueError(f"VoiceStudio returned HTTP {response.status_code}")
    return response


def get_voices() -> dict[str, str]:
    """Return selectable engine presets keyed by a stable, provider-specific ID."""
    catalog = _request("GET", "/engines/tts", timeout=(3, 8)).json()
    if not isinstance(catalog, dict) or not isinstance(catalog.get("backends"), list):
        raise ValueError("VoiceStudio returned an invalid engine catalog")

    voices = {}
    for engine in catalog["backends"]:
        if (
            not isinstance(engine, dict)
            or engine.get("available") is not True
            or engine.get("routing_status") == "unavailable"
            or (engine.get("license_required") and engine.get("license_accepted") is not True)
        ):
            continue
        engine_id = engine.get("id")
        if not isinstance(engine_id, str) or not _ENGINE_ID.fullmatch(engine_id):
            continue
        presets = engine.get("preset_voices")
        if not isinstance(presets, list):
            continue
        engine_label = engine.get("display_name") or engine_id
        for preset in presets:
            if isinstance(preset, str) and preset.strip():
                voices[f"{PREFIX}{engine_id}:{preset}"] = f"{preset} · {engine_label}"
    return voices


def _speech_chunks(text: str) -> Iterator[str]:
    """Split long scripts at sentence boundaries or the last available space."""
    remaining = text.strip()
    while len(remaining) > MAX_INPUT_LENGTH:
        window = remaining[:MAX_INPUT_LENGTH]
        end = max((match.end() for match in _BREAK.finditer(window)), default=0)
        if not end:
            space = window.rfind(" ")
            end = space if space > 0 else MAX_INPUT_LENGTH
        yield remaining[:end].strip()
        remaining = remaining[end:].lstrip()
    if remaining:
        yield remaining


def synthesize(
    text: str, voice_id: str, rate: float, output_file: str, *, volume: float = 1.0
) -> float:
    """Render all chunks and atomically publish the decoded MP3."""
    if not any(character.isalnum() for character in text):
        raise ValueError("VoiceStudio requires speakable text")
    if not voice_id.startswith(PREFIX) or voice_id not in get_voices():
        raise ValueError("Selected VoiceStudio preset is unavailable")
    engine, preset = voice_id.removeprefix(PREFIX).split(":", 1)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    rate = min(2.0, max(0.5, rate)) if math.isfinite(rate) and rate > 0 else 1.0

    volume = float(volume)
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("Invalid VoiceStudio volume")

    destination = Path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voicestudio-", dir=destination.parent) as work:
        pcm = Path(work) / "speech.pcm"
        with pcm.open("wb") as audio:
            for chunk in _speech_chunks(text):
                if not any(character.isalnum() for character in chunk):
                    continue
                response = _request(
                    "POST", "/v1/audio/speech", timeout=(3, 300),
                    json={"model": engine, "voice": preset, "input": chunk,
                          "response_format": "pcm", "speed": 1.0},
                )
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                data = response.content
                if mime != "audio/pcm" or not data or len(data) % 2:
                    raise ValueError("VoiceStudio returned invalid speech audio")
                audio.write(data)

        # Apply tempo locally because some VoiceStudio engines ignore API speed.
        rendered = Path(work) / "speech.mp3"
        subprocess.run(
            [utils.get_ffmpeg_binary(), "-nostdin", "-loglevel", "error",
             "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(pcm),
             "-af", f"atempo={rate},volume={volume}", "-c:a", "libmp3lame", str(rendered)],
            check=True, capture_output=True, timeout=120,
        )
        with AudioFileClip(str(rendered)) as clip:
            duration = clip.duration
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("VoiceStudio produced no playable audio")
        os.replace(rendered, destination)
        return duration
