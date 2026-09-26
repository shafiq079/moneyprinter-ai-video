from __future__ import annotations

import subprocess
from pathlib import Path

from app.utils import utils

from .base import GenerationResult, SceneSpec
from .media import validate_video_clip


class FakeLocalVideoProvider:
    """CPU/CI provider that renders obvious solid-color test clips with FFmpeg."""

    provider_id = "__local_ai_fake__"
    model_fingerprint = "fake-local-video:v1"

    def __init__(self, fail_scene_ids: set[int] | None = None):
        self.fail_scene_ids = set(fail_scene_ids or ())
        self.runtime_loaded = False
        self.runtime_load_count = 0
        self.generated_scene_ids: list[int] = []

    def preflight(self) -> None:
        if not utils.check_ffmpeg_ready():
            raise RuntimeError("fake local video provider requires FFmpeg")

    def load_runtime(self) -> None:
        if not self.runtime_loaded:
            self.runtime_loaded = True
            self.runtime_load_count += 1

    @staticmethod
    def _resolution(aspect: str) -> tuple[int, int]:
        if aspect == "9:16":
            return 360, 640
        if aspect == "16:9":
            return 640, 360
        return 480, 480

    def generate(self, scene: SceneSpec, output_path: Path) -> None:
        if not self.runtime_loaded:
            raise RuntimeError("fake provider runtime must be loaded before generation")
        if scene.scene_id in self.fail_scene_ids:
            raise RuntimeError(f"intentional fake failure for scene {scene.scene_id}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        width, height = self._resolution(scene.aspect)
        colors = ("0x17324d", "0x274c3c", "0x493664", "0x5b3b2f")
        color = colors[(scene.scene_id - 1) % len(colors)]
        command = [
            utils.get_ffmpeg_binary(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c={color}:s={width}x{height}:"
                f"r=24:d={float(scene.target_duration):.3f}"
            ),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            output.unlink(missing_ok=True)
            detail = (completed.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else "unknown FFmpeg failure"
            raise RuntimeError(f"fake clip generation failed: {tail}")

        self.generated_scene_ids.append(scene.scene_id)

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
        self.runtime_loaded = False
