from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


_PROTOCOL_PREFIX = "MPT_WAN22_JSON:"
_REQUIRED_MODULES = (
    "torch",
    "torchvision",
    "imageio",
    "easydict",
    "ftfy",
    "transformers",
    "diffusers",
    "numpy",
    "einops",
    "regex",
)


def _respond(payload: dict[str, Any]) -> None:
    stream = sys.__stdout__
    stream.write(_PROTOCOL_PREFIX + json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


@contextlib.contextmanager
def _quiet_output():
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield


def _missing_modules() -> list[str]:
    return [name for name in _REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def _install_wan_package(repo: Path) -> None:
    existing = sys.modules.get("wan")
    if existing is not None:
        existing_file = Path(getattr(existing, "__file__", "") or "").resolve()
        if existing_file and repo not in existing_file.parents:
            raise RuntimeError("a different wan package is already loaded")
        return

    # The official wan/__init__.py imports optional S2V/Animate modules that are
    # unrelated to TI2V and may pull extra dependencies. Seed a package shell so
    # importing wan.textimage2video loads only the TI2V dependency graph.
    package = types.ModuleType("wan")
    package.__path__ = [str(repo / "wan")]
    package.__package__ = "wan"
    package.__file__ = str(repo / "wan" / "__init__.py")
    sys.modules["wan"] = package


def _import_runtime(repo: Path):
    _install_wan_package(repo)
    with _quiet_output():
        from wan.configs import WAN_CONFIGS
        from wan.textimage2video import WanTI2V
        from wan.utils.utils import save_video
    return WanTI2V, WAN_CONFIGS["ti2v-5B"], save_video


def _preflight(repo: Path, device_id: int) -> dict[str, Any]:
    missing = _missing_modules()
    if missing:
        return {
            "ok": False,
            "error_type": "missing_dependency",
            "message": "Wan 2.2 worker is missing required modules: " + ", ".join(missing),
        }

    try:
        with _quiet_output():
            import torch
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "torch_import_error",
            "message": f"Wan 2.2 worker could not import torch ({type(exc).__name__})",
        }

    try:
        import numpy as np
        numpy_major = int(str(np.__version__).split(".", 1)[0])
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "numpy_import_error",
            "message": f"Wan 2.2 worker could not validate NumPy ({type(exc).__name__})",
        }
    if numpy_major >= 2:
        return {
            "ok": False,
            "error_type": "numpy_version_incompatible",
            "message": (
                "Official Wan2.2 currently requires NumPy < 2; use a dedicated "
                "Wan worker environment instead of the MoneyPrinterTurbo environment"
            ),
        }

    if not torch.cuda.is_available():
        return {
            "ok": False,
            "error_type": "cuda_unavailable",
            "message": "Wan 2.2 TI2V-5B requires a CUDA device",
        }
    if device_id < 0 or device_id >= torch.cuda.device_count():
        return {
            "ok": False,
            "error_type": "cuda_device_invalid",
            "message": "Configured Wan 2.2 CUDA device index is unavailable",
        }

    try:
        _import_runtime(repo)
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "wan_import_error",
            "message": (
                "Wan 2.2 TI2V modules could not be imported "
                f"({type(exc).__name__}); install the official Wan2.2 requirements "
                "in the configured worker environment"
            ),
        }

    return {
        "ok": True,
        "torch_version": str(getattr(torch, "__version__", "")),
        "cuda_device_index": device_id,
    }


def _frame_count(duration: float, fps: int, maximum: int) -> int:
    requested = max(0.001, float(duration))
    frames = 4 * math.ceil(max(0.0, requested * fps - 1.0) / 4.0) + 1
    return min(maximum, max(5, frames))


def _normalize_video(
    *,
    ffmpeg_path: str,
    raw_path: Path,
    output_path: Path,
    aspect: str,
    duration: float,
) -> None:
    video_filter = "fps=24"
    if aspect == "1:1":
        video_filter = r"crop=min(iw\,ih):min(iw\,ih),fps=24"

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(raw_path),
        "-vf",
        video_filter,
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


class WanWorker:
    def __init__(
        self,
        *,
        repo: Path,
        checkpoint: Path,
        device_id: int,
        offload_model: bool,
        t5_cpu: bool,
        convert_model_dtype: bool,
    ) -> None:
        self.repo = repo
        self.checkpoint = checkpoint
        self.device_id = device_id
        self.offload_model = offload_model
        self.t5_cpu = t5_cpu
        self.convert_model_dtype = convert_model_dtype
        self.pipeline = None
        self.cfg = None
        self.save_video = None

    def load(self) -> None:
        if self.pipeline is not None:
            return
        WanTI2V, cfg, save_video = _import_runtime(self.repo)
        with _quiet_output():
            self.pipeline = WanTI2V(
                config=cfg,
                checkpoint_dir=str(self.checkpoint),
                device_id=self.device_id,
                t5_cpu=self.t5_cpu,
                convert_model_dtype=self.convert_model_dtype,
            )
        self.cfg = cfg
        self.save_video = save_video

    def generate(self, request: dict[str, Any]) -> None:
        self.load()
        import torch

        output_path = Path(request["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path = output_path.with_name(f".{output_path.stem}.wan-raw.mp4")
        raw_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

        duration = float(request["duration"])
        fps = int(getattr(self.cfg, "sample_fps", 24) or 24)
        maximum_frames = int(getattr(self.cfg, "frame_num", 121) or 121)
        maximum_duration = maximum_frames / fps
        if duration > maximum_duration + 1e-6:
            raise ValueError("scene duration exceeds the configured Wan frame limit")

        aspect = str(request["aspect"])
        size = (704, 1280) if aspect == "9:16" else (1280, 704)
        frames = _frame_count(duration, fps, maximum_frames)

        try:
            with _quiet_output(), torch.inference_mode():
                video = self.pipeline.generate(
                    input_prompt=str(request["prompt"]),
                    size=size,
                    frame_num=frames,
                    shift=self.cfg.sample_shift,
                    sampling_steps=self.cfg.sample_steps,
                    guide_scale=self.cfg.sample_guide_scale,
                    seed=int(request["seed"]),
                    offload_model=self.offload_model,
                )
                try:
                    self.save_video(
                        tensor=video[None],
                        save_file=str(raw_path),
                        fps=fps,
                        nrow=1,
                        normalize=True,
                        value_range=(-1, 1),
                    )
                finally:
                    del video

            if not raw_path.is_file() or raw_path.stat().st_size <= 0:
                raise RuntimeError("Wan did not publish a raw video")

            _normalize_video(
                ffmpeg_path=str(request["ffmpeg_path"]),
                raw_path=raw_path,
                output_path=output_path,
                aspect=aspect,
                duration=duration,
            )
        finally:
            raw_path.unlink(missing_ok=True)

    def release(self) -> None:
        if self.pipeline is None:
            return
        self.pipeline = None
        self.cfg = None
        self.save_video = None
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
                "message": "Wan 2.2 ran out of CUDA memory on the configured device",
            }
    except Exception:
        pass

    return {
        "ok": False,
        "error_type": f"{stage}_error",
        "message": f"Wan 2.2 {stage} failed ({type(exc).__name__})",
    }


def _serve(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    checkpoint = Path(args.checkpoint).expanduser().resolve()
    preflight = _preflight(repo, args.device)
    if not preflight.get("ok"):
        _respond(preflight)
        return 2

    worker = WanWorker(
        repo=repo,
        checkpoint=checkpoint,
        device_id=args.device,
        offload_model=args.offload_model,
        t5_cpu=args.t5_cpu,
        convert_model_dtype=args.convert_model_dtype,
    )
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
                        "message": "Unknown Wan 2.2 worker action",
                    }
                )
        except Exception as exc:
            _respond(_safe_error(exc, stage="protocol"))

    worker.release()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--offload-model", action="store_true")
    parser.add_argument("--t5-cpu", action="store_true")
    parser.add_argument("--convert-model-dtype", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--serve", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if args.preflight:
        _respond(_preflight(repo, args.device))
        return 0
    if args.serve:
        return _serve(args)
    _respond(
        {
            "ok": False,
            "error_type": "protocol_error",
            "message": "Wan 2.2 worker mode was not selected",
        }
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
