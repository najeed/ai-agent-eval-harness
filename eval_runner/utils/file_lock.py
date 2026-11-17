"""OS-backed serialization for reference providers that persist atomic files."""

import os
import threading
from contextlib import contextmanager

_THREAD_LOCK = threading.RLock()


@contextmanager
def directory_write_lock(directory, name=".provider-write.lock"):
    """Keep the lock inode stable while protected records are atomically replaced."""
    with _THREAD_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
