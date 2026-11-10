"""Lock a file so only one process at a time does a job, on any operating system.

macOS and Linux provide `fcntl`; Windows provides `msvcrt` instead. The rest of
the project calls try_lock()/unlock() and does not need to know which is used.
"""

import os

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


def _descriptor(handle) -> int:
    """Accept either an open file object or a number from os.open()."""
    return handle if isinstance(handle, int) else handle.fileno()


def try_lock(handle) -> None:
    """Take the lock now, or raise BlockingIOError if another holder has it."""
    descriptor = _descriptor(handle)
    if fcntl:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    # Windows locks a range of bytes starting at the current position, so
    # every holder must lock the same place: the first byte.
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    except OSError as error:
        raise BlockingIOError(str(error)) from error


def unlock(handle) -> None:
    descriptor = _descriptor(handle)
    if fcntl:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass  # closing the file releases the lock anyway
