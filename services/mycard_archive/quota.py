"""Incremental allocated-byte accounting for the MyCard evidence directory."""
from contextlib import contextmanager
import os
import stat
import threading
import time
import uuid


@contextmanager
def file_lock(file):
    if os.name == "nt":
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def allocated(info):
    return info.st_blocks * 512 if hasattr(info, "st_blocks") else info.st_size


class ArchiveUsage:
    reconcile_seconds = 900

    def __init__(self, root):
        self.root = root
        self.marker = root / ".quota-generation"
        self.mutex = threading.RLock()
        self.handle = None
        self.generation = None
        self.nested = None
        self.checked = 0
        self.unit = os.statvfs(root).f_frsize if hasattr(os, "statvfs") else 4096

    @contextmanager
    def locked(self):
        with self.mutex:
            if self.handle is not None:
                yield
                return
            fd = os.open(self.marker, os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, "r+b", buffering=0) as handle, file_lock(handle):
                handle.seek(1)
                generation = handle.read(16)
                if len(generation) != 16:
                    generation = uuid.uuid4().bytes
                    handle.seek(1)
                    handle.write(generation)
                if generation != self.generation:
                    self.nested = None
                self.generation = generation
                self.handle = handle
                try:
                    yield
                finally:
                    self.handle = None

    def scan(self, directory, recurse):
        total = 0
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += allocated(entry.stat(follow_symlinks=False))
                    elif recurse and entry.is_dir(follow_symlinks=False):
                        total += self.scan(entry.path, True)
                except FileNotFoundError:
                    continue
        return total

    def total(self):
        with self.locked():
            now = time.monotonic()
            if self.nested is None or now - self.checked >= self.reconcile_seconds:
                with os.scandir(self.root) as entries:
                    self.nested = sum(self.scan(e.path, True) for e in entries
                                      if e.is_dir(follow_symlinks=False))
                self.checked = now
            # SQLite, WAL and other top-level files can change independently.
            return self.nested + self.scan(self.root, False)

    @staticmethod
    def size(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return 0
        return allocated(info) if stat.S_ISREG(info.st_mode) else 0

    @contextmanager
    def changing(self, path):
        """Invalidate peer caches before publication, then account the actual delta."""
        with self.locked():
            before = self.size(path)
            self.generation = uuid.uuid4().bytes
            self.handle.seek(1)
            self.handle.write(self.generation)
            try:
                yield
            except BaseException:
                self.nested = None
                raise
            else:
                if self.nested is not None:
                    self.nested += self.size(path) - before
