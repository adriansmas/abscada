"""Writes that survive a power cut, and a lock shared by processes. No GUI dependencies."""
import os
from contextlib import contextmanager
from pathlib import Path


def sync(stream):
    """Data of an open file on disk before it is renamed over the original: otherwise the
    rename can reach the disk first and leave an empty or zero-filled file after a cut."""
    stream.flush()
    os.fsync(stream.fileno())


def write_synced(path, data):
    with open(path, "wb") as stream:
        stream.write(data)
        sync(stream)


def sync_directory(path):
    """The rename itself on disk (POSIX); Windows commits renames with the file system."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def exact_exists(path):
    """The file exists with exactly this name, letter case included (Windows ignores case)."""
    path = Path(path)
    try:
        return path.name in os.listdir(path.parent)
    except OSError:
        return False


@contextmanager
def file_lock(path):
    """Exclusive lock between processes (Studio and the Runtime) around a read-modify-write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)   # retries for up to 10 s
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def process_alive(pid):
    """A process with this id is still running (a lock left by a crash is not)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
