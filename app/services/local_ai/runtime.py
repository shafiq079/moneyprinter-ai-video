from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from app.utils import utils


ReleaseCallback = Callable[[], None]
ProcessLockFactory = Callable[[int], "_CrossProcessGpuLock"]


class _CrossProcessGpuLock:
    """Portable advisory lock for one configured CUDA device.

    The lock is file-backed so independent API worker processes serialize local
    GPU work. OS-level locks are released automatically if a process exits or
    crashes, unlike sentinel lock files that can become stale.
    """

    def __init__(
        self,
        device_id: int,
        *,
        lock_root: str | Path | None = None,
        poll_interval: float = 0.05,
    ) -> None:
        self.device_id = int(device_id)
        if self.device_id < 0:
            raise ValueError("CUDA device index must be >= 0")
        root = Path(
            lock_root
            if lock_root is not None
            else utils.storage_dir("local_ai_locks", create=True)
        )
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"gpu-{self.device_id}.lock"
        self.poll_interval = max(float(poll_interval), 0.01)
        self._stream: BinaryIO | None = None

    def acquire(self) -> None:
        if self._stream is not None:
            raise RuntimeError("cross-process GPU lock is already acquired")

        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                # msvcrt.locking locks a byte range. Ensure byte zero exists and
                # use non-blocking attempts so another worker can release cleanly.
                import msvcrt

                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                    os.fsync(stream.fileno())
                while True:
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(self.poll_interval)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        except Exception:
            stream.close()
            raise

        self._stream = stream

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class LocalAIRuntimeManager:
    """Serialize heavyweight local-video GPU work across threads and processes.

    The in-process RLock preserves model-family/runtime state. A per-CUDA-device
    advisory file lock additionally coordinates independent API worker processes,
    so two workers cannot load/generate on the same configured GPU concurrently.
    """

    def __init__(
        self,
        *,
        lock_root: str | Path | None = None,
        process_lock_factory: ProcessLockFactory | None = None,
    ) -> None:
        self._gpu_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._active_family: str | None = None
        self._release_callbacks: dict[str, ReleaseCallback] = {}
        self._thread_state = threading.local()
        if process_lock_factory is not None:
            self._process_lock_factory = process_lock_factory
        else:
            self._process_lock_factory = lambda device_id: _CrossProcessGpuLock(
                device_id,
                lock_root=lock_root,
            )

    def register_family(self, family: str, release: ReleaseCallback) -> None:
        if not family:
            raise ValueError("runtime family must not be empty")
        with self._state_lock:
            self._release_callbacks[family] = release

    @staticmethod
    def _normalize_device_id(device_id: int) -> int:
        try:
            parsed = int(device_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("CUDA device index must be an integer") from exc
        if parsed < 0:
            raise ValueError("CUDA device index must be >= 0")
        return parsed

    def _enter_process_lock(self, device_id: int) -> None:
        depth = int(getattr(self._thread_state, "process_lock_depth", 0) or 0)
        if depth:
            active_device = getattr(
                self._thread_state,
                "process_lock_device",
                None,
            )
            if active_device != device_id:
                raise RuntimeError(
                    "nested local AI runtime slots cannot switch CUDA devices"
                )
            self._thread_state.process_lock_depth = depth + 1
            return

        process_lock = self._process_lock_factory(device_id)
        process_lock.acquire()
        self._thread_state.process_lock = process_lock
        self._thread_state.process_lock_device = device_id
        self._thread_state.process_lock_depth = 1

    def _exit_process_lock(self) -> None:
        depth = int(getattr(self._thread_state, "process_lock_depth", 0) or 0)
        if depth <= 0:
            return
        if depth > 1:
            self._thread_state.process_lock_depth = depth - 1
            return

        process_lock = getattr(self._thread_state, "process_lock", None)
        self._thread_state.process_lock_depth = 0
        self._thread_state.process_lock_device = None
        self._thread_state.process_lock = None
        if process_lock is not None:
            process_lock.release()

    @contextmanager
    def generation_slot(
        self,
        family: str,
        device_id: int = 0,
    ) -> Iterator[None]:
        if not family:
            raise ValueError("runtime family must not be empty")
        normalized_device = self._normalize_device_id(device_id)

        with self._gpu_lock:
            self._enter_process_lock(normalized_device)
            try:
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
            finally:
                self._exit_process_lock()

    @property
    def active_family(self) -> str | None:
        with self._state_lock:
            return self._active_family

    def clear_active_family(self, family: str) -> None:
        with self._state_lock:
            if self._active_family == family:
                self._active_family = None


LOCAL_AI_RUNTIME = LocalAIRuntimeManager()
