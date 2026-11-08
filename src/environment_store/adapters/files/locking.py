"""Per-store exclusive lock files for the file adapters.

POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking`, which is unverified in V2.0 (Windows is
not tested). Both locks belong to an open file description, so two adapters in one process, two
threads or two processes exclude each other alike. Locking polls with a non-blocking call, so a
stuck holder makes the caller fail with `BackendError` instead of hanging forever.
"""

import os
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from environment_store.core.errors import BackendError

__all__ = ["exclusive_lock"]

_POLL_INTERVAL: Final[float] = 0.005

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(path: Path, *, timeout: float) -> Generator[None]:
    """Hold an exclusive lock on `path` (created if missing, mode 0600) inside the block.

    The lock file is never removed: deleting it while another process waits on it would let
    two processes hold "the" lock at once.

    Args:
        path: The lock file.
        timeout: Seconds to wait for another holder to release the lock.

    Yields:
        Nothing; the lock is held until the block ends.

    Raises:
        BackendError: The lock file cannot be created or locked, or the lock was not acquired
            within `timeout` seconds. Errors raised inside the block pass through unchanged.
    """
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as err:
        message = f"could not open the lock file {path}: {err}"
        raise BackendError(message) from err
    try:
        _acquire(fd, path=path, timeout=timeout)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _acquire(fd: int, *, path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                message = (
                    f"could not lock {path} within {timeout:g} s: another process holds it; "
                    "try again"
                )
                raise BackendError(message)
            time.sleep(_POLL_INTERVAL)
    except OSError as err:
        message = f"could not lock {path}: {err}"
        raise BackendError(message) from err
