from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAX_USER_SEED = 2_147_483_647


class LocalAICapabilityError(ValueError):
    """Raised when a user-selected local-AI option is outside a supported domain."""


@dataclass(frozen=True, slots=True)
class LocalAICapability:
    source_id: str
    model_label: str
    backend_label: str
    generation_modes: tuple[str, ...]
    mode_labels: tuple[tuple[str, str], ...]
    aspect_ratios: tuple[str, ...]
    generation_dimensions: tuple[tuple[str, int, int], ...]
    clip_durations: tuple[int, ...]
    default_clip_duration: int
    seed_min: int = 0
    seed_max: int = MAX_USER_SEED
    prompt_max_chars: int = 2000

    def mode_label(self, mode: str) -> str:
        return dict(self.mode_labels).get(mode, str(mode))

    def dimensions_for(self, aspect: str) -> tuple[int, int]:
        for ratio, width, height in self.generation_dimensions:
            if ratio == aspect:
                return width, height
        raise LocalAICapabilityError(
            f"{self.source_id} does not support aspect ratio {aspect}"
        )


_CAPABILITIES = {
    "wan22_local": LocalAICapability(
        source_id="wan22_local",
        model_label="Wan 2.2 TI2V-5B",
        backend_label="Local GPU",
        generation_modes=("fast",),
        mode_labels=(("fast", "Default"),),
        aspect_ratios=("9:16", "16:9"),
        generation_dimensions=(("9:16", 704, 1280), ("16:9", 1280, 704)),
        clip_durations=(2, 3, 4, 5),
        default_clip_duration=3,
    ),
    "ltx25_local": LocalAICapability(
        source_id="ltx25_local",
        model_label="LTX 2.5",
        backend_label="Local GPU",
        generation_modes=("fast", "quality"),
        mode_labels=(("fast", "Fast / Distilled"), ("quality", "Quality / DFR")),
        aspect_ratios=("9:16", "16:9"),
        generation_dimensions=(("9:16", 576, 1024), ("16:9", 1024, 576)),
        clip_durations=(2, 3, 4, 5, 6, 7, 8),
        default_clip_duration=3,
    ),
    "ltx25_hf": LocalAICapability(
        source_id="ltx25_hf",
        model_label="LTX 2.5",
        backend_label="Hugging Face ZeroGPU",
        generation_modes=("fast",),
        mode_labels=(("fast", "Fast / Distilled"),),
        aspect_ratios=("9:16", "16:9"),
        generation_dimensions=(("9:16", 512, 768), ("16:9", 768, 512)),
        clip_durations=(2, 3, 4, 5),
        default_clip_duration=2,
    ),
}


def source_capability(source: str) -> LocalAICapability:
    source_id = str(source or "").strip()
    try:
        return _CAPABILITIES[source_id]
    except KeyError as exc:
        raise LocalAICapabilityError(
            f"unsupported public local AI source: {source_id or '<empty>'}"
        ) from exc


def public_capabilities() -> tuple[LocalAICapability, ...]:
    return tuple(_CAPABILITIES.values())


def validate_generation_request(
    source: str,
    *,
    generation_mode: str,
    aspect: Any,
    clip_duration: Any,
    seed: int | None,
) -> LocalAICapability:
    capability = source_capability(source)
    mode = str(generation_mode or "").strip().lower()
    if mode not in capability.generation_modes:
        allowed = ", ".join(capability.generation_modes)
        raise LocalAICapabilityError(
            f"{capability.model_label} on {capability.backend_label} "
            f"supports generation mode(s): {allowed}"
        )

    aspect_value = str(getattr(aspect, "value", aspect) or "").strip()
    if aspect_value not in capability.aspect_ratios:
        allowed = ", ".join(capability.aspect_ratios)
        raise LocalAICapabilityError(
            f"{capability.model_label} on {capability.backend_label} "
            f"supports aspect ratio(s): {allowed}"
        )

    try:
        duration = int(clip_duration)
    except (TypeError, ValueError) as exc:
        raise LocalAICapabilityError("local AI clip duration must be an integer") from exc
    if duration not in capability.clip_durations:
        allowed = ", ".join(str(value) for value in capability.clip_durations)
        raise LocalAICapabilityError(
            f"{capability.model_label} on {capability.backend_label} "
            f"supports clip duration(s): {allowed} seconds"
        )

    if seed is not None:
        try:
            seed_value = int(seed)
        except (TypeError, ValueError) as exc:
            raise LocalAICapabilityError("local AI seed must be an integer") from exc
        if not capability.seed_min <= seed_value <= capability.seed_max:
            raise LocalAICapabilityError(
                f"local AI seed must be between {capability.seed_min} "
                f"and {capability.seed_max}"
            )

    return capability
