import pytest

from app.models.schema import VideoAspect
from app.services import local_ai


def test_public_capabilities_define_model_backend_and_safe_domains():
    wan = local_ai.source_capability(local_ai.WAN22_SOURCE_ID)
    ltx = local_ai.source_capability(local_ai.LTX25_SOURCE_ID)
    hf = local_ai.source_capability(local_ai.LTX25_HF_SOURCE_ID)

    assert wan.model_label == "Wan 2.2 TI2V-5B"
    assert wan.backend_label == "Local GPU"
    assert wan.generation_modes == ("fast",)
    assert wan.clip_durations == (2, 3, 4, 5)
    assert wan.dimensions_for("9:16") == (704, 1280)

    assert ltx.model_label == "LTX 2.5"
    assert ltx.generation_modes == ("fast", "quality")
    assert ltx.clip_durations == (2, 3, 4, 5, 6, 7, 8)
    assert ltx.dimensions_for("16:9") == (1024, 576)

    assert hf.model_label == "LTX 2.5"
    assert hf.backend_label == "Hugging Face ZeroGPU"
    assert hf.generation_modes == ("fast",)
    assert hf.aspect_ratios == ("9:16", "16:9")
    assert hf.clip_durations == (2, 3, 4, 5)
    assert hf.dimensions_for("16:9") == (768, 512)


def test_generation_request_accepts_only_supported_choices():
    capability = local_ai.validate_generation_request(
        local_ai.LTX25_HF_SOURCE_ID,
        generation_mode="fast",
        aspect=VideoAspect.landscape,
        clip_duration=2,
        seed=42,
    )
    assert capability.source_id == local_ai.LTX25_HF_SOURCE_ID

    with pytest.raises(local_ai.LocalAICapabilityError, match="generation mode"):
        local_ai.validate_generation_request(
            local_ai.LTX25_HF_SOURCE_ID,
            generation_mode="quality",
            aspect="16:9",
            clip_duration=2,
            seed=42,
        )

    with pytest.raises(local_ai.LocalAICapabilityError, match="aspect ratio"):
        local_ai.validate_generation_request(
            local_ai.LTX25_HF_SOURCE_ID,
            generation_mode="fast",
            aspect="4:3",
            clip_duration=2,
            seed=42,
        )

    with pytest.raises(local_ai.LocalAICapabilityError, match="clip duration"):
        local_ai.validate_generation_request(
            local_ai.LTX25_HF_SOURCE_ID,
            generation_mode="fast",
            aspect="16:9",
            clip_duration=8,
            seed=42,
        )

    with pytest.raises(local_ai.LocalAICapabilityError, match="seed"):
        local_ai.validate_generation_request(
            local_ai.LTX25_HF_SOURCE_ID,
            generation_mode="fast",
            aspect="16:9",
            clip_duration=2,
            seed=local_ai.MAX_USER_SEED + 1,
        )
