from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator


ReleaseCallback = Callable[[], None]


class LocalAIRuntimeManager:
    """Serialize heavyweight local-video GPU work inside one app process.

    MoneyPrinterTurbo's default task manager is thread-based, so this protects
    concurrent tasks in the same process. It deliberately does not claim
    cross-process coordination; deployments that run multiple API worker
    processes must keep local GPU inference in one worker process or add a
    distributed/file-backed guard later.
    """

    def __init__(self) -> None:
        self._gpu_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._active_family: str | None = None
        self._release_callbacks: dict[str, ReleaseCallback] = {}

    def register_family(self, family: str, release: ReleaseCallback) -> None:
        if not family:
            raise ValueError("runtime family must not be empty")
        with self._state_lock:
            self._release_callbacks[family] = release

    @contextmanager
    def generation_slot(self, family: str) -> Iterator[None]:
        if not family:
            raise ValueError("runtime family must not be empty")

        with self._gpu_lock:
            with self._state_lock:
                previous_family = self._active_family
                previous_release = (
                    self._release_callbacks.get(previous_family)
                    if previous_family and previous_family != family
                    else None
                )

            if previous_release is not None:
                previous_release()

            with self._state_lock:
                self._active_family = family

            yield

    @property
    def active_family(self) -> str | None:
        with self._state_lock:
            return self._active_family

    def clear_active_family(self, family: str) -> None:
        with self._state_lock:
            if self._active_family == family:
                self._active_family = None


LOCAL_AI_RUNTIME = LocalAIRuntimeManager()
