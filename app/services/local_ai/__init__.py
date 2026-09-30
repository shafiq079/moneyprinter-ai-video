from __future__ import annotations

import os
import tempfile

from .capabilities import (
    LocalAICapability,
    LocalAICapabilityError,
    MAX_USER_SEED,
    public_capabilities,
    source_capability,
    validate_generation_request,
)
from .base import (
    GenerationResult,
    LocalAICancellationRequested,
    LocalAISceneGenerationError,
    LocalVideoProvider,
    SceneSpec,
)
from .fake import FakeLocalVideoProvider
from .orchestrator import generate_scene_materials, regenerate_scene_material
from .ltx25 import (
    LTX25_SOURCE_ID,
    LTX25ConfigurationError,
    LTX25LocalProvider,
    LTX25WorkerError,
)
from .ltx25_hf import (
    LTX25_HF_SOURCE_ID,
    LTX25HFConfigurationError,
    LTX25HFProvider,
)
from .remote_gpu.huggingface import HuggingFaceRemoteError
from app.utils import utils

from .wan22 import (
    WAN22_SOURCE_ID,
    Wan22ConfigurationError,
    Wan22LocalProvider,
    Wan22WorkerError,
)


class LocalAIStorageError(RuntimeError):
    """Raised when local AI task storage cannot safely accept generated assets."""


def validate_output_storage() -> None:
    """Prove task storage is writable before script/TTS/GPU work starts."""

    try:
        task_root = utils.task_dir()
        os.makedirs(task_root, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".local-ai-preflight-",
            suffix=".tmp",
            dir=task_root,
            delete=False,
        ) as stream:
            probe_path = stream.name
            stream.write(b"local-ai-output-preflight")
            stream.flush()
            os.fsync(stream.fileno())
        os.remove(probe_path)
    except Exception as exc:
        probe_path = locals().get("probe_path")
        if probe_path:
            try:
                os.remove(probe_path)
            except OSError:
                pass
        raise LocalAIStorageError(
            "local AI task output storage is not writable"
        ) from exc


FAKE_SOURCE_ID = FakeLocalVideoProvider.provider_id
_LOCAL_SOURCE_IDS = {
    FAKE_SOURCE_ID,
    WAN22_SOURCE_ID,
    LTX25_SOURCE_ID,
    LTX25_HF_SOURCE_ID,
}
_PUBLIC_SOURCE_IDS = (WAN22_SOURCE_ID, LTX25_SOURCE_ID, LTX25_HF_SOURCE_ID)


def is_local_ai_source(source: str | None) -> bool:
    return str(source or "") in _LOCAL_SOURCE_IDS


def is_public_source(source: str | None) -> bool:
    return str(source or "") in _PUBLIC_SOURCE_IDS


def public_source_ids() -> tuple[str, ...]:
    return _PUBLIC_SOURCE_IDS


def is_source_enabled(source: str | None) -> bool:
    """Production providers are always explicit; the M1 fake path is opt-in for tests."""

    if source == FAKE_SOURCE_ID:
        return os.getenv("MPT_ENABLE_LOCAL_AI_FAKE_PROVIDER") == "1"
    if source in {WAN22_SOURCE_ID, LTX25_SOURCE_ID, LTX25_HF_SOURCE_ID}:
        return True
    return False


def create_provider(
    source: str,
    *,
    generation_mode: str = "fast",
) -> LocalVideoProvider:
    if source == FAKE_SOURCE_ID:
        if not is_source_enabled(source):
            raise RuntimeError(
                "the fake local AI provider is test-only and is disabled by default"
            )
        return FakeLocalVideoProvider()
    if source == WAN22_SOURCE_ID:
        if generation_mode != "fast":
            raise ValueError("Wan 2.2 supports local_ai_generation_mode=fast only")
        return Wan22LocalProvider()
    if source == LTX25_SOURCE_ID:
        return LTX25LocalProvider(generation_mode=generation_mode)
    if source == LTX25_HF_SOURCE_ID:
        if generation_mode != "fast":
            raise ValueError("LTX 2.5 Hugging Face supports fast mode only")
        return LTX25HFProvider()
    raise ValueError(f"unknown local AI video source: {source}")


def prepare_provider(
    source: str,
    *,
    generation_mode: str = "fast",
) -> LocalVideoProvider:
    provider = create_provider(source, generation_mode=generation_mode)
    validate_output_storage()
    provider.preflight()
    return provider


def preflight_source(
    source: str,
    *,
    generation_mode: str = "fast",
) -> None:
    prepare_provider(source, generation_mode=generation_mode)


def preflight_status(
    source: str,
    *,
    generation_mode: str = "fast",
) -> dict:
    """Run the same provider preflight used by tasks and return safe operator data."""

    if not is_public_source(source):
        raise ValueError(f"unsupported public local AI source: {source}")

    try:
        provider = prepare_provider(
            source,
            generation_mode=generation_mode,
        )
    except Exception as exc:
        if isinstance(
            exc,
            (
                Wan22ConfigurationError,
                Wan22WorkerError,
                LTX25ConfigurationError,
                LTX25WorkerError,
                LTX25HFConfigurationError,
                HuggingFaceRemoteError,
                LocalAIStorageError,
            ),
        ):
            message = str(exc)
        else:
            message = f"local AI preflight failed ({type(exc).__name__})"
        return {
            "provider_id": str(source),
            "ready": False,
            "error_type": type(exc).__name__,
            "message": message,
        }

    metadata = (
        provider.safe_metadata()
        if callable(getattr(provider, "safe_metadata", None))
        else {}
    )
    return {
        "provider_id": provider.provider_id,
        "ready": True,
        "error_type": None,
        "message": "ready",
        "metadata": metadata,
    }


def scene_duration_limit(provider: LocalVideoProvider, requested: float) -> float:
    provider_limit = getattr(provider, "max_scene_duration", None)
    if provider_limit is None:
        return float(requested)
    return min(float(requested), float(provider_limit))


def provider_base_seed(provider: LocalVideoProvider, default: int = 42) -> int:
    return int(getattr(provider, "base_seed", default))


def provider_generation_settings(provider: LocalVideoProvider) -> dict[str, object]:
    getter = getattr(provider, "generation_settings", None)
    if not callable(getter):
        return {}
    value = getter()
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "FAKE_SOURCE_ID",
    "GenerationResult",
    "LocalAICapability",
    "LocalAICapabilityError",
    "MAX_USER_SEED",
    "LocalAICancellationRequested",
    "LocalAIStorageError",
    "LTX25_SOURCE_ID",
    "LTX25LocalProvider",
    "LTX25_HF_SOURCE_ID",
    "LTX25HFProvider",
    "LocalAISceneGenerationError",
    "WAN22_SOURCE_ID",
    "Wan22LocalProvider",
    "LocalVideoProvider",
    "SceneSpec",
    "create_provider",
    "generate_scene_materials",
    "regenerate_scene_material",
    "is_local_ai_source",
    "is_public_source",
    "is_source_enabled",
    "preflight_source",
    "preflight_status",
    "public_source_ids",
    "prepare_provider",
    "provider_base_seed",
    "provider_generation_settings",
    "public_capabilities",
    "source_capability",
    "validate_generation_request",
    "scene_duration_limit",
    "validate_output_storage",
]
