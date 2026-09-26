from __future__ import annotations

import os

from .base import (
    GenerationResult,
    LocalAISceneGenerationError,
    LocalVideoProvider,
    SceneSpec,
)
from .fake import FakeLocalVideoProvider
from .orchestrator import generate_scene_materials
from .wan22 import WAN22_SOURCE_ID, Wan22LocalProvider


FAKE_SOURCE_ID = FakeLocalVideoProvider.provider_id
_LOCAL_SOURCE_IDS = {FAKE_SOURCE_ID, WAN22_SOURCE_ID}


def is_local_ai_source(source: str | None) -> bool:
    return str(source or "") in _LOCAL_SOURCE_IDS


def is_source_enabled(source: str | None) -> bool:
    """Production providers are always explicit; the M1 fake path is opt-in for tests."""

    if source == FAKE_SOURCE_ID:
        return os.getenv("MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER") == "1"
    if source == WAN22_SOURCE_ID:
        return True
    return False


def create_provider(source: str) -> LocalVideoProvider:
    if source == FAKE_SOURCE_ID:
        if not is_source_enabled(source):
            raise RuntimeError(
                "the fake local AI provider is test-only and is disabled by default"
            )
        return FakeLocalVideoProvider()
    if source == WAN22_SOURCE_ID:
        return Wan22LocalProvider()
    raise ValueError(f"unknown local AI video source: {source}")


def prepare_provider(source: str) -> LocalVideoProvider:
    provider = create_provider(source)
    provider.preflight()
    return provider


def preflight_source(source: str) -> None:
    prepare_provider(source)


def scene_duration_limit(provider: LocalVideoProvider, requested: float) -> float:
    provider_limit = getattr(provider, "max_scene_duration", None)
    if provider_limit is None:
        return float(requested)
    return min(float(requested), float(provider_limit))


def provider_base_seed(provider: LocalVideoProvider, default: int = 42) -> int:
    return int(getattr(provider, "base_seed", default))


__all__ = [
    "FAKE_SOURCE_ID",
    "GenerationResult",
    "LocalAISceneGenerationError",
    "WAN22_SOURCE_ID",
    "Wan22LocalProvider",
    "LocalVideoProvider",
    "SceneSpec",
    "create_provider",
    "generate_scene_materials",
    "is_local_ai_source",
    "is_source_enabled",
    "preflight_source",
    "prepare_provider",
    "provider_base_seed",
    "scene_duration_limit",
]
