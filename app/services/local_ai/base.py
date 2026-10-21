from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


_ALLOWED_ASPECTS = {"16:9", "9:16", "1:1"}
_ALLOWED_BEATS = {"hook", "setup", "build", "reveal", "payoff", "cta", "ending"}


@dataclass(frozen=True, slots=True)
class SceneSpec:
    """Provider-neutral description of one generated visual scene."""

    scene_id: int
    narration_segment: str
    prompt: str
    target_duration: float
    aspect: str
    seed: int
    beat: str = "build"
    negative_prompt: str = ""
    continuity: str = ""
    camera: str = ""
    provider_settings: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scene_id < 1:
            raise ValueError("scene_id must be >= 1")
        if not str(self.prompt or "").strip():
            raise ValueError("scene prompt must not be empty")
        if not math.isfinite(float(self.target_duration)) or self.target_duration <= 0:
            raise ValueError("scene target_duration must be a positive finite number")
        if self.aspect not in _ALLOWED_ASPECTS:
            raise ValueError(f"unsupported scene aspect: {self.aspect}")
        if self.beat not in _ALLOWED_BEATS:
            raise ValueError(f"unsupported scene beat: {self.beat}")
        if not isinstance(self.provider_settings, dict):
            raise ValueError("scene provider_settings must be a dictionary")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Validated local clip metadata returned by a provider."""

    output_path: Path
    actual_duration: float
    width: int
    height: int
    provider_id: str
    model_fingerprint: str


class LocalAICancellationRequested(RuntimeError):
    """Raised at a safe local-AI scene boundary after cancellation is requested."""


class LocalAISceneGenerationError(RuntimeError):
    """Safe scene-scoped failure suitable for task state and API responses."""

    def __init__(
        self,
        *,
        provider_id: str,
        scene_id: int,
        cause_type: str,
        error_code: str,
    ) -> None:
        self.provider_id = str(provider_id)
        self.scene_id = int(scene_id)
        self.cause_type = str(cause_type)
        self.error_code = str(error_code)
        super().__init__(
            f"provider={self.provider_id}, scene_id={self.scene_id}, "
            f"error_code={self.error_code}, cause={self.cause_type}"
        )


class LocalVideoProvider(Protocol):
    """Minimal model-provider contract. Orchestration owns retries and persistence."""

    provider_id: str
    model_fingerprint: str

    def preflight(self) -> None: ...

    def load_runtime(self) -> None: ...

    def generate(self, scene: SceneSpec, output_path: Path) -> None: ...

    def validate_output(
        self, output_path: Path, scene: SceneSpec
    ) -> GenerationResult: ...

    def unload(self) -> None: ...


def scene_fingerprint(
    scene: SceneSpec,
    *,
    provider_id: str,
    model_fingerprint: str,
) -> str:
    """Return a stable fingerprint for every input that can change scene media."""

    payload = {
        "schema_version": 2,
        "provider_id": provider_id,
        "model_fingerprint": model_fingerprint,
        "scene": scene.to_dict(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
