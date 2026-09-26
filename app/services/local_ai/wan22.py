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


WAN22_SOURCE_ID = "wan22_local"
WAN22_FAMILY_ID = "wan22"
WAN22_MODEL_NAME = "Wan2.2-TI2V-5B"
_PROTOCOL_PREFIX = "MPT_WAN22_JSON:"
_ADAPTER_VERSION = "mpt-wan22-local:v1"


class Wan22ConfigurationError(RuntimeError):
    pass


class Wan22WorkerError(RuntimeError):
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
    raise Wan22ConfigurationError("Wan 2.2 boolean configuration is invalid")


def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise Wan22ConfigurationError("Wan 2.2 integer configuration is invalid") from exc
    if parsed < minimum:
        raise Wan22ConfigurationError("Wan 2.2 integer configuration is out of range")
    return parsed


def _resolve_python(value: str) -> str:
    candidate = os.path.expanduser(str(value or "").strip())
    if not candidate:
        candidate = sys.executable

    candidate_path = Path(candidate)
    if candidate_path.is_file():
        return str(candidate_path.resolve())

    resolved = shutil.which(candidate)
    if resolved:
        return str(Path(resolved).resolve())

    raise Wan22ConfigurationError(
        "Wan 2.2 worker Python executable is unavailable; configure "
        "wan22_local.python_executable"
    )


@dataclass(frozen=True, slots=True)
class Wan22Settings:
    repo_path: Path
    checkpoint_path: Path
    python_executable: str
    device_id: int = 0
    base_seed: int = 42
    offload_model: bool = True
    t5_cpu: bool = True
    convert_model_dtype: bool = True

    @classmethod
    def from_config(cls) -> "Wan22Settings":
        section = dict(getattr(config, "wan22_local", {}) or {})
        repo_value = os.getenv("WAN22_REPO") or section.get("repo_path", "")
        checkpoint_value = (
            os.getenv("WAN22_CHECKPOINT") or section.get("checkpoint_path", "")
        )
        if not str(repo_value or "").strip() or not str(checkpoint_value or "").strip():
            raise Wan22ConfigurationError(
                "Wan 2.2 requires wan22_local.repo_path and "
                "wan22_local.checkpoint_path in config.toml "
                "(or WAN22_REPO and WAN22_CHECKPOINT)"
            )

        python_value = (
            os.getenv("WAN22_PYTHON")
            or section.get("python_executable", "")
            or sys.executable
        )
        return cls(
            repo_path=Path(str(repo_value)).expanduser().resolve(),
            checkpoint_path=Path(str(checkpoint_value)).expanduser().resolve(),
            python_executable=_resolve_python(str(python_value)),
            device_id=_parse_int(
                os.getenv("WAN22_DEVICE", section.get("device", 0)),
                0,
            ),
            base_seed=_parse_int(
                os.getenv("WAN22_SEED", section.get("seed", 42)),
                42,
            ),
            offload_model=_parse_bool(
                os.getenv(
                    "WAN22_OFFLOAD_MODEL",
                    section.get("offload_model", True),
                ),
                True,
            ),
            t5_cpu=_parse_bool(
                os.getenv("WAN22_T5_CPU", section.get("t5_cpu", True)),
                True,
            ),
            convert_model_dtype=_parse_bool(
                os.getenv(
                    "WAN22_CONVERT_MODEL_DTYPE",
                    section.get("convert_model_dtype", True),
                ),
                True,
            ),
        )

    def runtime_key(self) -> tuple[Any, ...]:
        return (
            self.python_executable,
            str(self.repo_path),
            str(self.checkpoint_path),
            self.device_id,
            self.offload_model,
            self.t5_cpu,
            self.convert_model_dtype,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_shards(checkpoint: Path) -> list[Path]:
    index_path = checkpoint / "diffusion_pytorch_model.safetensors.index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        weight_map = payload["weight_map"]
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError("empty weight_map")
        names = sorted(set(weight_map.values()))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Wan22ConfigurationError(
            "Wan 2.2 checkpoint index is invalid"
        ) from exc

    shards: list[Path] = []
    for name in names:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise Wan22ConfigurationError(
                "Wan 2.2 checkpoint index contains an unsafe shard name"
            )
        shard = checkpoint / name
        if not shard.is_file():
            raise Wan22ConfigurationError(
                "Wan 2.2 checkpoint index references a missing model shard"
            )
        shards.append(shard)
    return shards


def _validate_model_files(settings: Wan22Settings) -> list[Path]:
    repo = settings.repo_path
    checkpoint = settings.checkpoint_path

    required_repo_files = (
        repo / "wan" / "textimage2video.py",
        repo / "wan" / "configs" / "wan_ti2v_5B.py",
        repo / "wan" / "utils" / "utils.py",
    )
    if any(not item.is_file() for item in required_repo_files):
        raise Wan22ConfigurationError(
            "wan22_local.repo_path must point to an official Wan2.2 checkout "
            "containing the TI2V implementation"
        )

    required_checkpoint_files = (
        checkpoint / "config.json",
        checkpoint / "models_t5_umt5-xxl-enc-bf16.pth",
        checkpoint / "Wan2.2_VAE.pth",
        checkpoint / "diffusion_pytorch_model.safetensors.index.json",
    )
    if any(not item.is_file() for item in required_checkpoint_files):
        raise Wan22ConfigurationError(
            "wan22_local.checkpoint_path is missing required Wan2.2-TI2V-5B files"
        )
    if not (checkpoint / "google" / "umt5-xxl").is_dir():
        raise Wan22ConfigurationError(
            "wan22_local.checkpoint_path is missing the google/umt5-xxl tokenizer"
        )

    return _checkpoint_shards(checkpoint)


def _model_fingerprint(settings: Wan22Settings) -> str:
    shards = _validate_model_files(settings)
    repo = settings.repo_path
    checkpoint = settings.checkpoint_path
    payload = {
        "adapter": _ADAPTER_VERSION,
        "model": WAN22_MODEL_NAME,
        "repo_code": {
            "textimage2video": _sha256_file(repo / "wan" / "textimage2video.py"),
            "ti2v_config": _sha256_file(repo / "wan" / "configs" / "wan_ti2v_5B.py"),
        },
        "checkpoint": {
            "config": _sha256_file(checkpoint / "config.json"),
            "index": _sha256_file(
                checkpoint / "diffusion_pytorch_model.safetensors.index.json"
            ),
            "t5_size": (checkpoint / "models_t5_umt5-xxl-enc-bf16.pth").stat().st_size,
            "vae_size": (checkpoint / "Wan2.2_VAE.pth").stat().st_size,
            "shards": [(item.name, item.stat().st_size) for item in shards],
        },
        "generation": {
            "offload_model": settings.offload_model,
            "t5_cpu": settings.t5_cpu,
            "convert_model_dtype": settings.convert_model_dtype,
        },
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "wan22-ti2v5b:sha256:" + hashlib.sha256(encoded).hexdigest()


def _worker_script() -> Path:
    return Path(__file__).with_name("wan22_worker.py").resolve()


def _worker_command(settings: Wan22Settings, mode: str) -> list[str]:
    command = [
        settings.python_executable,
        str(_worker_script()),
        mode,
        "--repo",
        str(settings.repo_path),
        "--checkpoint",
        str(settings.checkpoint_path),
        "--device",
        str(settings.device_id),
    ]
    if settings.offload_model:
        command.append("--offload-model")
    if settings.t5_cpu:
        command.append("--t5-cpu")
    if settings.convert_model_dtype:
        command.append("--convert-model-dtype")
    return command


def _parse_worker_response(output: str) -> dict[str, Any]:
    responses = [
        line[len(_PROTOCOL_PREFIX) :]
        for line in str(output or "").splitlines()
        if line.startswith(_PROTOCOL_PREFIX)
    ]
    if not responses:
        raise Wan22WorkerError(
            "Wan 2.2 worker did not return a valid protocol response",
            code="protocol_error",
        )
    try:
        payload = json.loads(responses[-1])
    except ValueError as exc:
        raise Wan22WorkerError(
            "Wan 2.2 worker returned invalid protocol JSON",
            code="protocol_error",
        ) from exc
    if not isinstance(payload, dict):
        raise Wan22WorkerError(
            "Wan 2.2 worker returned an invalid response",
            code="protocol_error",
        )
    return payload


class _WanWorkerClient:
    def __init__(self, settings: Wan22Settings) -> None:
        self.settings = settings
        self._process: subprocess.Popen | None = None
        self._request_lock = threading.RLock()
        self._ready = False
        self._loaded = False

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        self.close()
        self._process = subprocess.Popen(
            _worker_command(self.settings, "--serve"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        payload = self._read_response()
        if not payload.get("ok"):
            self.close()
            raise Wan22WorkerError(
                str(payload.get("message") or "Wan 2.2 worker failed to start"),
                code=str(payload.get("error_type") or "worker_start_error"),
            )
        self._ready = True

    def _read_response(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise Wan22WorkerError(
                "Wan 2.2 worker is not running",
                code="worker_not_running",
            )

        while True:
            line = process.stdout.readline()
            if line == "":
                return_code = process.poll()
                self._process = None
                self._ready = False
                self._loaded = False
                raise Wan22WorkerError(
                    "Wan 2.2 worker exited unexpectedly"
                    + (f" (status {return_code})" if return_code is not None else ""),
                    code="worker_exited",
                )
            if not line.startswith(_PROTOCOL_PREFIX):
                continue
            return _parse_worker_response(line)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._request_lock:
            self._start()
            process = self._process
            if process is None or process.stdin is None:
                raise Wan22WorkerError(
                    "Wan 2.2 worker stdin is unavailable",
                    code="worker_not_running",
                )
            try:
                process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise Wan22WorkerError(
                    "Wan 2.2 worker pipe closed unexpectedly",
                    code="worker_exited",
                ) from exc

            response = self._read_response()
            if not response.get("ok"):
                raise Wan22WorkerError(
                    str(response.get("message") or "Wan 2.2 worker request failed"),
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
        self._ready = False
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


class Wan22LocalProvider:
    provider_id = WAN22_SOURCE_ID
    family_id = WAN22_FAMILY_ID
    max_scene_duration = 5.0

    _worker_lock = threading.RLock()
    _worker: _WanWorkerClient | None = None
    _worker_key: tuple[Any, ...] | None = None
    _worker_factory = _WanWorkerClient

    def __init__(self, settings: Wan22Settings | None = None) -> None:
        self.settings = settings or Wan22Settings.from_config()
        self.model_fingerprint = _model_fingerprint(self.settings)
        self.base_seed = self.settings.base_seed

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "model": WAN22_MODEL_NAME,
            "device_index": self.settings.device_id,
            "offload_model": self.settings.offload_model,
            "t5_cpu": self.settings.t5_cpu,
            "convert_model_dtype": self.settings.convert_model_dtype,
            "output_audio": "none",
        }

    def preflight(self) -> None:
        _validate_model_files(self.settings)
        if not utils.check_ffmpeg_ready():
            raise Wan22ConfigurationError("Wan 2.2 requires a working FFmpeg executable")

        try:
            completed = subprocess.run(
                _worker_command(self.settings, "--preflight"),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Wan22ConfigurationError(
                "Wan 2.2 worker preflight timed out"
            ) from exc
        except OSError as exc:
            raise Wan22ConfigurationError(
                "Wan 2.2 worker process could not be started"
            ) from exc

        response = _parse_worker_response(completed.stdout)
        if not response.get("ok"):
            raise Wan22ConfigurationError(
                str(response.get("message") or "Wan 2.2 worker preflight failed")
            )
        if completed.returncode not in (0, None):
            raise Wan22ConfigurationError("Wan 2.2 worker preflight failed")

    @classmethod
    def _worker_for(cls, settings: Wan22Settings) -> _WanWorkerClient:
        key = settings.runtime_key()
        with cls._worker_lock:
            if cls._worker is None or cls._worker_key != key:
                if cls._worker is not None:
                    cls._worker.close()
                cls._worker = cls._worker_factory(settings)
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

    def load_runtime(self) -> None:
        with LOCAL_AI_RUNTIME.generation_slot(self.family_id):
            logger.info(
                "loading/reusing Wan 2.2 local runtime "
                f"on CUDA device {self.settings.device_id}"
            )
            self._worker_for(self.settings).load()

    def generate(self, scene: SceneSpec, output_path: Path) -> None:
        if scene.target_duration > self.max_scene_duration + 1e-6:
            raise Wan22ConfigurationError(
                "Wan 2.2 scene duration exceeds the supported 5 second local limit"
            )

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with LOCAL_AI_RUNTIME.generation_slot(self.family_id):
            worker = self._worker_for(self.settings)
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
            except Wan22WorkerError as exc:
                if exc.code in {"cuda_oom", "worker_exited", "runtime_load_error"}:
                    self.release_runtime()
                raise

    def validate_output(
        self, output_path: Path, scene: SceneSpec
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
        # Persistence across tasks is intentional. Family switching or process exit
        # calls release_runtime explicitly.
        return None


LOCAL_AI_RUNTIME.register_family(WAN22_FAMILY_ID, Wan22LocalProvider.release_runtime)
atexit.register(Wan22LocalProvider.release_runtime)
