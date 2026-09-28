from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import config
from app.utils import utils

from .base import GenerationResult, SceneSpec
from .media import validate_video_clip
from .runtime import LOCAL_AI_RUNTIME


LTX25_SOURCE_ID = "ltx25_local"
LTX25_FAMILY_ID = "ltx25"
LTX25_MODEL_NAME = "LTX-2.5"
LTX25_MODES = {"fast", "quality"}
_PROTOCOL_PREFIX = "MPT_LTX25_JSON:"
_ADAPTER_VERSION = "mpt-ltx25-local:v1"


class LTX25ConfigurationError(RuntimeError):
    pass


class LTX25WorkerError(RuntimeError):
    def __init__(self, message: str, *, code: str = "worker_error") -> None:
        super().__init__(message)
        self.code = code


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise LTX25ConfigurationError("LTX 2.5 boolean configuration is invalid")


def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LTX25ConfigurationError("LTX 2.5 integer configuration is invalid") from exc
    if parsed < minimum:
        raise LTX25ConfigurationError("LTX 2.5 integer configuration is out of range")
    return parsed


def _parse_offload_mode(value: Any) -> str:
    normalized = str(value or "cpu").strip().lower()
    if normalized not in {"none", "cpu", "disk"}:
        raise LTX25ConfigurationError(
            "LTX 2.5 offload_mode must be one of: none, cpu, disk"
        )
    return normalized


def _resolve_python(value: str) -> str:
    candidate = os.path.expanduser(str(value or "").strip()) or sys.executable
    path = Path(candidate)
    if path.is_file():
        return str(path.resolve())
    resolved = shutil.which(candidate)
    if resolved:
        return str(Path(resolved).resolve())
    raise LTX25ConfigurationError(
        "LTX 2.5 worker Python executable is unavailable; configure "
        "ltx25_local.python_executable"
    )


@dataclass(frozen=True, slots=True)
class LTX25Settings:
    repo_path: Path
    transformer_path: Path
    text_encoder_path: Path
    video_vae_path: Path
    audio_vae_path: Path
    spatial_upsampler_path: Path
    python_executable: str
    detailing_lora_path: Path | None = None
    device_id: int = 0
    base_seed: int = 42
    offload_mode: str = "cpu"
    fp8_cast: bool = True

    @classmethod
    def from_config(cls) -> "LTX25Settings":
        section = dict(getattr(config, "ltx25_local", {}) or {})
        keys = {
            "repo_path": os.getenv("LTX25_REPO") or section.get("repo_path", ""),
            "transformer_path": os.getenv("LTX25_TRANSFORMER")
            or section.get("transformer_path", ""),
            "text_encoder_path": os.getenv("LTX25_TEXT_ENCODER")
            or section.get("text_encoder_path", ""),
            "video_vae_path": os.getenv("LTX25_VIDEO_VAE")
            or section.get("video_vae_path", ""),
            "audio_vae_path": os.getenv("LTX25_AUDIO_VAE")
            or section.get("audio_vae_path", ""),
            "spatial_upsampler_path": os.getenv("LTX25_SPATIAL_UPSAMPLER")
            or section.get("spatial_upsampler_path", ""),
        }
        missing = [name for name, value in keys.items() if not str(value or "").strip()]
        if missing:
            raise LTX25ConfigurationError(
                "LTX 2.5 requires these ltx25_local settings: "
                + ", ".join(missing)
            )

        python_value = (
            os.getenv("LTX25_PYTHON")
            or section.get("python_executable", "")
            or sys.executable
        )
        return cls(
            repo_path=Path(str(keys["repo_path"])).expanduser().resolve(),
            transformer_path=Path(str(keys["transformer_path"])).expanduser().resolve(),
            text_encoder_path=Path(str(keys["text_encoder_path"])).expanduser().resolve(),
            video_vae_path=Path(str(keys["video_vae_path"])).expanduser().resolve(),
            audio_vae_path=Path(str(keys["audio_vae_path"])).expanduser().resolve(),
            spatial_upsampler_path=Path(
                str(keys["spatial_upsampler_path"])
            ).expanduser().resolve(),
            python_executable=_resolve_python(str(python_value)),
            detailing_lora_path=(
                Path(
                    str(
                        os.getenv("LTX25_DETAILING_LORA")
                        or section.get("detailing_lora_path", "")
                    )
                ).expanduser().resolve()
                if str(
                    os.getenv("LTX25_DETAILING_LORA")
                    or section.get("detailing_lora_path", "")
                ).strip()
                else None
            ),
            device_id=_parse_int(
                os.getenv("LTX25_DEVICE", section.get("device", 0)),
                0,
            ),
            base_seed=_parse_int(
                os.getenv("LTX25_SEED", section.get("seed", 42)),
                42,
            ),
            offload_mode=_parse_offload_mode(
                os.getenv(
                    "LTX25_OFFLOAD_MODE",
                    section.get("offload_mode", "cpu"),
                )
            ),
            fp8_cast=_parse_bool(
                os.getenv("LTX25_FP8_CAST", section.get("fp8_cast", True)),
                True,
            ),
        )

    def runtime_key(self) -> tuple[Any, ...]:
        return (
            self.python_executable,
            str(self.repo_path),
            str(self.transformer_path),
            str(self.text_encoder_path),
            str(self.video_vae_path),
            str(self.audio_vae_path),
            str(self.spatial_upsampler_path),
            str(self.detailing_lora_path or ""),
            self.device_id,
            self.offload_mode,
            self.fp8_cast,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_stat_fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _normalize_generation_mode(value: str | None) -> str:
    mode = str(value or "fast").strip().lower()
    if mode not in LTX25_MODES:
        raise LTX25ConfigurationError(
            "LTX 2.5 generation mode must be fast or quality"
        )
    return mode


def _validate_model_files(
    settings: LTX25Settings,
    generation_mode: str = "fast",
) -> tuple[Path, ...]:
    repo = settings.repo_path
    required_repo_files = (
        repo / "packages" / "ltx-pipelines" / "src" / "ltx_pipelines" / "distilled.py",
        repo / "packages" / "ltx-pipelines" / "src" / "ltx_pipelines" / "utils" / "model_paths.py",
        repo / "packages" / "ltx-core" / "src" / "ltx_core" / "__init__.py",
    )
    mode = _normalize_generation_mode(generation_mode)
    if mode == "quality":
        required_repo_files += (
            repo
            / "packages"
            / "ltx-pipelines"
            / "src"
            / "ltx_pipelines"
            / "dfr_pipeline.py",
        )
    if any(not item.is_file() for item in required_repo_files):
        raise LTX25ConfigurationError(
            "ltx25_local.repo_path must point to an official LTX-2 checkout "
            "containing ltx-core and ltx-pipelines"
        )

    model_files = (
        settings.transformer_path,
        settings.text_encoder_path,
        settings.video_vae_path,
        settings.audio_vae_path,
        settings.spatial_upsampler_path,
    )
    if any(not item.is_file() for item in model_files):
        raise LTX25ConfigurationError(
            "ltx25_local is missing one or more required LTX-2.5 model files"
        )
    if mode == "quality":
        if (
            settings.detailing_lora_path is None
            or not settings.detailing_lora_path.is_file()
        ):
            raise LTX25ConfigurationError(
                "LTX 2.5 quality mode requires "
                "ltx25_local.detailing_lora_path"
            )
        model_files += (settings.detailing_lora_path,)
    return model_files


def _model_fingerprint(
    settings: LTX25Settings,
    generation_mode: str,
) -> str:
    mode = _normalize_generation_mode(generation_mode)
    model_files = _validate_model_files(settings, mode)
    repo = settings.repo_path
    code_files = {
        "distilled": repo
        / "packages"
        / "ltx-pipelines"
        / "src"
        / "ltx_pipelines"
        / "distilled.py",
        "model_paths": repo
        / "packages"
        / "ltx-pipelines"
        / "src"
        / "ltx_pipelines"
        / "utils"
        / "model_paths.py",
    }
    if mode == "quality":
        code_files["dfr"] = (
            repo
            / "packages"
            / "ltx-pipelines"
            / "src"
            / "ltx_pipelines"
            / "dfr_pipeline.py"
        )
    payload = {
        "adapter": _ADAPTER_VERSION,
        "model": LTX25_MODEL_NAME,
        "repo_code": {
            name: _sha256_file(path)
            for name, path in code_files.items()
        },
        "model_files": [
            (path.name, *_file_stat_fingerprint(path))
            for path in model_files
        ],
        "generation": {
            "mode": mode,
            "offload_mode": settings.offload_mode,
            "fp8_cast": settings.fp8_cast,
        },
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"ltx25-{mode}:sha256:" + hashlib.sha256(encoded).hexdigest()


def _worker_script() -> Path:
    return Path(__file__).with_name("ltx25_worker.py").resolve()


def _worker_command(
    settings: LTX25Settings,
    worker_mode: str,
    generation_mode: str,
) -> list[str]:
    command = [
        settings.python_executable,
        str(_worker_script()),
        worker_mode,
        "--repo",
        str(settings.repo_path),
        "--transformer",
        str(settings.transformer_path),
        "--text-encoder",
        str(settings.text_encoder_path),
        "--video-vae",
        str(settings.video_vae_path),
        "--audio-vae",
        str(settings.audio_vae_path),
        "--spatial-upscaler",
        str(settings.spatial_upsampler_path),
        "--device",
        str(settings.device_id),
        "--offload-mode",
        settings.offload_mode,
        "--generation-mode",
        _normalize_generation_mode(generation_mode),
    ]
    if settings.detailing_lora_path is not None:
        command.extend(
            ["--detailing-lora", str(settings.detailing_lora_path)]
        )
    if settings.fp8_cast:
        command.append("--fp8-cast")
    return command


def _parse_worker_response(output: str) -> dict[str, Any]:
    responses = [
        line[len(_PROTOCOL_PREFIX) :]
        for line in str(output or "").splitlines()
        if line.startswith(_PROTOCOL_PREFIX)
    ]
    if not responses:
        raise LTX25WorkerError(
            "LTX 2.5 worker did not return a valid protocol response",
            code="protocol_error",
        )
    try:
        payload = json.loads(responses[-1])
    except ValueError as exc:
        raise LTX25WorkerError(
            "LTX 2.5 worker returned invalid protocol JSON",
            code="protocol_error",
        ) from exc
    if not isinstance(payload, dict):
        raise LTX25WorkerError(
            "LTX 2.5 worker returned an invalid response",
            code="protocol_error",
        )
    return payload


class _LTXWorkerClient:
    def __init__(
        self,
        settings: LTX25Settings,
        generation_mode: str = "fast",
    ) -> None:
        self.settings = settings
        self.generation_mode = _normalize_generation_mode(generation_mode)
        self._process: subprocess.Popen | None = None
        self._request_lock = threading.RLock()
        self._loaded = False

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self.close()
        self._process = subprocess.Popen(
            _worker_command(
                self.settings,
                "--serve",
                self.generation_mode,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        payload = self._read_response()
        if not payload.get("ok"):
            self.close()
            raise LTX25WorkerError(
                str(payload.get("message") or "LTX 2.5 worker failed to start"),
                code=str(payload.get("error_type") or "worker_start_error"),
            )

    def _read_response(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise LTX25WorkerError(
                "LTX 2.5 worker is not running",
                code="worker_not_running",
            )
        while True:
            line = process.stdout.readline()
            if line == "":
                return_code = process.poll()
                self._process = None
                self._loaded = False
                for stream in (process.stdin, process.stdout):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:
                        pass
                raise LTX25WorkerError(
                    "LTX 2.5 worker exited unexpectedly"
                    + (f" (status {return_code})" if return_code is not None else ""),
                    code="worker_exited",
                )
            if line.startswith(_PROTOCOL_PREFIX):
                return _parse_worker_response(line)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._request_lock:
            self._start()
            process = self._process
            if process is None or process.stdin is None:
                raise LTX25WorkerError(
                    "LTX 2.5 worker stdin is unavailable",
                    code="worker_not_running",
                )
            try:
                process.stdin.write(
                    json.dumps(payload, separators=(",", ":")) + "\n"
                )
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise LTX25WorkerError(
                    "LTX 2.5 worker pipe closed unexpectedly",
                    code="worker_exited",
                ) from exc
            response = self._read_response()
            if not response.get("ok"):
                raise LTX25WorkerError(
                    str(response.get("message") or "LTX 2.5 worker request failed"),
                    code=str(response.get("error_type") or "worker_error"),
                )
            return response

    def load(self) -> None:
        if self._loaded and self._process is not None and self._process.poll() is None:
            return
        self.request({"action": "load"})
        self._loaded = True

    def close(self) -> None:
        process = self._process
        self._process = None
        self._loaded = False
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        finally:
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass


class LTX25LocalProvider:
    provider_id = LTX25_SOURCE_ID
    family_id = LTX25_FAMILY_ID
    max_scene_duration = 8.0

    _worker_lock = threading.RLock()
    _worker: _LTXWorkerClient | None = None
    _worker_key: tuple[Any, ...] | None = None
    _worker_factory = _LTXWorkerClient

    def __init__(
        self,
        settings: LTX25Settings | None = None,
        generation_mode: str = "fast",
    ) -> None:
        self.settings = settings or LTX25Settings.from_config()
        self.generation_mode = _normalize_generation_mode(generation_mode)
        self.model_fingerprint = _model_fingerprint(
            self.settings,
            self.generation_mode,
        )
        self.base_seed = self.settings.base_seed
        self._preflight_complete = False

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "model": LTX25_MODEL_NAME,
            "mode": self.generation_mode,
            "device_index": self.settings.device_id,
            "offload_mode": self.settings.offload_mode,
            "fp8_cast": self.settings.fp8_cast,
            "output_audio": "none",
        }

    def generation_settings(self) -> dict[str, object]:
        return {"mode": self.generation_mode}

    def preflight(self) -> None:
        if self._preflight_complete:
            return
        _validate_model_files(
            self.settings,
            self.generation_mode,
        )
        if not utils.check_ffmpeg_ready():
            raise LTX25ConfigurationError(
                "LTX 2.5 requires a working FFmpeg executable"
            )
        try:
            completed = subprocess.run(
                _worker_command(
                    self.settings,
                    "--preflight",
                    self.generation_mode,
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LTX25ConfigurationError(
                "LTX 2.5 worker preflight timed out"
            ) from exc
        except OSError as exc:
            raise LTX25ConfigurationError(
                "LTX 2.5 worker process could not be started"
            ) from exc

        response = _parse_worker_response(completed.stdout)
        if not response.get("ok"):
            raise LTX25ConfigurationError(
                str(response.get("message") or "LTX 2.5 worker preflight failed")
            )
        if completed.returncode not in (0, None):
            raise LTX25ConfigurationError("LTX 2.5 worker preflight failed")
        self._preflight_complete = True

    @classmethod
    def _worker_for(
        cls,
        settings: LTX25Settings,
        model_fingerprint: str,
    ) -> _LTXWorkerClient:
        key = settings.runtime_key() + (model_fingerprint,)
        with cls._worker_lock:
            if cls._worker is None or cls._worker_key != key:
                if cls._worker is not None:
                    cls._worker.close()
                cls._worker = cls._worker_factory(
                    settings,
                    model_fingerprint.split(":", 1)[0].removeprefix("ltx25-"),
                )
                cls._worker_key = key
            return cls._worker

    @classmethod
    def release_runtime(cls) -> None:
        with cls._worker_lock:
            if cls._worker is not None:
                cls._worker.close()
            cls._worker = None
            cls._worker_key = None
        LOCAL_AI_RUNTIME.clear_active_family(cls.family_id)

    def generation_session(self):
        return LOCAL_AI_RUNTIME.generation_slot(
            self.family_id,
            self.settings.device_id,
        )

    def load_runtime(self) -> None:
        with LOCAL_AI_RUNTIME.generation_slot(
            self.family_id,
            self.settings.device_id,
        ):
            logger.info(
                "loading/reusing LTX 2.5 runtime "
                f"mode={self.generation_mode}, "
                f"CUDA device={self.settings.device_id}"
            )
            self._worker_for(self.settings, self.model_fingerprint).load()

    def generate(self, scene: SceneSpec, output_path: Path) -> None:
        if scene.target_duration > self.max_scene_duration + 1e-6:
            raise LTX25ConfigurationError(
                "LTX 2.5 scene duration exceeds the supported 8 second local limit"
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL_AI_RUNTIME.generation_slot(
            self.family_id,
            self.settings.device_id,
        ):
            worker = self._worker_for(self.settings, self.model_fingerprint)
            try:
                worker.load()
                worker.request(
                    {
                        "action": "generate",
                        "scene_id": scene.scene_id,
                        "prompt": scene.prompt,
                        "duration": scene.target_duration,
                        "aspect": scene.aspect,
                        "seed": scene.seed,
                        "output_path": str(output),
                        "ffmpeg_path": utils.get_ffmpeg_binary(),
                    }
                )
            except LTX25WorkerError as exc:
                if exc.code in {"cuda_oom", "worker_exited", "runtime_load_error"}:
                    self.release_runtime()
                raise

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


LOCAL_AI_RUNTIME.register_family(LTX25_FAMILY_ID, LTX25LocalProvider.release_runtime)
atexit.register(LTX25LocalProvider.release_runtime)
