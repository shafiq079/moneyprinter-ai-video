"""Bounded independent caption drafts and source-bound active caption tracks."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import re
import shutil
import uuid
from pathlib import Path

from app.services import generation_manifest as gm, narration_mix, scene_planner

DRAFT = "caption_edits.json"
ACTIVE = "caption_track.json"
MAX_BYTES = 1024 * 1024
MAX_CUES = 2000


def file(task_id: str, name: str = DRAFT) -> Path:
    return gm.resolve_asset(task_id, name)


def revision(task_id: str) -> str:
    target = file(task_id)
    if not target.exists():
        return "missing"
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("caption metadata is too large")
    return gm.media_sha256(target)


def read(task_id: str, name: str = DRAFT) -> dict | None:
    target = file(task_id, name)
    if not target.exists():
        return None
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("caption metadata is too large")
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid caption metadata")
    validate_cues(value.get("cues"), value.get("duration_ms"))
    validate_style(value.get("style", {}))
    return value


def save(task_id: str, name: str, data: dict) -> None:
    if len((json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").replace("\n", os.linesep).encode()) > MAX_BYTES:
        raise ValueError("caption metadata is too large")
    scene_planner._atomic_write_json(file(task_id, name), data)


def render_signature(params) -> str:
    return hashlib.sha256(params.model_dump_json().encode()).hexdigest()


def source_binding(task_id: str, original: str, audio: str, captions: str) -> dict:
    def asset(candidate):
        if not candidate:
            return None
        root = file(task_id).parent
        path = Path(candidate).resolve()
        relative = path.relative_to(root.resolve()).as_posix()
        gm.resolve_asset(task_id, relative)
        if captions and candidate == captions and path.stat().st_size > MAX_BYTES:
            raise ValueError("caption source is too large")
        return {"asset": relative, "sha256": gm.media_sha256(path)}
    mix = narration_mix.file(task_id)
    return {"source_audio": asset(original), "audio": asset(audio), "captions": asset(captions),
            "narration_mix_sha256": gm.media_sha256(mix) if mix.exists() else None}


STYLE_KEYS = {"font_name", "font_size", "text_fore_color", "text_background_color",
              "rounded_subtitle_background", "stroke_color", "stroke_width",
              "subtitle_position", "custom_position", "subtitle_animation"}


def validate_style(style):
    from app.utils import file_security, utils
    if not isinstance(style, dict) or set(style) - STYLE_KEYS:
        raise ValueError("invalid caption style")
    for key, value in style.items():
        if key == "font_name":
            if not isinstance(value, str) or "/" in value or "\\" in value or Path(value).name != value:
                raise ValueError("invalid caption font")
            file_security.resolve_path_within_directory(utils.font_dir(), value)
        elif key in {"text_fore_color", "stroke_color", "text_background_color"}:
            if key == "text_background_color" and value is False:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("caption colors must be six-digit hex colors")
        elif key == "rounded_subtitle_background":
            if type(value) is not bool:
                raise ValueError("invalid caption background")
        elif key in {"font_size", "stroke_width", "custom_position"}:
            limit = {"font_size": (1, 200), "stroke_width": (0, 10), "custom_position": (0, 100)}[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not limit[0] <= value <= limit[1]:
                raise ValueError("caption style value outside limits")
        elif key == "subtitle_position" and value not in {"top", "center", "bottom", "two_thirds_bottom", "custom"}:
            raise ValueError("invalid caption position")
        elif key == "subtitle_animation" and value not in {"none", "pop_spring"}:
            raise ValueError("invalid caption animation")


def validate_spans(cue):
    spans = cue.get("spans", [])
    if not isinstance(spans, list) or len(spans) > 100:
        raise ValueError("too many caption color ranges")
    previous = 0
    for span in spans:
        if (not isinstance(span, dict) or set(span) != {"start", "end", "color"}
                or type(span['start']) is not int or type(span['end']) is not int
                or not previous <= span['start'] < span['end'] <= len(cue['text'])):
            raise ValueError("invalid caption text selection")
        validate_style({"text_fore_color": span['color']})
        previous = span['end']


def validate_cues(cues, duration_ms):
    if type(duration_ms) is not int or not 0 < duration_ms <= 3600000:
        raise ValueError("caption timeline must be at most one hour")
    if not isinstance(cues, list) or len(cues) > MAX_CUES:
        raise ValueError("caption track must contain at most 2000 cues")
    previous = 0
    for cue in cues:
        if (not isinstance(cue, dict) or not {"start_ms", "end_ms", "text"} <= set(cue) or set(cue) - {"start_ms", "end_ms", "text", "style", "spans"}
                or type(cue["start_ms"]) is not int or type(cue["end_ms"]) is not int
                or not previous <= cue["start_ms"] < cue["end_ms"] <= duration_ms):
            raise ValueError("caption cues must be ordered, non-overlapping and within the audio duration")
        text = cue["text"]
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or any(ord(c) < 32 and c != '\n' for c in text)
                or any(c in text for c in ("<", ">", "\x7f"))
                or "\n\n" in text or any(not line.strip() for line in text.splitlines())):
            raise ValueError("caption text must be plain text with 1–2000 characters and no empty lines")
        validate_style(cue.get("style", {}))
        validate_spans(cue)
        previous = cue["end_ms"]
    if len(json.dumps(cues, ensure_ascii=False).encode()) > MAX_BYTES - 4096:
        raise ValueError("caption track is too large")


def srt(cues: list[dict]) -> str:
    return "".join(f"{i}\n{narration_mix._timestamp(c['start_ms'])} --> {narration_mix._timestamp(c['end_ms'])}\n{c['text']}\n\n"
                   for i, c in enumerate(cues, 1))


def parse_srt(content: str) -> list[dict]:
    def timestamp(value):
        h, m, sec, ms = (int(n) for n in re.split(r"[:,]", value))
        if m > 59 or sec > 59:
            raise ValueError("invalid caption timestamp")
        return ((h * 60 + m) * 60 + sec) * 1000 + ms
    result = []
    for block in re.split(r"\n\s*\n", content.lstrip('\ufeff').replace('\r\n', '\n').strip()):
        if not block:
            continue
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError("invalid caption source SRT")
        match = re.fullmatch(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", lines[1])
        if not match:
            raise ValueError("invalid caption source SRT")
        result.append({"start_ms": timestamp(match[1]), "end_ms": timestamp(match[2]), "text": '\n'.join(lines[2:])})
    return result


def load_validated(task_id: str, binding: dict, duration_ms: int, name: str = DRAFT) -> dict:
    data = read(task_id, name)
    if data is None or data.get("binding") != binding or data["duration_ms"] != duration_ms:
        raise ValueError("caption sources changed; restore active captions or prepare a new draft")
    return data


def prepare(task_id: str, binding: dict, duration_ms: int, captions: str, expected_revision: str, *, before_publish=lambda: None) -> dict:
    if revision(task_id) != expected_revision:
        raise ValueError("caption draft changed; refresh the editor")
    try:
        existing = read(task_id)
    except (ValueError, KeyError, TypeError):
        existing = None  # Explicit preparation can recover a damaged draft.
    if existing and existing.get("binding") == binding and existing["duration_ms"] == duration_ms:
        return existing
    cues = parse_srt(Path(captions).read_text(encoding="utf-8")) if captions else []
    validate_cues(cues, duration_ms)
    result = {"schema_version": 1, "binding": binding, "duration_ms": duration_ms, "cues": cues}
    before_publish()
    if revision(task_id) != expected_revision:
        raise ValueError("caption draft changed; refresh the editor")
    save(task_id, DRAFT, result)
    return result


def milliseconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 3600:
        raise ValueError("caption time must be finite seconds")
    return round(value * 1000)


def edit(data: dict, action: str, *, index: int | None = None, start=None, end=None,
         text: str | None = None, split_at=None, second_text: str | None = None,
         style: dict | None = None, spans: list | None = None, scope: str = "cue") -> dict:
    result = json.loads(json.dumps(data))
    cues = result["cues"]
    if action not in {"add", "style"} and (type(index) is not int or not 0 <= index < len(cues)):
        raise ValueError("select an existing caption cue")
    if action == "style":
        validate_style(style)
        if scope == "all":
            result['style'] = style
        elif scope == "cue" and type(index) is int and 0 <= index < len(cues):
            cues[index]['style'] = style
        else:
            raise ValueError("select a caption style scope")
    elif action == "spans":
        cues[index]['spans'] = spans
    elif action in {"add", "update"}:
        cue = {"start_ms": milliseconds(start), "end_ms": milliseconds(end), "text": text}
        if action == "add":
            cues.append(cue)
            cues.sort(key=lambda c: c["start_ms"])
        else:
            old = cues[index]
            if old.get('style'):
                cue['style'] = old['style']
            if old['text'] == text and old.get('spans'):
                cue['spans'] = old['spans']
            cues[index] = cue
    elif action == "remove":
        cues.pop(index)
    elif action == "split":
        cue = cues[index]
        point = milliseconds(split_at)
        if not cue["start_ms"] < point < cue["end_ms"]:
            raise ValueError("split point must be inside the selected cue")
        cue = {k: v for k, v in cue.items() if k != "spans"}
        cues[index:index + 1] = [{**cue, "end_ms": point, "text": text},
                                {**cue, "start_ms": point, "text": second_text}]
    elif action == "merge":
        if index + 1 >= len(cues):
            raise ValueError("select a cue with a following cue to merge")
        first, second = cues[index:index + 2]
        cues[index:index + 2] = [{"start_ms": first["start_ms"], "end_ms": second["end_ms"],
                                "text": first["text"] + "\n" + second["text"], **({"style": first["style"]} if first.get("style") else {})}]
    else:
        raise ValueError("unknown caption edit action")
    validate_cues(cues, data["duration_ms"])
    return result


def stage(task_id: str, data: dict) -> tuple[dict, Path]:
    directory = file(task_id, f"caption_tracks/{uuid.uuid4().hex}/captions.srt").parent
    directory.mkdir(parents=True)
    target = directory / "captions.srt"
    try:
        target.write_bytes(srt(data["cues"]).encode("utf-8"))
        return {**data, "captions_asset": target.relative_to(file(task_id).parent).as_posix(),
                "captions_sha256": gm.media_sha256(target)}, directory
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def resolve(task_id: str, binding: dict, duration_ms: int) -> dict | None:
    if not file(task_id, ACTIVE).exists():
        return None
    data = load_validated(task_id, binding, duration_ms, ACTIVE)
    asset = data.get("captions_asset", "")
    if not isinstance(asset, str) or not re.fullmatch(r"caption_tracks/[a-f0-9]{32}/captions\.srt", asset):
        raise ValueError("invalid independent caption reference")
    candidate = file(task_id, asset)
    if candidate.stat().st_size > MAX_BYTES:
        raise ValueError("active captions are too large")
    content = candidate.read_bytes()
    if hashlib.sha256(content).hexdigest() != data.get("captions_sha256") or content != srt(data["cues"]).encode():
        raise ValueError("active captions changed; restore base captions")
    return data


def cleanup(task_id: str) -> None:
    active = read(task_id, ACTIVE)
    keep = Path(active["captions_asset"]).parts[1] if active else None
    root = file(task_id, "caption_tracks")
    if root.exists():
        for directory in root.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}", directory.name) and directory.name != keep and not directory.is_symlink():
                shutil.rmtree(directory)


def restore(task_id: str, content: bytes | None) -> None:
    target = file(task_id, ACTIVE)
    if content is None:
        target.unlink(missing_ok=True)
        return
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=".caption-track-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def load_preview(task_id: str, binding: dict, duration_ms: int, scene_snapshot: dict, render_settings: str) -> dict | None:
    try:
        data = read(task_id, "caption_preview.json")
        if (data is None or data.get("binding") != binding or data["duration_ms"] != duration_ms
                or data.get("draft_revision") != revision(task_id)
                or data.get("scene_snapshot") != scene_snapshot or data.get("render_settings") != render_settings):
            return None
        asset = data.get("preview_asset", "")
        if not isinstance(asset, str) or not re.fullmatch(r"caption_previews/[a-f0-9]{32}/preview\.mp4", asset):
            return None
        combined = file(task_id, "combined-1.mp4")
        if (gm.media_sha256(combined) != data.get("combined_sha256")
                or gm.media_sha256(file(task_id, asset)) != data.get("preview_sha256")):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None
