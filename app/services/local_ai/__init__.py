from __future__ import annotations

from .base import GenerationResult, LocalVideoProvider, SceneSpec
from .fake import FakeLocalVideoProvider
from .orchestrator import generate_scene_materials


FAKE_SOURCE_ID = FakeLocalVideoProvider.provider_id
_LOCAL_SOURCE_IDS = {FAKE_SOURCE_ID}


def is_local_ai_source(source: str | None) -> bool:
    return str(source or "") in _LOCAL_SOURCE_IDS


def create_provider(source: str) -> LocalVideoProvider:
    if source == FAKE_SOURCE_ID:
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
]
