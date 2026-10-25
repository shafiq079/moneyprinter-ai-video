"""Source-bound narration ranges, original previews and replacement auditions."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import uuid
import wave
from pathlib import Path

from app.services import generation_manifest as gm
from app.services import scene_planner, voice
from app.utils import utils

_NAME = "narration_ranges.json"
_MAX_SCENES = 512
_MAX_SECONDS = 3600
MAX_REPLACEMENT_BYTES = 20 * 1024 * 1024


def _file(task_id: str) -> Path:
    return gm.resolve_asset(task_id, _NAME)


def read_ranges(task_id: str) -> dict | None:
    file = _file(task_id)
    if not file.exists():
        return None
    if file.stat().st_size > 1024 * 1024:
        raise ValueError("narration range file is too large")
    data = json.loads(file.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("basis") not in ("estimated_scene_weights", "operator_adjusted")
        or data.get("speech_aligned") is not False
        or not isinstance(data.get("ranges"), list)
        or not 0 < len(data["ranges"]) <= _MAX_SCENES
    ):
        raise ValueError("unsupported narration range data")
    duration = data.get("audio_duration")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or not 0 < duration <= _MAX_SECONDS
    ):
        raise ValueError("invalid narration duration")
    previous = 0.0
    ids = set()
    for item in data["ranges"]:
        if (
            not isinstance(item, dict)
            or type(item.get("scene_id")) is not int
            or item["scene_id"] <= 0
            or item["scene_id"] in ids
        ):
            raise ValueError("invalid narration scene IDs")
        start, end = item.get("start"), item.get("end")
        if (
            any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                for v in (start, end)
            )
            or abs(start - previous) > 1e-6
            or not start < end <= duration + 1e-6
        ):
            raise ValueError("invalid narration range boundaries")
        if "replacement" in item:
            draft = item["replacement"]
            if (not isinstance(draft, dict)
                    or not {"preview_asset", "preview_sha256"} <= set(draft)
                    or set(draft) - {"preview_asset", "preview_sha256", "text", "origin", "fit_ratio", "timing_mode", "audio_duration"}
                    or not isinstance(draft["preview_asset"], str)
                    or not isinstance(draft["preview_sha256"], str)):
                raise ValueError("invalid narration replacement metadata")
            if "text" in draft and normalize_text(draft["text"]) != draft["text"]:
                raise ValueError("invalid replacement transcript")
            if "origin" in draft and draft["origin"] not in ("upload", "tts"):
                raise ValueError("invalid replacement origin")
            ratio = draft.get("fit_ratio", 1.0)
            if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0.5 <= ratio <= 2:
                raise ValueError("invalid replacement tempo")
            if "timing_mode" in draft:
                draft_duration = draft.get("audio_duration")
                if (draft["timing_mode"] != "natural" or isinstance(draft_duration, bool)
                        or not isinstance(draft_duration, (int, float)) or not math.isfinite(draft_duration)
                        or not 0 < draft_duration <= _MAX_SECONDS or "fit_ratio" in draft):
                    raise ValueError("invalid natural narration duration")
            elif "audio_duration" in draft:
                raise ValueError("natural narration duration requires its timing mode")
            parts = Path(draft["preview_asset"]).parts
            if (len(parts) != 3 or parts[0] != "narration_replacements"
                    or len(parts[1]) != 32
                    or any(c not in "0123456789abcdef" for c in parts[1])
                    or parts[2] != f"scene-{item['scene_id']:03d}.wav"
                    or len(draft["preview_sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in draft["preview_sha256"])):
                raise ValueError("invalid narration replacement reference")
        ids.add(item["scene_id"])
        previous = end
    if abs(previous - duration) > 1e-6:
        raise ValueError("narration ranges do not cover the audio")
    binding = data.get("binding")
    if (
        not isinstance(binding, dict)
        or not isinstance(binding.get("scene_text"), list)
        or [item["scene_id"] for item in data["ranges"]]
        != [
            item.get("scene_id")
            for item in binding["scene_text"]
            if isinstance(item, dict)
        ]
    ):
        raise ValueError("narration ranges do not match their bound scenes")
    reviewed = data.get("operator_reviewed_scene_ids", [])
    if (
        not isinstance(reviewed, list)
        or any(type(i) is not int or i not in ids for i in reviewed)
        or len(set(reviewed)) != len(reviewed)
    ):
        raise ValueError("invalid operator narration review state")
    weights = data.get("estimation_weights")
    if (
        not isinstance(weights, dict)
        or set(weights) != {str(i) for i in ids}
        or any(
            isinstance(w, bool)
            or not isinstance(w, (int, float))
            or not math.isfinite(w)
            or w <= 0
            for w in weights.values()
        )
    ):
        raise ValueError("invalid saved narration estimation weights")
    return data


def normalize_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("scene narration text must contain 1–2000 characters")
    if any(ord(c) < 32 and not c.isspace() for c in text):
        raise ValueError("scene narration text contains control characters")
    return " ".join(text.split())


def _save(task_id: str, data: dict) -> None:
    if len((json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")) > 1024 * 1024:
        raise ValueError("narration metadata exceeds one MiB")
    scene_planner._atomic_write_json(_file(task_id), data)


def set_draft_text(task_id: str, plan, source: str, scene_id: int, *, expected_revision: str, text: str) -> dict:
    text = normalize_text(text)
    if type(scene_id) is not int:
        raise ValueError("invalid narration scene ID")
    if gm.resolve_asset(task_id, "narration_mix.json").exists():
        raise ValueError("restore original narration before changing drafts")
    if revision(task_id) != expected_revision:
        raise ValueError("narration ranges changed; refresh the Scene Editor")
    data = load_validated(task_id, plan, source)
    item = next((i for i in data["ranges"] if i["scene_id"] == scene_id), None)
    if item is None or not item.get("replacement"):
        raise ValueError("save a replacement recording first")
    _replacement_preview(task_id, item)
    item["replacement"]["text"] = text
    current = scene_planner.load_scene_plan(task_id)
    if (current is None or _binding(task_id, current, source)[0] != data["binding"]
            or revision(task_id) != expected_revision):
        raise ValueError("narration inputs changed; refresh the Scene Editor")
    _save(task_id, data)
    return data


def _binding(task_id: str, plan, audio_file: str) -> tuple[dict, Path]:
    root = Path(utils.task_dir(task_id)).resolve()
    try:
        relative = Path(audio_file).resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            "narration previews require task-local audio; upload the audio into this task"
        ) from exc
    audio = gm.resolve_asset(task_id, relative)
    script = json.loads(
        gm.resolve_asset(task_id, "script.json").read_text(encoding="utf-8")
    )
    text = script.get("script")
    if not isinstance(text, str):
        raise ValueError("saved narration script is unavailable")
    scenes = sorted(plan.scenes, key=lambda s: s.scene_id)
    return {
        "audio_asset": relative,
        "audio_sha256": gm.media_sha256(audio),
        "script_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "scene_text": [
            {"scene_id": s.scene_id, "text": s.narration_segment} for s in scenes
        ],
    }, audio


def load_validated(task_id: str, plan, audio_file: str) -> dict:
    data = read_ranges(task_id)
    if data is None:
        raise ValueError("prepare narration previews first")
    binding, _audio = _binding(task_id, plan, audio_file)
    if data.get("binding") != binding:
        raise ValueError("narration sources changed; prepare narration previews again")
    return data


def _preview(task_id: str, item: dict, *, replacement: bool = False) -> Path:
    prefix = "narration_replacements/" if replacement else "narration_previews/"
    relative = item.get("preview_asset")
    if (
        not isinstance(relative, str)
        or not relative.startswith(prefix)
        or not relative.endswith(".wav")
    ):
        raise ValueError("invalid narration preview reference")
    parts = Path(relative).parts
    if (
        len(parts) != 3
        or len(parts[1]) != 32
        or any(c not in "0123456789abcdef" for c in parts[1])
        or parts[2] != f"scene-{item['scene_id']:03d}.wav"
    ):
        raise ValueError("invalid narration preview reference")
    candidate = gm.resolve_asset(task_id, relative)
    if candidate.stat().st_size > _MAX_SECONDS * 32000 + 4096:
        raise ValueError("narration preview is too large")
    if gm.media_sha256(candidate) != item.get("preview_sha256"):
        raise ValueError("narration preview changed; prepare previews again")
    with wave.open(str(candidate), "rb") as stream:
        if (
            stream.getnframes() <= 0
            or stream.getframerate() != 16000
            or stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or abs(stream.getnframes() / 16000 - (item["audio_duration"] if replacement and item.get("timing_mode") == "natural" else item["end"] - item["start"])) > 0.002
        ):
            raise ValueError("invalid narration preview audio")
    return candidate


def _extract(audio: Path, output: Path, start: float, duration: float, input_format: str | None = None) -> None:
    command = [
        utils.get_ffmpeg_binary(),
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        *(["-f", input_format] if input_format else []),
        "-i",
        str(audio),
        "-ss",
        f"{start:.9f}",
        "-t",
        f"{duration:.9f}",
        "-map",
        "0:a:0",
        "-vn",
        "-map_metadata",
        "-1",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("narration preview processing timed out") from exc
    except OSError as exc:
        raise ValueError("narration preview decoder unavailable") from exc
    if result.returncode:
        raise ValueError("could not extract narration preview")


def _fit_audio(source: Path, target: Path, frames: int, ratio: float) -> None:
    command = [utils.get_ffmpeg_binary(), "-nostdin", "-y", "-v", "error", "-i", str(source),
               "-af", f"atempo={ratio:.12f},apad=whole_len={frames},atrim=end_sample={frames}",
               "-map_metadata", "-1", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("could not fit narration duration") from exc
    if result.returncode:
        raise ValueError("could not fit narration duration")


def prepare(
    task_id: str,
    plan,
    audio_file: str,
    *,
    _revised: dict | None = None,
    _expected_revision: str | None = None,
) -> dict:
    binding, audio = _binding(task_id, plan, audio_file)
    try:
        old = read_ranges(task_id)
    except (ValueError, OSError):
        old = None
    reusable = old is not None and old.get("binding") == binding
    if _revised is not None and (not reusable or _revised.get("binding") != binding):
        raise ValueError("narration sources changed; refresh the Scene Editor")
    if reusable and _revised is None:
        try:
            for item in old["ranges"]:
                _preview(task_id, item)
            _remove_inactive_previews(task_id, old)
            return old
        except (OSError, ValueError, wave.Error, EOFError):
            pass
    scenes = sorted(plan.scenes, key=lambda s: s.scene_id)
    reported_duration = float(voice.get_audio_duration(str(audio)))
    if (
        not 0 < len(scenes) <= _MAX_SCENES
        or not math.isfinite(reported_duration)
        or not 0 < reported_duration <= _MAX_SECONDS
    ):
        raise ValueError(
            "narration previews support up to 512 scenes and one hour of audio"
        )
    directory = gm.resolve_asset(task_id, f"narration_previews/{uuid.uuid4().hex}")
    directory.mkdir(parents=True)
    try:
        # Container duration can include MP3 encoder padding. Use the decoded
        # sample timeline shared by every preview, never the rounded task duration.
        decoded = directory / ".decoded.wav"
        _extract(audio, decoded, 0, _MAX_SECONDS + 1)
        with wave.open(str(decoded), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        if not 0 < duration <= _MAX_SECONDS:
            raise ValueError("invalid decoded narration duration")
        if reusable:
            if abs(old["audio_duration"] - duration) > 0.002:
                raise ValueError(
                    "decoded audio no longer matches the saved narration ranges"
                )
            selected = _revised if _revised is not None else old
            data = {**selected, "ranges": [dict(item) for item in selected["ranges"]]}
        else:
            weights = [scene.target_duration for scene in scenes]
            if any(not math.isfinite(w) or w <= 0 for w in weights):
                raise ValueError("invalid narration estimation weights")
            total, elapsed = sum(weights), 0.0
            ranges = []
            for scene, weight in zip(scenes, weights):
                start = elapsed / total * duration
                elapsed += weight
                end = duration if scene == scenes[-1] else elapsed / total * duration
                ranges.append({"scene_id": scene.scene_id, "start": start, "end": end})
            data = {
                "schema_version": 1,
                "basis": "estimated_scene_weights",
                "speech_aligned": False,
                "audio_duration": duration,
                "estimation_weights": {
                    str(scene.scene_id): weight
                    for scene, weight in zip(scenes, weights)
                },
                "binding": binding,
                "ranges": ranges,
            }
        # Seek in the decoded PCM track instead of decoding the original file
        # again for each range. Adjacent cuts share the same sample boundaries.
        with wave.open(str(decoded), "rb") as source:
            for item in data["ranges"]:
                output = directory / f"scene-{item['scene_id']:03d}.wav"
                start_frame = round(item["start"] * 16000)
                end_frame = round(item["end"] * 16000)
                if end_frame <= start_frame:
                    raise ValueError(
                        "narration range is shorter than one preview sample"
                    )
                source.setpos(start_frame)
                remaining = end_frame - start_frame
                with wave.open(str(output), "wb") as target:
                    target.setparams(source.getparams())
                    while remaining:
                        chunk = source.readframes(min(160000, remaining))
                        if not chunk:
                            raise ValueError(
                                "decoded narration ended before its saved range"
                            )
                        target.writeframesraw(chunk)
                        remaining -= len(chunk) // 2
                item["preview_asset"] = output.relative_to(
                    Path(utils.task_dir(task_id)).resolve()
                ).as_posix()
                item["preview_sha256"] = gm.media_sha256(output)
                _preview(task_id, item)
        decoded.unlink()
        current_plan = scene_planner.load_scene_plan(task_id)
        if (
            current_plan is None
            or _binding(task_id, current_plan, audio_file)[0] != binding
        ):
            raise ValueError("narration sources changed during preview extraction")
        if _expected_revision is not None and revision(task_id) != _expected_revision:
            raise ValueError("narration ranges changed; refresh the Scene Editor")
        _save(task_id, data)
    except Exception:
        shutil.rmtree(directory)
        raise
    _remove_inactive_previews(task_id, data)
    return data


def revision(task_id: str) -> str:
    return gm.media_sha256(_file(task_id))


def read_snapshot(task_id: str) -> tuple[dict | None, str | None]:
    """Pair displayed ranges with the exact revision used for a queued edit."""
    before = revision(task_id) if _file(task_id).exists() else None
    data = read_ranges(task_id)
    after = revision(task_id) if data is not None else None
    if before != after:
        raise ValueError("narration ranges changed; refresh the Scene Editor")
    return data, before


def edit(
    task_id: str,
    plan,
    audio_file: str,
    scene_id: int,
    *,
    expected_revision: str,
    end: float | None = None,
    reviewed: bool = False,
) -> dict:
    """Adjust a shared narration boundary, or record an explicit operator review."""
    if type(scene_id) is not int or type(reviewed) is not bool:
        raise ValueError("invalid narration review request")
    if revision(task_id) != expected_revision:
        raise ValueError("narration ranges changed; refresh the Scene Editor")
    data = load_validated(task_id, plan, audio_file)
    data = json.loads(json.dumps(data))
    index = next(
        (n for n, item in enumerate(data["ranges"]) if item["scene_id"] == scene_id),
        None,
    )
    if index is None:
        raise ValueError("scene has no narration range")
    checked = set(data.get("operator_reviewed_scene_ids", []))
    if reviewed:
        if end is not None:
            raise ValueError("review and boundary changes are separate actions")
        # Listenability and source identity must be valid when review is recorded.
        _preview(task_id, data["ranges"][index])
        checked.add(scene_id)
        data["operator_reviewed_scene_ids"] = sorted(checked)
        current_plan = scene_planner.load_scene_plan(task_id)
        if (
            current_plan is None
            or _binding(task_id, current_plan, audio_file)[0] != data["binding"]
            or revision(task_id) != expected_revision
        ):
            raise ValueError(
                "narration sources or ranges changed; refresh the Scene Editor"
            )
        _save(task_id, data)
        return data
    if index == len(data["ranges"]) - 1:
        raise ValueError("the final narration endpoint stays at the audio end")
    if (
        isinstance(end, bool)
        or not isinstance(end, (int, float))
        or not math.isfinite(end)
    ):
        raise ValueError("narration boundary must be a finite number")
    left, right = data["ranges"][index : index + 2]
    end = round(end * 16000) / 16000
    if not left["start"] < end < right["end"]:
        raise ValueError("narration boundary must leave audio in both adjacent ranges")
    if abs(end - left["end"]) < 1 / 32000:
        return data
    if left.get("replacement") or right.get("replacement"):
        raise ValueError("remove adjacent narration drafts before moving this boundary")
    if gm.resolve_asset(task_id, "narration_mix.json").exists():
        raise ValueError("restore original narration before editing boundaries")
    left["end"] = right["start"] = end
    checked.difference_update((left["scene_id"], right["scene_id"]))
    data["operator_reviewed_scene_ids"] = sorted(checked)
    data["basis"] = "operator_adjusted"
    return prepare(
        task_id, plan, audio_file, _revised=data, _expected_revision=expected_revision
    )


def _remove_inactive_previews(task_id: str, data: dict) -> None:
    keep = {
        gm.resolve_asset(task_id, item["preview_asset"]).parent
        for item in data["ranges"]
    }
    _remove_inactive_replacements(task_id, data)
    preview_root = gm.resolve_asset(task_id, "narration_previews")
    for previous in preview_root.iterdir():
        if (
            previous not in keep
            and not previous.is_symlink()
            and len(previous.name) == 32
            and all(c in "0123456789abcdef" for c in previous.name)
            and previous.is_dir()
        ):
            shutil.rmtree(previous, ignore_errors=True)


def _replacement_preview(task_id: str, item: dict) -> Path:
    replacement = item.get("replacement")
    if not isinstance(replacement, dict):
        raise ValueError("invalid narration replacement draft")
    return _preview(task_id, {**item, **replacement}, replacement=True)


def _remove_inactive_replacements(task_id: str, data: dict) -> None:
    directory = gm.resolve_asset(task_id, "narration_replacements")
    if not directory.exists():
        return
    keep = {
        gm.resolve_asset(task_id, item["replacement"]["preview_asset"]).parent
        for item in data["ranges"] if item.get("replacement")
    }
    for old in directory.iterdir():
        if (old not in keep and not old.is_symlink() and old.is_dir()
                and len(old.name) == 32
                and all(c in "0123456789abcdef" for c in old.name)):
            shutil.rmtree(old, ignore_errors=True)


def replace_draft(task_id: str, plan, audio_file: str, scene_id: int, *,
                  expected_revision: str, content: bytes | None = None,
                  text: str | None = None, fit_duration: bool = False, origin: str = "upload", natural_duration: bool = False) -> dict:
    """Save or remove an audition-only upload, never edit the master track."""
    if type(scene_id) is not int or type(fit_duration) is not bool or type(natural_duration) is not bool or (fit_duration and natural_duration) or origin not in ("upload", "tts"):
        raise ValueError("invalid narration draft request")
    if text is not None:
        text = normalize_text(text)
    if content is not None and (type(content) is not bytes or not 0 < len(content) <= MAX_REPLACEMENT_BYTES):
        raise ValueError("narration upload must contain at most 20 MiB")
    if gm.resolve_asset(task_id, "narration_mix.json").exists():
        raise ValueError("restore original narration before changing drafts")
    input_format = None
    if content is not None:
        # Force an audio demuxer so an uploaded playlist/concat document cannot
        # ask FFmpeg to read arbitrary local files under the file protocol.
        if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            input_format = "wav"
        elif content[:3] == b"ID3" or (len(content) > 1 and content[0] == 255 and content[1] & 224 == 224):
            input_format = "mp3"
        elif content[4:8] == b"ftyp":
            input_format = "mov"
        else:
            raise ValueError("upload a WAV, MP3 or M4A audio file")
    if revision(task_id) != expected_revision:
        raise ValueError("narration ranges changed; refresh the Scene Editor")
    data = load_validated(task_id, plan, audio_file)
    item = next((i for i in data["ranges"] if i["scene_id"] == scene_id), None)
    if item is None:
        raise ValueError("scene has no narration range")
    if content is not None and scene_id not in data.get("operator_reviewed_scene_ids", []):
        raise ValueError("listen to and review the original narration range first")
    if content is None and "replacement" not in item:
        return data
    directory = None
    try:
        if content is None:
            item.pop("replacement", None)
        else:
            _preview(task_id, item)
            directory = gm.resolve_asset(task_id, f"narration_replacements/{uuid.uuid4().hex}")
            directory.mkdir(parents=True)
            upload = directory / "upload.audio"
            upload.write_bytes(content)
            output = directory / f"scene-{scene_id:03d}.wav"
            duration = item["end"] - item["start"]
            # Decode beyond the permitted duration so an overlong upload is
            # rejected rather than silently trimmed. No time stretching/padding.
            _extract(upload, output, 0, _MAX_SECONDS + 1 if natural_duration else (duration * 2 if fit_duration else duration) + 0.2, input_format)
            with wave.open(str(output), "rb") as stream:
                actual = stream.getnframes() / stream.getframerate()
            if not 0 < actual <= _MAX_SECONDS:
                raise ValueError("recording must contain at most one hour of audio")
            ratio = actual / duration
            if fit_duration:
                if not 0.5 <= ratio <= 2:
                    raise ValueError("recording needs more than 0.5x–2x tempo fitting; shorten/extend the text or adjust its range")
                fitted = directory / "fitted.wav"
                _fit_audio(output, fitted, round(duration * 16000), ratio)
                fitted.replace(output)
            elif not natural_duration and abs(actual - duration) > 0.002:
                raise ValueError(f"replacement must match the range duration ({duration:.3f} seconds) within 2 ms")
            upload.unlink()
            item["replacement"] = {
                "preview_asset": output.relative_to(Path(utils.task_dir(task_id)).resolve()).as_posix(),
                "preview_sha256": gm.media_sha256(output),
            }
            if text is not None:
                item["replacement"]["text"] = text
            item["replacement"]["origin"] = origin
            if natural_duration:
                item["replacement"].update(timing_mode="natural", audio_duration=actual)
            if fit_duration:
                item["replacement"]["fit_ratio"] = ratio
            _replacement_preview(task_id, item)
        current_plan = scene_planner.load_scene_plan(task_id)
        if (current_plan is None
                or _binding(task_id, current_plan, audio_file)[0] != data["binding"]
                or revision(task_id) != expected_revision):
            raise ValueError("narration sources or ranges changed; refresh the Scene Editor")
        _save(task_id, data)
    except Exception:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    _remove_inactive_replacements(task_id, data)
    return data


def preview_payload(task_id: str, plan, audio_file: str, scene_id: int, *, replacement: bool = False) -> dict:
    data = load_validated(task_id, plan, audio_file)
    item = next((i for i in data["ranges"] if i["scene_id"] == scene_id), None)
    if item is None:
        raise ValueError("scene has no narration range")
    if replacement:
        item = {**item, **item.get("replacement", {})}
        if not item["preview_asset"].startswith("narration_replacements/"):
            raise ValueError("scene has no replacement narration draft")
    candidate = _preview(task_id, item, replacement=replacement)
    assets = [
        data["binding"]["audio_asset"],
        item["preview_asset"],
        _NAME,
        "scene_plan.json",
        "script.json",
    ]
    signature = {
        asset: _signature(gm.resolve_asset(task_id, asset)) for asset in assets
    }
    content = candidate.read_bytes()
    current_plan = scene_planner.load_scene_plan(task_id)
    if (
        current_plan is None
        or _binding(task_id, current_plan, audio_file)[0] != data["binding"]
        or any(
            _signature(gm.resolve_asset(task_id, asset)) != value
            for asset, value in signature.items()
        )
    ):
        raise ValueError("narration sources changed while loading preview")
    return {
        "replacement": replacement,
        "audio": content,
        "signature": signature,
        "audio_asset": data["binding"]["audio_asset"],
    }


def _signature(file: Path) -> tuple[int, int]:
    stat = file.stat()
    return stat.st_size, stat.st_mtime_ns


def preview_is_current(
    task_id: str, payload: dict, audio_file: str | None = None
) -> bool:
    try:
        if audio_file:
            current = (
                Path(audio_file)
                .resolve()
                .relative_to(Path(utils.task_dir(task_id)).resolve())
                .as_posix()
            )
            if current != payload.get("audio_asset"):
                return False
        return all(
            _signature(gm.resolve_asset(task_id, asset)) == value
            for asset, value in payload["signature"].items()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
