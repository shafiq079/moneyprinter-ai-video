from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


_PROTOCOL_PREFIX = "MPT_LTX25_JSON:"


def _respond(payload: dict[str, Any]) -> None:
    stream = sys.__stdout__
    stream.write(_PROTOCOL_PREFIX + json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


@contextlib.contextmanager
def _quiet_output():
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield


def _install_repo(repo: Path) -> None:
    for source in (
        repo / "packages" / "ltx-core" / "src",
        repo / "packages" / "ltx-pipelines" / "src",
    ):
        value = str(source)
        if value not in sys.path:
            sys.path.insert(0, value)


def _missing_modules() -> list[str]:
    return [
        name
        for name in ("torch", "safetensors", "numpy", "PIL")
        if importlib.util.find_spec(name) is None
    ]


def _import_runtime(repo: Path, generation_mode: str):
    _install_repo(repo)
    with _quiet_output():
        from ltx_core.loader import (
            LTXV_LORA_COMFY_RENAMING_MAP,
            LoraPathStrengthAndSDOps,
        )
        from ltx_core.model.video_vae import get_video_chunks_number
        from ltx_core.quantization.fp8_cast import build_policy as build_fp8_cast_policy
        from ltx_pipelines.distilled import DistilledPipeline
        DFRPipeline = None
        if generation_mode == "quality":
            from ltx_pipelines.dfr_pipeline import DFRPipeline
        from ltx_pipelines.utils.media_io import encode_video
        from ltx_pipelines.utils.model_paths import ModelPaths
        from ltx_pipelines.utils.types import OffloadMode
    return (
        DistilledPipeline,
        DFRPipeline,
        ModelPaths,
        OffloadMode,
        encode_video,
        get_video_chunks_number,
        build_fp8_cast_policy,
        LoraPathStrengthAndSDOps,
        LTXV_LORA_COMFY_RENAMING_MAP,
    )


def _preflight(
    repo: Path,
    device_id: int,
    generation_mode: str,
) -> dict[str, Any]:
    missing = _missing_modules()
    if missing:
        return {
            "ok": False,
            "error_type": "missing_dependency",
            "message": (
                "LTX 2.5 worker is missing required modules: "
                + ", ".join(missing)
            ),
        }
    try:
        with _quiet_output():
            import torch
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "torch_import_error",
            "message": f"LTX 2.5 worker could not import torch ({type(exc).__name__})",
        }
    if not torch.cuda.is_available():
        return {
            "ok": False,
            "error_type": "cuda_unavailable",
            "message": "LTX 2.5 local generation requires a CUDA device",
        }
    if device_id < 0 or device_id >= torch.cuda.device_count():
        return {
            "ok": False,
            "error_type": "cuda_device_invalid",
            "message": "Configured LTX 2.5 CUDA device index is unavailable",
        }
    try:
        _import_runtime(repo, generation_mode)
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "ltx_import_error",
            "message": (
                "LTX 2.5 modules could not be imported "
                f"({type(exc).__name__}); install the official LTX-2 environment "
                "in the configured worker Python"
            ),
        }
    return {
        "ok": True,
        "torch_version": str(getattr(torch, "__version__", "")),
        "cuda_device_index": device_id,
    }


def _frame_count(duration: float, fps: int) -> int:
    requested = max(0.001, float(duration))
    return max(9, 8 * math.ceil(max(0.0, requested * fps - 1.0) / 8.0) + 1)


def _dimensions(aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return 576, 1024
    if aspect == "16:9":
        return 1024, 576
    if aspect == "1:1":
        return 768, 768
    raise ValueError("unsupported LTX aspect")


def _normalize_video(
    *,
    ffmpeg_path: str,
    raw_path: Path,
    output_path: Path,
    duration: float,
) -> None:
    command = [
        ffmpeg_path,
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
        raise RuntimeError("ffmpeg normalization failed")


class LTXWorker:
    def __init__(
        self,
        *,
        repo: Path,
        transformer: Path,
        text_encoder: Path,
        video_vae: Path,
        audio_vae: Path,
        spatial_upsampler: Path,
        detailing_lora: Path | None,
        generation_mode: str,
        device_id: int,
        offload_mode: str,
        fp8_cast: bool,
    ) -> None:
        self.repo = repo
        self.transformer = transformer
        self.text_encoder = text_encoder
        self.video_vae = video_vae
        self.audio_vae = audio_vae
        self.spatial_upsampler = spatial_upsampler
        self.detailing_lora = detailing_lora
        self.generation_mode = generation_mode
        self.device_id = device_id
        self.offload_mode = offload_mode
        self.fp8_cast = fp8_cast
        self.pipeline = None
        self.encode_video = None
        self.get_video_chunks_number = None

    def load(self) -> None:
        if self.pipeline is not None:
            return
        (
            DistilledPipeline,
            DFRPipeline,
            ModelPaths,
            OffloadMode,
            encode_video,
            get_video_chunks_number,
            build_fp8_cast_policy,
            LoraPathStrengthAndSDOps,
            LTXV_LORA_COMFY_RENAMING_MAP,
        ) = _import_runtime(self.repo, self.generation_mode)
        import torch

        model_paths = ModelPaths.from_split(
            transformer_path=str(self.transformer),
            text_encoder_path=str(self.text_encoder),
            video_vae_path=str(self.video_vae),
            audio_vae_path=str(self.audio_vae),
        )
        quantization = (
            build_fp8_cast_policy(str(self.transformer))
            if self.fp8_cast
            else None
        )
        with _quiet_output():
            common = {
                "model_paths": model_paths,
                "spatial_upsampler_path": str(self.spatial_upsampler),
                "loras": [],
                "device": torch.device(f"cuda:{self.device_id}"),
                "quantization": quantization,
                "offload_mode": OffloadMode(self.offload_mode),
            }
            if self.generation_mode == "quality":
                if DFRPipeline is None or self.detailing_lora is None:
                    raise ValueError(
                        "LTX 2.5 quality mode requires the DFR pipeline "
                        "and detailing LoRA"
                    )
                detailing = [
                    LoraPathStrengthAndSDOps(
                        str(self.detailing_lora),
                        1.0,
                        LTXV_LORA_COMFY_RENAMING_MAP,
                    )
                ]
                self.pipeline = DFRPipeline(
                    **common,
                    detailing_lora=detailing,
                )
            else:
                self.pipeline = DistilledPipeline(**common)
        self.encode_video = encode_video
        self.get_video_chunks_number = get_video_chunks_number

    def generate(self, request: dict[str, Any]) -> None:
        self.load()
        import torch

        output_path = Path(request["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path = output_path.with_name(f".{output_path.stem}.ltx-raw.mp4")
        raw_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

        duration = float(request["duration"])
        if duration <= 0 or duration > 8.0 + 1e-6:
            raise ValueError("scene duration exceeds the configured LTX scene limit")

        width, height = _dimensions(str(request["aspect"]))
        fps = 24
        frames = _frame_count(duration, fps)

        try:
            with _quiet_output(), torch.inference_mode():
                pipeline_kwargs = {
                    "prompt": str(request["prompt"]),
                    "seed": int(request["seed"]),
                    "height": height,
                    "width": width,
                    "frame_rate": fps,
                    "images": [],
                    "num_frames": frames,
                }
                if self.generation_mode == "quality":
                    pipeline_kwargs.update(
                        {
                            "temporal_upscalings": 0,
                            "spatial_upscalings": 1,
                        }
                    )
                result = self.pipeline(**pipeline_kwargs)
                self.encode_video(
                    video=result.video,
                    fps=fps,
                    audio=result.audio,
                    output_path=str(raw_path),
                    video_chunks_number=self.get_video_chunks_number(
                        result.num_frames,
                        result.tiling_config,
                    ),
                )
                del result

            if not raw_path.is_file() or raw_path.stat().st_size <= 0:
                raise RuntimeError("LTX 2.5 did not publish a raw video")

            _normalize_video(
                ffmpeg_path=str(request["ffmpeg_path"]),
                raw_path=raw_path,
                output_path=output_path,
                duration=duration,
            )
        finally:
            raw_path.unlink(missing_ok=True)

    def release(self) -> None:
        if self.pipeline is None:
            return
        self.pipeline = None
        self.encode_video = None
        self.get_video_chunks_number = None
        try:
            import gc
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def _safe_error(exc: Exception, *, stage: str) -> dict[str, Any]:
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return {
                "ok": False,
                "error_type": "cuda_oom",
                "message": "LTX 2.5 ran out of CUDA memory on the configured device",
            }
    except Exception:
        pass
    return {
        "ok": False,
        "error_type": f"{stage}_error",
        "message": f"LTX 2.5 {stage} failed ({type(exc).__name__})",
    }


def _worker_from_args(args) -> LTXWorker:
    return LTXWorker(
        repo=Path(args.repo).expanduser().resolve(),
        transformer=Path(args.transformer).expanduser().resolve(),
        text_encoder=Path(args.text_encoder).expanduser().resolve(),
        video_vae=Path(args.video_vae).expanduser().resolve(),
        audio_vae=Path(args.audio_vae).expanduser().resolve(),
        spatial_upsampler=Path(args.spatial_upsampler).expanduser().resolve(),
        detailing_lora=(
            Path(args.detailing_lora).expanduser().resolve()
            if args.detailing_lora
            else None
        ),
        generation_mode=args.generation_mode,
        device_id=args.device,
        offload_mode=args.offload_mode,
        fp8_cast=args.fp8_cast,
    )


def _serve(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    preflight = _preflight(repo, args.device, args.generation_mode)
    if not preflight.get("ok"):
        _respond(preflight)
        return 2

    worker = _worker_from_args(args)
    _respond({"ok": True, "event": "ready"})

    for line in sys.stdin:
        try:
            request = json.loads(line)
            action = request.get("action")
            if action == "load":
                try:
                    worker.load()
                except Exception as exc:
                    _respond(_safe_error(exc, stage="runtime_load"))
                else:
                    _respond({"ok": True, "event": "loaded"})
            elif action == "generate":
                try:
                    worker.generate(request)
                except Exception as exc:
                    _respond(_safe_error(exc, stage="generation"))
                else:
                    _respond({"ok": True, "event": "generated"})
            elif action == "shutdown":
                worker.release()
                _respond({"ok": True, "event": "shutdown"})
                return 0
            else:
                _respond(
                    {
                        "ok": False,
                        "error_type": "protocol_error",
                        "message": "Unknown LTX 2.5 worker action",
                    }
                )
        except Exception as exc:
            _respond(_safe_error(exc, stage="protocol"))

    worker.release()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--transformer", required=True)
    parser.add_argument("--text-encoder", required=True)
    parser.add_argument("--video-vae", required=True)
    parser.add_argument("--audio-vae", required=True)
    parser.add_argument("--spatial-upscaler", required=True)
    parser.add_argument("--detailing-lora", default="")
    parser.add_argument(
        "--generation-mode",
        choices=("fast", "quality"),
        default="fast",
    )
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument(
        "--offload-mode",
        choices=("none", "cpu", "disk"),
        default="cpu",
    )
    parser.add_argument("--fp8-cast", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--serve", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if args.preflight:
        _respond(_preflight(repo, args.device, args.generation_mode))
        return 0
    if args.serve:
        return _serve(args)
    _respond(
        {
            "ok": False,
            "error_type": "protocol_error",
            "message": "LTX 2.5 worker mode was not selected",
        }
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
