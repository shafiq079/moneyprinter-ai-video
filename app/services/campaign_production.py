"""Durable campaign input snapshots; existing task services still own generation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.config import config
from app.models.schema import VideoParams
from app.services import bgm, generation_manifest as gm, loomloom
from app.utils import utils

SOURCES = {
    "pexels",
    "pixabay",
    "coverr",
    "wavespeed",
    "volcengine_seedance",
    "ofox",
    "metaso_minimax",
    "muapi",
    "loomloom",
    "openai_image",
    "wan22_local",
    "ltx25_local",
    "ltx25_hf",
    "local",
}
PAID = {
    "wavespeed",
    "volcengine_seedance",
    "ofox",
    "metaso_minimax",
    "muapi",
    "loomloom",
    "openai_image",
}
AUDIO_OPTIONS = {
    "elevenlabs": ("model_id",),
    "fish_audio": ("model",),
    "voxcpm": ("model_id",),
    "chatterbox": ("model_id",),
    "kokoro": ("model_id",),
    "minimax_tts": ("model_id",),
}


def inputs_root():
    root = Path(utils.storage_dir("social/campaign-inputs", create=True))
    if root.is_symlink():
        raise ValueError("Invalid campaign input storage.")
    return root


def asset(record):
    if not isinstance(record, dict) or "asset" not in record or "sha256" not in record:
        raise ValueError(
            "Campaign uploaded input has not been retained. Save settings through the campaign editor."
        )
    name = record["asset"]
    if not re.fullmatch(r"[a-f0-9]{32}/[a-z0-9-]+\.[a-zA-Z0-9]+", name):
        raise ValueError("Invalid campaign input reference.")
    target = inputs_root() / name
    if (
        target.is_symlink()
        or target.parent.is_symlink()
        or not target.is_file()
        or gm.media_sha256(target) != record["sha256"]
    ):
        raise ValueError(
            "Campaign input is missing or changed. Reopen production settings and upload it again."
        )
    return target


def capture(
    params,
    staging_task,
    *,
    request=None,
    reference=None,
    prompt_audio=None,
    prompt_text="",
    quote_summary=None,
):
    """Only called after the generator has validated/staged its uploads."""
    value = {"params": params.model_dump(mode="json"), "inputs": {}, "runtime": {}}
    input_id = uuid.uuid4().hex
    directory = inputs_root() / input_id

    def retain(name, source=None, content=None):
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / name
        if source is not None:
            source = Path(source)
            allowed = [
                Path(utils.task_dir(staging_task)),
                Path(utils.storage_dir("local_videos")),
                inputs_root(),
            ]
            if source.is_symlink() or not any(
                source.resolve().is_relative_to(p.resolve()) for p in allowed
            ):
                raise ValueError(
                    "Campaign uploads must come from the current settings upload."
                )
            if source.stat().st_size > 200 * 1024 * 1024:
                raise ValueError("Campaign input exceeds 200 MiB.")
            shutil.copyfile(source, target)
        else:
            if len(content) > 64 * 1024 * 1024:
                raise ValueError("Campaign reference audio exceeds 64 MiB.")
            target.write_bytes(content)
        target.chmod(0o600)
        return {"asset": input_id + "/" + name, "sha256": gm.media_sha256(target)}

    if params.custom_audio_file:
        record = retain(
            "narration" + Path(params.custom_audio_file).suffix,
            source=params.custom_audio_file,
        )
        value["inputs"]["audio"] = record
        value["params"]["custom_audio_file"] = str(asset(record))
    if params.video_materials:
        value["inputs"]["materials"] = []
        for n, item in enumerate(value["params"]["video_materials"]):
            record = retain(
                f"material-{n}" + Path(item["url"]).suffix, source=item["url"]
            )
            value["inputs"]["materials"].append(record)
            item["url"] = str(asset(record))
    for name, content in [("reference", reference), ("prompt", prompt_audio)]:
        if content:
            value["inputs"][name] = retain(name + ".wav", content=bytes(content))
    value["prompt_text"] = str(prompt_text or "")
    if params.bgm_file:
        filename = bgm.resolve_bgm_file(params.bgm_file)
        if not filename:
            raise ValueError("Background music is unavailable.")
        value["bgm_sha256"] = gm.media_sha256(Path(filename))
    for section, keys in AUDIO_OPTIONS.items():
        value["runtime"][section] = {
            key: copy.deepcopy(
                config.snapshot_config_with_pending(getattr(config, section)).get(key)
            )
            for key in keys
            if key in getattr(config, section)
        }
    # Only non-secret provider rendering options. Endpoints and credentials remain
    # operator-owned and are deliberately excluded from durable campaign state.
    value["runtime"]["app"] = {
        k: copy.deepcopy(v)
        for k, v in config.snapshot_config_with_pending(config.app).items()
        if k.startswith(
            (
                "wavespeed_",
                "volcengine_",
                "ofox_",
                "metaso_minimax_",
                "muapi_",
                "openai_image_",
            )
        )
        and k.endswith(
            (
                "_model",
                "_model_id",
                "_resolution",
                "_fps",
                "_duration",
                "_steps",
                "_guidance_scale",
            )
        )
        and isinstance(v, (str, int, float, bool))
    }
    if request is not None:
        value["quote"] = {
            "rows": list(request.batch.input_rows),
            "listing_version_id": request.listing_version_id,
            "client_request_id": request.client_request_id,
            "binding": script_binding(VideoParams.model_validate(value["params"])),
            "endpoint": hashlib.sha256(request.settings.base_url.encode()).hexdigest(),
            "listing": request.settings.market_listing_id,
            "summary": copy.deepcopy(quote_summary or {}),
        }
    return value


def script_binding(params):
    return hashlib.sha256(
        json.dumps(params.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()


def validate_inputs(package, params):
    if set(package) - {
        "params",
        "inputs",
        "runtime",
        "prompt_text",
        "quote",
        "bgm_sha256",
    }:
        raise ValueError("Invalid campaign production metadata.")
    for section, values in package.get("runtime", {}).items():
        for key, value in values.items():
            if not allowed_option(section, key) or not isinstance(
                value, (str, int, float, bool, type(None))
            ):
                raise ValueError("Invalid campaign runtime option.")
    inputs = package.get("inputs", {})
    if params.custom_audio_file:
        if str(asset(inputs.get("audio", {}))) != params.custom_audio_file:
            raise ValueError("Campaign narration does not match its saved input.")
    if params.video_materials:
        records = inputs.get("materials", [])
        if len(records) != len(params.video_materials) or any(
            str(asset(r)) != m.url
            for r, m in zip(records, params.video_materials, strict=True)
        ):
            raise ValueError("Campaign footage does not match its saved inputs.")
    for name in ("reference", "prompt"):
        if name in inputs:
            asset(inputs[name])
    if params.bgm_file:
        filename = bgm.resolve_bgm_file(params.bgm_file)
        if not filename or gm.media_sha256(Path(filename)) != package.get("bgm_sha256"):
            raise ValueError("Campaign background music changed. Save settings again.")
    return package


def requires_charge(params):
    return params.video_source in PAID or params.bgm_type in {"sonilo", "elevenlabs"}


def worker_inputs(package, params, tid):
    validate_inputs(package, params)
    result = {}
    inputs = package.get("inputs", {})
    if params.custom_audio_file:
        original = asset(inputs["audio"])
        target = Path(utils.task_dir(tid)) / ("custom-audio" + original.suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        params.custom_audio_file = str(target)
    for name, key in [
        ("reference", "voxcpm_reference_audio"),
        ("prompt", "voxcpm_prompt_audio"),
    ]:
        if name in inputs:
            result[key] = asset(inputs[name]).read_bytes()
    if package.get("prompt_text"):
        result["voxcpm_prompt_text"] = package["prompt_text"]
    if params.video_source == "loomloom":
        q = package.get("quote")
        # Recheck before task-local audio path changes affect the parameter hash.
        bound = params.model_copy(
            update={"custom_audio_file": package["params"].get("custom_audio_file")}
        )
        if not q or q["binding"] != script_binding(bound):
            raise ValueError("This video needs its own current LoomLoom quote.")
        settings = loomloom.video_settings_from_mapping(
            config.snapshot_config_with_pending(config.app)
        )
        if (
            hashlib.sha256(settings.base_url.encode()).hexdigest() != q["endpoint"]
            or settings.market_listing_id != q["listing"]
        ):
            raise ValueError(
                "Quoted provider configuration changed; obtain a new quote."
            )
        request = loomloom.LoomLoomConfirmedVideoRequest(
            settings=settings,
            batch=loomloom.LoomLoomVideoBatch(tuple(q["rows"])),
            listing_version_id=q["listing_version_id"],
            client_request_id=q["client_request_id"],
        )
        request.validate()
        result["loomloom_video_request"] = request
    return result


def allowed_option(section, key):
    if section == "app":
        return key == "video_codec" or (
            key.startswith(
                (
                    "wavespeed_",
                    "volcengine_",
                    "ofox_",
                    "metaso_minimax_",
                    "muapi_",
                    "openai_image_",
                )
            )
            and key.endswith(
                (
                    "_model",
                    "_model_id",
                    "_resolution",
                    "_fps",
                    "_duration",
                    "_steps",
                    "_guidance_scale",
                )
            )
        )
    return key in AUDIO_OPTIONS.get(section, ())


@contextmanager
def runtime_options(package):
    """Caller holds the generation runtime lock; restore before its exit flush."""
    originals = []
    try:
        for section, values in package.get("runtime", {}).items():
            for key, value in values.items():
                if not allowed_option(section, key):
                    raise ValueError("Invalid campaign runtime option.")
                target = getattr(config, section)
                originals.append((target, key, key in target, target.get(key)))
                target[key] = value
        yield
    finally:
        for target, key, present, value in reversed(originals):
            if present:
                target[key] = value
            else:
                target.pop(key, None)
