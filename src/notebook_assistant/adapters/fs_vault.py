"""The real vault on disk.

Portable file handling (docs/architecture.md §5.2):

- text is always UTF-8 and written byte-for-byte (``newline=""``: line endings untouched);
- writes are atomic: a temp file in the same folder, then ``os.replace`` over the target;
- on Windows, a file locked by Obsidian, Sync or antivirus raises ``PermissionError``;
  it is retried with backoff and finally reported as :class:`FileBusyError`;
- lookups are case-insensitive even on case-sensitive filesystems, so behaviour matches NTFS/APFS;
- folders emptied by a move or delete are removed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import TypeVar

from notebook_assistant.domain.names import name_key
from notebook_assistant.ports.vault import FileBusyError, FileExistsInVaultError, VaultError

T = TypeVar("T")

TEMP_SUFFIX = ".na-tmp"
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)


def _retry(action: Callable[[], T], what: str) -> T:
    for delay in (*_RETRY_DELAYS, None):
        try:
            return action()
        except PermissionError as exc:
            if delay is None:
                raise FileBusyError(f"{what}: file is locked by another program") from exc
            time.sleep(delay)
    raise AssertionError("unreachable")


class FsVault:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise VaultError(f"vault folder not found: {self.root}")

    # ----- path mapping

    def _real(self, path: PurePosixPath) -> Path:
        if path.is_absolute() or ".." in path.parts:
            raise VaultError(f"path escapes the vault: {path}")
        return self.root.joinpath(*path.parts)

    def _find(self, path: PurePosixPath) -> Path | None:
        """The existing file matching ``path`` case-insensitively, or None."""
        exact = self._real(path)
        if exact.is_file():
            return exact
        current = self.root
        for part in path.parts:
            if not current.is_dir():
                return None
            key = name_key(part)
            match = next((c for c in current.iterdir() if name_key(c.name) == key), None)
            if match is None:
                return None
            current = match
        return current if current.is_file() else None

    # ----- VaultStore

    def iter_files(self) -> Iterator[PurePosixPath]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = Path(dirpath).relative_to(self.root)
            for name in sorted(filenames):
                if name.endswith(TEMP_SUFFIX):
                    continue
                yield PurePosixPath(*rel.parts, name)

    def exists(self, path: PurePosixPath) -> bool:
        return self._find(path) is not None

    def read_bytes(self, path: PurePosixPath) -> bytes:
        real = self._find(path)
        if real is None:
            raise VaultError(f"no such file: {path}")
        return _retry(real.read_bytes, f"read {path}")

    def read_text(self, path: PurePosixPath) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: PurePosixPath, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: PurePosixPath, data: bytes) -> None:
        target = self._find(path) or self._real(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}{TEMP_SUFFIX}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            _retry(lambda: os.replace(tmp, target), f"write {path}")
        finally:
            if tmp.exists():
                tmp.unlink()

    def move(self, src: PurePosixPath, dest: PurePosixPath) -> None:
        real_src = self._find(src)
        if real_src is None:
            raise VaultError(f"no such file: {src}")
        existing = self._find(dest)
        case_only = existing is not None and existing.samefile(real_src)
        if existing is not None and not case_only:
            raise FileExistsInVaultError(f"target exists: {dest}")
        real_dest = self._real(dest)
        real_dest.parent.mkdir(parents=True, exist_ok=True)
        if case_only:
            # A case-only rename needs a hop through a temporary name on case-insensitive disks.
            hop = real_src.with_name(f".{real_src.name}{TEMP_SUFFIX}")
            _retry(lambda: os.replace(real_src, hop), f"move {src}")
            _retry(lambda: os.replace(hop, real_dest), f"move {src}")
        else:
            _retry(lambda: os.replace(real_src, real_dest), f"move {src}")
        self._prune(real_src.parent)

    def delete(self, path: PurePosixPath) -> None:
        real = self._find(path)
        if real is None:
            raise VaultError(f"no such file: {path}")
        _retry(real.unlink, f"delete {path}")
        self._prune(real.parent)

    def _prune(self, folder: Path) -> None:
        while folder != self.root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
