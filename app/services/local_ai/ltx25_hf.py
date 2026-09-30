from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import config
from app.utils import utils

from .base import GenerationResult, SceneSpec
from .media import validate_video_clip
from .remote_gpu.huggingface import (
    HuggingFaceGradioBackend,
    HuggingFaceRemoteError,
)


LTX25_HF_SOURCE_ID = "ltx25_hf"
LTX25_HF_MODEL_NAME = "LTX-2.5"
_ADAPTER_VERSION = "mpt-ltx25-hf:v3"


class LTX25HFConfigurationError(RuntimeError):
    pass


def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LTX25HFConfigurationError(
            "LTX 2.5 Hugging Face integer configuration is invalid"
        ) from exc
    if parsed < minimum:
        raise LTX25HFConfigurationError(
            "LTX 2.5 Hugging Face integer configuration is out of range"
        )
    return parsed


def _parse_float(value: Any, default: float, *, minimum: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LTX25HFConfigurationError(
            "LTX 2.5 Hugging Face numeric configuration is invalid"
        ) from exc
    if parsed < minimum:
        raise LTX25HFConfigurationError(
            "LTX 2.5 Hugging Face numeric configuration is out of range"
        )
    return parsed


@dataclass(frozen=True, slots=True)
class LTX25HFSettings:
    space_url: str
    api_name: str = "generate_scene"
    token_env: str = "HF_TOKEN"
    deployment_revision: str = ""
    base_seed: int = 42
    max_scene_duration: float = 5.0
    decoder: str = "conv"
    job_timeout_seconds: int = 900

    @classmethod
    def from_config(cls) -> "LTX25HFSettings":
        section = dict(getattr(config, "ltx25_hf", {}) or {})
        space_url = str(
            os.getenv("LTX25_HF_SPACE_URL")
            or section.get("space_url", "")
            or ""
        ).strip().rstrip("/")
        api_name = str(
            os.getenv("LTX25_HF_API_NAME")
            or section.get("api_name", "generate_scene")
            or "generate_scene"
        ).strip().strip("/")
        token_env = str(
            os.getenv("LTX25_HF_TOKEN_ENV")
            or section.get("token_env", "HF_TOKEN")
            or "HF_TOKEN"
        ).strip()
        deployment_revision = str(
            os.getenv("LTX25_HF_DEPLOYMENT_REVISION")
            or section.get("deployment_revision", "")
            or ""
        ).strip()
        decoder = str(
            os.getenv("LTX25_HF_DECODER")
            or section.get("decoder", "conv")
            or "conv"
        ).strip().lower()

        parsed = urlparse(space_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise LTX25HFConfigurationError(
                "ltx25_hf.space_url must be an absolute HTTPS Space URL"
            )
        if not api_name:
            raise LTX25HFConfigurationError("ltx25_hf.api_name is required")
        if not token_env:
            raise LTX25HFConfigurationError("ltx25_hf.token_env is required")
        if not deployment_revision:
            raise LTX25HFConfigurationError(
                "ltx25_hf.deployment_revision is required"
            )
        if decoder not in {"conv", "diffusion"}:
            raise LTX25HFConfigurationError(
                "ltx25_hf.decoder must be conv or diffusion"
            )

        return cls(
            space_url=space_url,
            api_name=api_name,
            token_env=token_env,
            deployment_revision=deployment_revision,
            base_seed=_parse_int(
                os.getenv("LTX25_HF_SEED", section.get("seed", 42)),
                42,
            ),
            max_scene_duration=_parse_float(
                os.getenv(
                    "LTX25_HF_MAX_SCENE_DURATION",
                    section.get("max_scene_duration", 5.0),
                ),
                5.0,
                minimum=2.0,
            ),
            decoder=decoder,
            job_timeout_seconds=_parse_int(
                os.getenv(
                    "LTX25_HF_JOB_TIMEOUT_SECONDS",
                    section.get("job_timeout_seconds", 900),
                ),
                900,
                minimum=60,
            ),
        )


def _model_fingerprint(settings: LTX25HFSettings) -> str:
    payload = {
        "adapter": _ADAPTER_VERSION,
        "model": LTX25_HF_MODEL_NAME,
        "backend": "huggingface_zerogpu",
        "space_url": settings.space_url,
        "api_name": settings.api_name,
        "deployment_revision": settings.deployment_revision,
        "decoder": settings.decoder,
        "max_scene_duration": settings.max_scene_duration,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ltx25-hf:sha256:" + hashlib.sha256(encoded).hexdigest()


def _dimensions(aspect: str) -> tuple[int, int]:
    if aspect == "16:9":
        return 1472, 832
    if aspect == "9:16":
        return 832, 1472
    if aspect == "1:1":
        return 640, 640
    raise LTX25HFConfigurationError(f"unsupported LTX Hugging Face aspect: {aspect}")


def _normalize_video(
    *,
    raw_path: Path,
    output_path: Path,
    duration: float,
) -> None:
    command = [
        utils.get_ffmpeg_binary(),
        "-y",
        "-i",
        str(raw_path),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{float(duration):.3f}",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise HuggingFaceRemoteError(
            "LTX 2.5 Hugging Face output normalization failed",
            code="output_normalization_failed",
        )


class LTX25HFProvider:
    provider_id = LTX25_HF_SOURCE_ID
    backend_id = "huggingface_zerogpu"
    uses_local_gpu = False

    _backend_factory = HuggingFaceGradioBackend

    def __init__(
        self,
        settings: LTX25HFSettings | None = None,
    ) -> None:
        self.settings = settings or LTX25HFSettings.from_config()
        self.max_scene_duration = self.settings.max_scene_duration
        self.base_seed = self.settings.base_seed
        self.model_fingerprint = _model_fingerprint(self.settings)
        self._backend: HuggingFaceGradioBackend | None = None
        self._preflight_complete = False
        self._preflight_metadata: dict[str, Any] = {}

    def _token(self) -> str:
        token = str(os.getenv(self.settings.token_env) or "").strip()
        if not token:
            raise LTX25HFConfigurationError(
                f"LTX 2.5 Hugging Face token environment variable "
                f"{self.settings.token_env} is not set"
            )
        return token

    def _backend_client(self) -> HuggingFaceGradioBackend:
        if self._backend is None:
            self._backend = self._backend_factory(
                space_url=self.settings.space_url,
                api_name=self.settings.api_name,
                token=self._token(),
                job_timeout_seconds=self.settings.job_timeout_seconds,
            )
        return self._backend

    def safe_metadata(self) -> dict[str, Any]:
        host = urlparse(self.settings.space_url).netloc
        return {
            "model": LTX25_HF_MODEL_NAME,
            "mode": "fast",
            "backend": self.backend_id,
            "space_host": host,
            "api_name": self.settings.api_name,
            "deployment_revision": self.settings.deployment_revision,
            "decoder": self.settings.decoder,
            "output_audio": "none",
            **self._preflight_metadata,
        }

    def generation_settings(self) -> dict[str, object]:
        return {
            "mode": "fast",
            "backend": self.backend_id,
            "decoder": self.settings.decoder,
        }

    def preflight(self) -> None:
        if self._preflight_complete:
            return
        if not utils.check_ffmpeg_ready():
            raise LTX25HFConfigurationError(
                "LTX 2.5 Hugging Face requires a working FFmpeg executable"
            )
        metadata = self._backend_client().preflight()
        self._preflight_metadata = {
            "remote_api_ready": True,
            "remote_backend": str(metadata.get("backend") or self.backend_id),
        }
        self._preflight_complete = True

    def load_runtime(self) -> None:
        # ZeroGPU acquires/releases the remote runtime inside the Space's GPU
        # function. MoneyPrinter intentionally holds no local CUDA runtime.
        return None

    def generate(self, scene: SceneSpec, output_path: Path) -> None:
        if scene.target_duration > self.max_scene_duration + 1e-6:
            raise LTX25HFConfigurationError(
                "LTX 2.5 Hugging Face scene duration exceeds the configured limit"
            )

        width, height = _dimensions(scene.aspect)
        requested_duration = max(2.0, float(scene.target_duration))
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        raw_path = output.with_name(f".{output.name}.hf-raw.mp4")
        raw_path.unlink(missing_ok=True)

        inputs = {
            "prompt": scene.prompt,
            "image_path": None,
            "height": height,
            "width": width,
            "duration_s": requested_duration,
            "seed": int(scene.seed),
            "decoder": self.settings.decoder,
            "auto_len": False,
            "randomize_seed": False,
            "do_enhance": False,
        }

        try:
            self._backend_client().generate(inputs, raw_path)
            _normalize_video(
                raw_path=raw_path,
                output_path=output,
                duration=scene.target_duration,
            )
        finally:
            raw_path.unlink(missing_ok=True)

    def validate_output(
        self,
        output_path: Path,
        scene: SceneSpec,
    ) -> GenerationResult:
        probe = validate_video_clip(output_path, scene)
        return GenerationResult(
            output_path=Path(output_path),
            actual_duration=probe.duration,
            width=probe.width,
            height=probe.height,
            provider_id=self.provider_id,
            model_fingerprint=self.model_fingerprint,
        )

    def unload(self) -> None:
        return None
