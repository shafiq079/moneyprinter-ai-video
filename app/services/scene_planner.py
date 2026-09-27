from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loguru import logger

from app.services import llm
from app.services.local_ai.base import SceneSpec
from app.utils import utils


SCENE_PLAN_SCHEMA_VERSION = 1
SCENE_DIRECTOR_VERSION = "scene-director-v1"
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?", re.UNICODE)
_ALLOWED_BEATS = {"hook", "setup", "build", "reveal", "payoff", "cta", "ending"}
_PROMPT_LIMIT = 1800
_VISUAL_BIBLE_LIMIT = 900
_CONTINUITY_LIMIT = 500
_CAMERA_LIMIT = 240
_NEGATIVE_PROMPT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ScenePlan:
    """Canonical visual plan created after narration duration is known."""

    idea: str
    story_arc: str
    visual_bible: str
    source: str
    input_fingerprint: str
    scenes: tuple[SceneSpec, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCENE_PLAN_SCHEMA_VERSION,
            "director_version": SCENE_DIRECTOR_VERSION,
            "input_fingerprint": self.input_fingerprint,
            "source": self.source,
            "idea": self.idea,
            "story_arc": self.story_arc,
            "visual_bible": self.visual_bible,
            "scenes": [scene.to_dict() for scene in self.scenes],
        }


def scene_plan_path(task_id: str) -> Path:
    return Path(utils.task_dir(task_id)) / "scene_plan.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".scene-plan-",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _clean_text(value: object, limit: int) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned[:limit].rstrip()


def _normalized_script(text: str) -> str:
    return " ".join(utils.remove_pause_tags(str(text or "")).split()).strip()


def _split_narration(text: str, count: int) -> list[str]:
    cleaned = _normalized_script(text)
    if not cleaned:
        return ["Visual scene"] * count

    sentences = [
        part.strip()
        for part in _SENTENCE_RE.findall(cleaned)
        if part.strip()
    ]
    words = cleaned.split()
    # Prefer sentence-sized beats only when there are enough of them to populate
    # all scenes. Otherwise split smaller units so no scene repeats the full script.
    if len(sentences) >= count:
        units = sentences
        separator = " "
    elif len(words) >= count:
        units = words
        separator = " "
    else:
        characters = [char for char in cleaned if not char.isspace()]
        units = characters if characters else [cleaned]
        separator = ""

    buckets: list[list[str]] = [[] for _ in range(count)]
    for index, unit in enumerate(units):
        bucket = min(count - 1, (index * count) // max(1, len(units)))
        buckets[bucket].append(unit)

    segments = [separator.join(bucket).strip() for bucket in buckets]
    return [segment or cleaned for segment in segments]


def _default_beat(index: int, count: int) -> str:
    if index == 0:
        return "hook"
    if index == count - 1:
        return "ending"
    if index == 1:
        return "setup"
    if index == count - 2 and count > 3:
        return "payoff"
    if index >= max(2, math.ceil(count * 0.6)):
        return "reveal"
    return "build"


def _camera_for_beat(beat: str) -> str:
    return {
        "hook": "dynamic close-up with a controlled push-in",
        "setup": "clear establishing wide shot with a slow dolly",
        "build": "medium tracking shot with natural subject motion",
        "reveal": "revealing close-up with a gentle orbit",
        "payoff": "hero medium-wide shot with a slow push-in",
        "cta": "clean direct medium shot with restrained movement",
        "ending": "cinematic closing wide shot with a gentle pull-back",
    }.get(beat, "cinematic medium shot with restrained camera motion")


def _aspect_direction(aspect: str) -> str:
    return {
        "9:16": "vertical 9:16 composition with a clear central subject",
        "16:9": "cinematic 16:9 landscape composition",
        "1:1": "balanced square 1:1 composition",
    }.get(aspect, f"{aspect} composition")


def _normalize_durations(
    total_duration: float,
    count: int,
    max_scene_duration: float,
) -> list[float]:
    beat_weights = {
        "hook": 0.88,
        "setup": 1.02,
        "build": 1.08,
        "reveal": 0.92,
        "payoff": 1.05,
        "cta": 0.92,
        "ending": 0.9,
    }
    weights = [
        beat_weights[_default_beat(index, count)]
        for index in range(count)
    ]
    weight_total = sum(weights)
    values = [
        total_duration * weight / weight_total
        for weight in weights
    ]
    values = [min(max_scene_duration, value) for value in values]

    for _ in range(30):
        difference = total_duration - sum(values)
        if abs(difference) < 0.0005:
            break
        candidates = [
            index
            for index, value in enumerate(values)
            if value < max_scene_duration - 0.0005
        ]
        if not candidates:
            break
        share = difference / len(candidates)
        for index in candidates:
            values[index] = min(
                max_scene_duration,
                values[index] + share,
            )

    rounded = [round(value, 3) for value in values]
    remainder = round(total_duration - sum(rounded), 3)
    if remainder:
        for index in reversed(range(len(rounded))):
            candidate = round(rounded[index] + remainder, 3)
            if 0 < candidate <= max_scene_duration + 1e-6:
                rounded[index] = candidate
                remainder = 0
                break
    if abs(sum(rounded) - total_duration) > 0.01:
        raise ValueError("scene durations do not cover narration duration")
    return rounded


def _planning_fingerprint(
    *,
    video_subject: str,
    video_script: str,
    audio_duration: float,
    max_scene_duration: float,
    aspect: str,
    base_seed: int,
    provider_settings: dict[str, object] | None = None,
) -> str:
    payload = {
        "schema_version": SCENE_PLAN_SCHEMA_VERSION,
        "director_version": SCENE_DIRECTOR_VERSION,
        "video_subject": _clean_text(video_subject, 500),
        "video_script": _normalized_script(video_script),
        "audio_duration": round(float(audio_duration), 3),
        "max_scene_duration": round(float(max_scene_duration), 3),
        "aspect": str(aspect),
        "base_seed": int(base_seed),
    }
    if provider_settings:
        payload["provider_settings"] = dict(provider_settings)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _fallback_visual_bible(subject: str, aspect: str) -> str:
    subject_rule = (
        f"Keep the appearance and visual identity of {subject} consistent "
        "across scenes."
        if subject
        else "Keep recurring subjects visually consistent across scenes."
    )
    return (
        "Cinematic realism with coherent natural lighting, one stable color "
        f"palette, and {_aspect_direction(aspect)}. {subject_rule} "
        "Use clean imagery without embedded text, captions, logos, or watermarks."
    )


def _fallback_plan(
    *,
    video_subject: str,
    video_script: str,
    audio_duration: float,
    max_scene_duration: float,
    aspect: str,
    base_seed: int,
    input_fingerprint: str,
    source: str,
    provider_settings: dict[str, object] | None = None,
) -> ScenePlan:
    scene_count = max(1, math.ceil(audio_duration / max_scene_duration))
    durations = _normalize_durations(
        audio_duration,
        scene_count,
        max_scene_duration,
    )
    narration_segments = _split_narration(video_script, scene_count)
    subject = _clean_text(video_subject, 240)
    visual_bible = _fallback_visual_bible(subject, aspect)
    scenes: list[SceneSpec] = []

    for index, (segment, duration) in enumerate(
        zip(narration_segments, durations, strict=True)
    ):
        beat = _default_beat(index, scene_count)
        camera = _camera_for_beat(beat)
        continuity = (
            "Establish the main subject, environment, lighting, and palette clearly."
            if index == 0
            else (
                "Maintain subject identity, environment logic, lighting, palette, "
                "and movement direction from the previous scene."
            )
        )
        subject_clause = (
            f"Show {subject} in one concrete visible action"
            if subject
            else "Show one concrete visible action"
        )
        prompt = (
            f"{camera}. {subject_clause} that directly illustrates this narration "
            f"beat: {segment} {continuity} Project visual bible: {visual_bible} "
            "Do not add factual details that are not present in the narration. "
            "No titles, captions, logos, watermarks, UI, or readable text."
        )
        scenes.append(
            SceneSpec(
                scene_id=index + 1,
                narration_segment=segment,
                prompt=_clean_text(prompt, _PROMPT_LIMIT),
                target_duration=duration,
                aspect=aspect,
                seed=int(base_seed) + index,
                beat=beat,
                negative_prompt=(
                    "titles, captions, logos, watermarks, readable text, "
                    "duplicated subjects, distorted anatomy, broken geometry"
                ),
                continuity=_clean_text(continuity, _CONTINUITY_LIMIT),
                camera=_clean_text(camera, _CAMERA_LIMIT),
                provider_settings=dict(provider_settings or {}),
            )
        )

    idea = (
        f"A visually coherent short about {subject}"
        if subject
        else "A visually coherent short matching the supplied narration"
    )
    return ScenePlan(
        idea=idea,
        story_arc=(
            "Hook, establish the subject, develop the central idea, reveal the "
            "key point, then close clearly."
        ),
        visual_bible=visual_bible,
        source=source,
        input_fingerprint=input_fingerprint,
        scenes=tuple(scenes),
    )


def build_director_prompt(
    *,
    video_subject: str,
    fallback_plan: ScenePlan,
) -> str:
    fixed_scenes = [
        {
            "scene_id": scene.scene_id,
            "narration_segment": scene.narration_segment,
            "target_duration": scene.target_duration,
            "beat_hint": scene.beat,
        }
        for scene in fallback_plan.scenes
    ]
    fixed_json = json.dumps(fixed_scenes, ensure_ascii=False, indent=2)
    aspect = fallback_plan.scenes[0].aspect if fallback_plan.scenes else "9:16"
    subject = _clean_text(video_subject, 500) or "(use the supplied narration)"
    return f"""
Act as a senior short-form video director. Direct visuals for an already-recorded narration.

Video subject: {subject}
Aspect: {aspect}

The narration is already generated and timed. You MUST NOT rewrite, summarize,
reorder, merge, split, or add narration. The scene IDs, narration segments, and
target durations below are fixed:
{fixed_json}

Return one JSON object only with these top-level keys:
- idea: short creative direction
- story_arc: one sentence describing visual progression
- visual_bible: stable subject identity, environment logic, lighting, palette,
  realism/stylization, and overall visual language
- scenes: exactly one object for every supplied scene_id

Each scene object must contain:
- scene_id
- beat: one of hook, setup, build, reveal, payoff, cta, ending
- prompt: one concrete generatable shot that directly represents that fixed
  narration segment
- camera: one compatible shot scale/camera movement
- continuity: what must stay visually consistent from the previous scene
- negative_prompt: short visual exclusions

Rules:
1. Keep the first beat as hook and normally close with ending unless the fixed
   narration clearly contains a natural CTA.
2. State visible subject, action, environment, lighting, and camera only when useful.
3. Maintain recurring subject identity and visual continuity through one visual bible.
4. Do not render titles, subtitles, captions, logos, watermarks, UI, charts with
   text, or other readable on-screen text.
5. Do not invent factual details, numbers, names, dates, quotes, products, places,
   or claims that are not present in the fixed narration.
6. Prompts must be readable and concise rather than keyword dumps or inflated jargon.
7. Output prompts in English where practical, while preserving named entities accurately.
8. Return JSON only. Do not include Markdown fences or commentary.
""".strip()


def _normalize_director_payload(
    payload: dict[str, Any],
    *,
    fallback_plan: ScenePlan,
) -> ScenePlan:
    raw_scenes = payload.get("scenes")
    if (
        not isinstance(raw_scenes, list)
        or len(raw_scenes) != len(fallback_plan.scenes)
    ):
        raise ValueError("director returned the wrong scene count")

    by_id: dict[int, dict[str, Any]] = {}
    for item in raw_scenes:
        if not isinstance(item, dict):
            raise ValueError("director returned an invalid scene")
        try:
            scene_id = int(item.get("scene_id"))
        except (TypeError, ValueError):
            raise ValueError("director returned an invalid scene_id") from None
        if scene_id in by_id:
            raise ValueError("director returned duplicate scene_id values")
        by_id[scene_id] = item

    expected_ids = {scene.scene_id for scene in fallback_plan.scenes}
    if set(by_id) != expected_ids:
        raise ValueError("director scene IDs do not match the fixed plan")

    visual_bible = _clean_text(
        payload.get("visual_bible") or fallback_plan.visual_bible,
        _VISUAL_BIBLE_LIMIT,
    )
    idea = _clean_text(
        payload.get("idea") or fallback_plan.idea,
        500,
    )
    story_arc = _clean_text(
        payload.get("story_arc") or fallback_plan.story_arc,
        900,
    )
    directed_scenes: list[SceneSpec] = []

    for index, fixed in enumerate(fallback_plan.scenes):
        item = by_id[fixed.scene_id]
        beat = _clean_text(item.get("beat"), 40).lower()
        if beat not in _ALLOWED_BEATS:
            beat = fixed.beat
        if index == 0:
            beat = "hook"
        elif (
            index == len(fallback_plan.scenes) - 1
            and beat not in {"cta", "ending"}
        ):
            beat = "ending"

        camera = _clean_text(
            item.get("camera") or fixed.camera,
            _CAMERA_LIMIT,
        )
        continuity = _clean_text(
            item.get("continuity") or fixed.continuity,
            _CONTINUITY_LIMIT,
        )
        negative_prompt = _clean_text(
            item.get("negative_prompt") or fixed.negative_prompt,
            _NEGATIVE_PROMPT_LIMIT,
        )
        raw_prompt = _clean_text(item.get("prompt"), 1000)
        if not raw_prompt:
            raise ValueError(
                f"director returned an empty prompt for scene {fixed.scene_id}"
            )

        final_prompt = _clean_text(
            (
                f"{raw_prompt} Camera: {camera}. Visual continuity: {continuity}. "
                f"Project visual bible: {visual_bible}. "
                "Do not add factual details beyond the narration. "
                "No titles, captions, logos, watermarks, UI, or readable text."
            ),
            _PROMPT_LIMIT,
        )
        directed_scenes.append(
            SceneSpec(
                scene_id=fixed.scene_id,
                narration_segment=fixed.narration_segment,
                prompt=final_prompt,
                target_duration=fixed.target_duration,
                aspect=fixed.aspect,
                seed=fixed.seed,
                beat=beat,
                negative_prompt=negative_prompt,
                continuity=continuity,
                camera=camera,
                provider_settings=dict(fixed.provider_settings),
            )
        )

    return ScenePlan(
        idea=idea,
        story_arc=story_arc,
        visual_bible=visual_bible,
        source="configured_llm",
        input_fingerprint=fallback_plan.input_fingerprint,
        scenes=tuple(directed_scenes),
    )


def _scene_from_payload(value: dict[str, Any]) -> SceneSpec:
    provider_settings = value.get("provider_settings")
    if not isinstance(provider_settings, dict):
        provider_settings = {}
    return SceneSpec(
        scene_id=int(value["scene_id"]),
        narration_segment=str(value.get("narration_segment") or ""),
        prompt=str(value["prompt"]),
        target_duration=float(value["target_duration"]),
        aspect=str(value["aspect"]),
        seed=int(value["seed"]),
        beat=str(value.get("beat") or "build"),
        negative_prompt=str(value.get("negative_prompt") or ""),
        continuity=str(value.get("continuity") or ""),
        camera=str(value.get("camera") or ""),
        provider_settings=provider_settings,
    )


def load_scene_plan(task_id: str) -> ScenePlan | None:
    path = scene_plan_path(task_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("scene plan is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCENE_PLAN_SCHEMA_VERSION
        or payload.get("director_version") != SCENE_DIRECTOR_VERSION
        or not isinstance(payload.get("scenes"), list)
    ):
        raise ValueError("unsupported scene plan schema")
    try:
        scenes = tuple(
            _scene_from_payload(item)
            for item in payload["scenes"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("scene plan contains invalid scenes") from exc
    if not scenes:
        raise ValueError("scene plan contains no scenes")
    return ScenePlan(
        idea=str(payload.get("idea") or ""),
        story_arc=str(payload.get("story_arc") or ""),
        visual_bible=str(payload.get("visual_bible") or ""),
        source=str(payload.get("source") or "unknown"),
        input_fingerprint=str(payload.get("input_fingerprint") or ""),
        scenes=scenes,
    )


def save_scene_plan(task_id: str, plan: ScenePlan) -> None:
    _atomic_write_json(scene_plan_path(task_id), plan.to_dict())


def replace_scene_in_plan(
    plan: ScenePlan,
    replacement: SceneSpec,
    *,
    source: str,
) -> ScenePlan:
    """Replace one scene while preserving project-level direction."""

    scenes: list[SceneSpec] = []
    replaced = False
    for scene in plan.scenes:
        if scene.scene_id == replacement.scene_id:
            scenes.append(replacement)
            replaced = True
        else:
            scenes.append(scene)
    if not replaced:
        raise KeyError(
            f"scene {replacement.scene_id} is missing from scene plan"
        )
    return ScenePlan(
        idea=plan.idea,
        story_arc=plan.story_arc,
        visual_bible=plan.visual_bible,
        source=str(source),
        input_fingerprint=plan.input_fingerprint,
        scenes=tuple(scenes),
    )


def revise_scene_plan(
    plan: ScenePlan,
    scene_id: int,
    *,
    prompt: str | None = None,
    seed: int | None = None,
) -> tuple[ScenePlan, SceneSpec]:
    """Return a manual scene revision without changing narration/timing."""

    revised: list[SceneSpec] = []
    target: SceneSpec | None = None
    for scene in plan.scenes:
        if scene.scene_id != int(scene_id):
            revised.append(scene)
            continue

        next_prompt = (
            _clean_text(prompt, _PROMPT_LIMIT)
            if prompt is not None
            else scene.prompt
        )
        if not next_prompt:
            raise ValueError("scene prompt must not be empty")
        next_seed = scene.seed if seed is None else int(seed)
        if next_seed < 0:
            raise ValueError("scene seed must be >= 0")

        target = replace(
            scene,
            prompt=next_prompt,
            seed=next_seed,
        )
        revised.append(target)

    if target is None:
        raise KeyError(f"scene {scene_id} is missing from scene plan")

    return (
        ScenePlan(
            idea=plan.idea,
            story_arc=plan.story_arc,
            visual_bible=plan.visual_bible,
            source="manual_edit",
            input_fingerprint=plan.input_fingerprint,
            scenes=tuple(revised),
        ),
        target,
    )


def get_or_create_scene_plan(
    task_id: str,
    video_script: str,
    *,
    video_subject: str = "",
    audio_duration: float,
    max_scene_duration: float,
    aspect: str,
    base_seed: int = 42,
    provider_settings: dict[str, object] | None = None,
    use_llm: bool = True,
) -> ScenePlan:
    """Reuse a matching plan or create visual direction exactly once."""

    duration = float(audio_duration)
    max_duration = float(max_scene_duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("audio_duration must be a positive finite number")
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("max_scene_duration must be a positive finite number")

    fingerprint = _planning_fingerprint(
        video_subject=video_subject,
        video_script=video_script,
        audio_duration=duration,
        max_scene_duration=max_duration,
        aspect=aspect,
        base_seed=base_seed,
        provider_settings=provider_settings,
    )
    try:
        existing = load_scene_plan(task_id)
    except ValueError as exc:
        logger.warning(
            f"discard invalid scene plan for task {task_id}: {exc}"
        )
        existing = None
    if (
        existing is not None
        and existing.input_fingerprint == fingerprint
    ):
        return existing

    fallback = _fallback_plan(
        video_subject=video_subject,
        video_script=video_script,
        audio_duration=duration,
        max_scene_duration=max_duration,
        aspect=aspect,
        base_seed=base_seed,
        input_fingerprint=fingerprint,
        source="deterministic",
        provider_settings=provider_settings,
    )
    plan = fallback
    if use_llm:
        try:
            payload = llm.generate_json_response(
                build_director_prompt(
                    video_subject=video_subject,
                    fallback_plan=fallback,
                )
            )
            plan = _normalize_director_payload(
                payload,
                fallback_plan=fallback,
            )
        except Exception as exc:
            logger.warning(
                "scene director LLM failed; use deterministic visual plan: "
                f"task_id={task_id}, error={type(exc).__name__}: {exc}"
            )
            plan = ScenePlan(
                idea=fallback.idea,
                story_arc=fallback.story_arc,
                visual_bible=fallback.visual_bible,
                source="deterministic_fallback",
                input_fingerprint=fallback.input_fingerprint,
                scenes=fallback.scenes,
            )

    save_scene_plan(task_id, plan)
    return plan


def plan_scenes(
    video_script: str,
    *,
    audio_duration: float,
    max_scene_duration: float,
    aspect: str,
    base_seed: int = 42,
) -> list[SceneSpec]:
    """Backward-compatible deterministic planner for CPU-safe callers."""

    duration = float(audio_duration)
    max_duration = float(max_scene_duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("audio_duration must be a positive finite number")
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("max_scene_duration must be a positive finite number")

    fingerprint = _planning_fingerprint(
        video_subject="",
        video_script=video_script,
        audio_duration=duration,
        max_scene_duration=max_duration,
        aspect=aspect,
        base_seed=base_seed,
        provider_settings=None,
    )
    return list(
        _fallback_plan(
            video_subject="",
            video_script=video_script,
            audio_duration=duration,
            max_scene_duration=max_duration,
            aspect=aspect,
            base_seed=base_seed,
            input_fingerprint=fingerprint,
            source="deterministic",
            provider_settings=None,
        ).scenes
    )
