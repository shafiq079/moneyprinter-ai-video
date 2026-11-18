"""VoiceStudio's local voice catalog and speech API."""
import hashlib
import math
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from moviepy import AudioFileClip

from app.utils import utils

PREFIX = "voicestudio:"
GALLERY_PREFIX = f"{PREFIX}gallery:"
_GALLERY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
DEFAULT_URL = "http://127.0.0.1:3900"
MAX_INPUT_LENGTH = 4096
_ENGINE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_BREAK = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])\s*|\n+")


@dataclass(frozen=True)
class VoiceOption:
    label: str
    sample: str = ""
    use_path: str = ""
    recorded: bool = False


class GalleryVoiceError(ValueError):
    """An actionable gallery error safe to display to an operator."""


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


def _engine_catalog() -> dict:
    catalog = _request("GET", "/engines/tts", timeout=(3, 8)).json()
    if not isinstance(catalog, dict) or not isinstance(catalog.get("backends"), list):
        raise ValueError("VoiceStudio returned an invalid engine catalog")
    return catalog


def _preset_voices(catalog: dict) -> dict[str, VoiceOption]:
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
                voices[f"{PREFIX}{engine_id}:{preset}"] = VoiceOption(f"{preset} · {engine_label}")
    return voices


def _gallery_page(path: str, **params) -> Iterator[dict]:
    offset = 0
    limit = 100
    while True:
        data = _request("GET", path, timeout=(3, 25),
                        params={**params, "limit": limit, "offset": offset}).json()
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("items"), list)
            or type(data.get("total")) is not int
        ):
            raise ValueError("VoiceStudio returned an invalid gallery catalog")
        page = data["items"]
        yield from (item for item in page if isinstance(item, dict))
        offset += len(page)
        if not page or len(page) < limit:
            return
        if offset >= data["total"]:
            return


def _gallery_voices() -> dict[str, VoiceOption]:
    # The website's Starter, World and Community packs use the community catalog.
    # Bundled featured voices are also available when the remote manifest is offline.
    voices = {}
    for path, params in (("/community/items", {}), ("/archetypes", {"featured": "true"})):
        try:
            items = _gallery_page(path, **params)
            for item in items:
                item_id, name = item.get("id"), item.get("name")
                if not isinstance(item_id, str) or not _GALLERY_ID.fullmatch(item_id):
                    continue
                if not isinstance(name, str) or not name.strip():
                    continue
                language = item.get("language")
                suffix = f" · {language}" if isinstance(language, str) and language else ""
                sample = item.get("sample_script")
                if not sample and isinstance(item.get("audio"), dict):
                    sample = item["audio"].get("ref_text")
                voices.setdefault(
                    f"{GALLERY_PREFIX}{item_id}",
                    VoiceOption(
                        f"{name.strip()}{suffix} · VoiceStudio Gallery",
                        sample.strip()[:1000] if isinstance(sample, str) else "",
                        f"{path}/{item_id}/use",
                        item.get("type") == "voice",
                    ),
                )
        except (ValueError, requests.RequestException):
            # Older, offline or restricted backends can still serve engine presets.
            continue
        if voices:
            break
    return voices


def get_voice_catalog() -> dict[str, VoiceOption]:
    return _preset_voices(_engine_catalog()) | _gallery_voices()


def get_voices() -> dict[str, str]:
    """Return voice labels keyed by stable IDs, including the VoiceStudio gallery."""
    return {voice_id: option.label for voice_id, option in get_voice_catalog().items()}


def _gallery_voice(voice_id: str) -> VoiceOption:
    option = _gallery_voices().get(voice_id)
    if option is None:
        raise GalleryVoiceError("The selected voice is unavailable in the VoiceStudio gallery.")
    return option


def _gallery_profile(voice_id: str) -> str:
    option = _gallery_voice(voice_id)
    response = _request("POST", option.use_path, timeout=(3, 90)).json()
    profile_id = response.get("profile_id") if isinstance(response, dict) else None
    if not isinstance(profile_id, str) or not _GALLERY_ID.fullmatch(profile_id):
        raise GalleryVoiceError("VoiceStudio could not save the selected gallery voice.")
    return profile_id


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


def _rate_and_volume(rate: float, volume: float) -> tuple[float, float]:
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    rate = min(2.0, max(0.5, rate)) if math.isfinite(rate) and rate > 0 else 1.0

    volume = float(volume)
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("Invalid VoiceStudio volume")
    return rate, volume


def _encode_mp3(source: Path, rate: float, volume: float, *, pcm: bool = False) -> Path:
    rendered = source.with_name("rendered.mp3")
    input_format = ["-f", "s16le", "-ar", "24000", "-ac", "1"] if pcm else []
    subprocess.run(
        [utils.get_ffmpeg_binary(), "-nostdin", "-loglevel", "error", *input_format,
         "-i", str(source), "-af", f"atempo={rate},volume={volume}",
         "-c:a", "libmp3lame", str(rendered)],
        check=True, capture_output=True, timeout=120,
    )
    return rendered


def _publish_audio(source: Path, destination: Path) -> float:
    with AudioFileClip(str(source)) as clip:
        duration = clip.duration
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("VoiceStudio produced no playable audio")
    os.replace(source, destination)
    return duration


def _content_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def _write_audio(response: requests.Response, path: Path, *, wav_only: bool = False) -> Path:
    mime = _content_type(response)
    suffix = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3"}.get(mime)
    if not suffix or (wav_only and suffix != ".wav") or not response.content:
        raise GalleryVoiceError("VoiceStudio returned invalid gallery audio.")
    source = path.with_suffix(suffix)
    source.write_bytes(response.content)
    return source


def _sample_location(voice_id: str) -> tuple[str, bool]:
    item_id = voice_id.removeprefix(GALLERY_PREFIX)
    if not voice_id.startswith(GALLERY_PREFIX) or not _GALLERY_ID.fullmatch(item_id):
        raise GalleryVoiceError("Invalid VoiceStudio gallery voice.")
    if item_id.startswith("feat_"):
        return f"https://voicestudio.sh/audio/gallery/{item_id}.mp3", True
    option = _gallery_voice(voice_id)
    if option.recorded:
        return option.use_path.removesuffix("/use") + "/preview", False
    raise GalleryVoiceError(
        "This voice has no published sample. Use Generate Full Voiceover Preview "
        "to render your script with this voice."
    )


def _download_sample(location: str, public: bool) -> requests.Response:
    try:
        if not public:
            return _request("GET", location, timeout=(3, 15))
        # Official website clips are small MP3s. Never send local API credentials
        # to the website, and never follow a redirect to another host.
        with requests.get(location, timeout=(8, 15), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise GalleryVoiceError("The published voice sample is currently unavailable.")
            chunks = []
            size = 0
            started = time.monotonic()
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2 * 1024 * 1024 or time.monotonic() - started > 20:
                    raise GalleryVoiceError("The voice sample download exceeded its limit.")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            return response
    except requests.RequestException as exc:
        raise GalleryVoiceError(
            "The voice sample download timed out or failed. Try Play Voice again."
        ) from exc


def preview_gallery(voice_id: str, rate: float, output_file: str, *, volume: float = 1.0) -> float:
    """Download a published sample, reusing the local cache on later plays."""
    location, public = _sample_location(voice_id)
    rate, volume = _rate_and_volume(rate, volume)
    cache_root = Path(utils.storage_dir("voicestudio-previews", create=True))
    # Recorded clips can be private to a server; scope their cache to that
    # connection. Published website clips are shared across local connections.
    identity = location if public else repr((connection(), location))
    digest = hashlib.sha256(identity.encode()).hexdigest()
    destination = Path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voicestudio-", dir=destination.parent) as work:
        source = Path(work) / "sample.mp3"
        cached = next(
            (path for path in cache_root.glob(f"{digest}.*")
             if path.suffix in {".mp3", ".wav"} and time.time() - path.stat().st_mtime < 86400),
            None,
        )
        if cached is not None:
            source = source.with_suffix(cached.suffix)
            source.write_bytes(cached.read_bytes())
        else:
            response = _download_sample(location, public)
            source = _write_audio(response, source)
            with AudioFileClip(str(source)) as clip:
                if not math.isfinite(clip.duration) or clip.duration <= 0:
                    raise GalleryVoiceError("The downloaded voice sample is not playable.")
            # Publish only complete, decoded audio to the shared cache.
            with tempfile.NamedTemporaryFile(dir=cache_root, suffix=".part", delete=False) as temporary:
                temporary.write(source.read_bytes())
                pending = Path(temporary.name)
            try:
                os.replace(pending, cache_root / f"{digest}{source.suffix}")
            finally:
                pending.unlink(missing_ok=True)
        if rate != 1.0 or volume != 1.0:
            source = _encode_mp3(source, rate, volume)
        return _publish_audio(source, destination)


def synthesize(
    text: str, voice_id: str, rate: float, output_file: str, *, volume: float = 1.0
) -> float:
    """Render voiceover speech and atomically publish the decoded MP3."""
    if not any(character.isalnum() for character in text):
        raise ValueError("VoiceStudio requires speakable text")
    rate, volume = _rate_and_volume(rate, volume)
    destination = Path(output_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voicestudio-", dir=destination.parent) as work:
        if voice_id.startswith(GALLERY_PREFIX):
            # The native route applies the profile language, reference and seed.
            # Match VoiceStudio's gallery renderer and use its own long-text
            # chunking instead of starting a new voice generation per chunk.
            response = _request(
                "POST", "/generate", timeout=(3, 900),
                data={
                    "text": text, "engine": "omnivoice", "profile_id": _gallery_profile(voice_id),
                    "num_step": 32, "guidance_scale": 2.0, "effect_preset": "broadcast",
                    "postprocess_output": "true",
                },
            )
            if response.headers.get("X-OmniVoice-Dropped-Chunks", "0") != "0":
                raise GalleryVoiceError("VoiceStudio could not speak part of the script.")
            source = _write_audio(response, Path(work) / "speech", wav_only=True)
            return _publish_audio(_encode_mp3(source, rate, volume), destination)

        if voice_id not in _preset_voices(_engine_catalog()):
            raise ValueError("Selected VoiceStudio preset is unavailable")
        engine, preset = voice_id.removeprefix(PREFIX).split(":", 1)
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
                data = response.content
                if _content_type(response) != "audio/pcm" or not data or len(data) % 2:
                    raise ValueError("VoiceStudio returned invalid speech audio")
                audio.write(data)

        return _publish_audio(_encode_mp3(pcm, rate, volume, pcm=True), destination)
