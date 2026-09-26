from __future__ import annotations

import os

from .base import GenerationResult, LocalVideoProvider, SceneSpec
from .fake import FakeLocalVideoProvider
from .orchestrator import generate_scene_materials


FAKE_SOURCE_ID = FakeLocalVideoProvider.provider_id
_LOCAL_SOURCE_IDS = {FAKE_SOURCE_ID}


def is_local_ai_source(source: str | None) -> bool:
    return str(source or "") in _LOCAL_SOURCE_IDS


def is_source_enabled(source: str | None) -> bool:
    """Production providers are always explicit; the M1 fake path is opt-in for tests."""

    if source == FAKE_SOURCE_ID:
        return os.getenv("MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER") == "1"
    return False


def create_provider(source: str) -> LocalVideoProvider:
    if source == FAKE_SOURCE_ID:
        if not is_source_enabled(source):
            raise RuntimeError(
                "the fake local AI provider is test-only and is disabled by default"
            )
        return FakeLocalVideoProvider()
    raise ValueError(f"unknown local AI video source: {source}")


__all__ = [
    "FAKE_SOURCE_ID",
    "GenerationResult",
    "LocalVideoProvider",
    "SceneSpec",
    "create_provider",
    "generate_scene_materials",
    "is_local_ai_source",
    "is_source_enabled",
]
