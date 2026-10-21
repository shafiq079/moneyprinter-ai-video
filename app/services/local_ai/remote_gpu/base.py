from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class RemoteGPUBackend(Protocol):
    """Transport boundary for a remote GPU execution service."""

    backend_id: str

    def preflight(self) -> dict[str, Any]: ...

    def generate(
        self,
        inputs: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]: ...
