"""The vault storage port.

All paths are vault-relative :class:`~pathlib.PurePosixPath` values using ``/``, whatever the
host OS. Adapters translate them to real paths.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Protocol


class VaultError(Exception):
    """Base class for storage errors."""


class FileBusyError(VaultError):
    """The file is locked by another program (e.g. Obsidian, Sync or antivirus on Windows)."""


class FileExistsInVaultError(VaultError):
    """A create or move target already exists (compared case-insensitively)."""


class VaultStore(Protocol):
    def iter_files(self) -> Iterator[PurePosixPath]:
        """Every file in the vault, excluding ``.obsidian/`` and other dot-folders."""
        ...

    def exists(self, path: PurePosixPath) -> bool:
        """Whether a file exists at ``path`` (case-insensitive, like NTFS and APFS)."""
        ...

    def read_bytes(self, path: PurePosixPath) -> bytes: ...

    def read_text(self, path: PurePosixPath) -> str:
        """Read UTF-8 text exactly as stored (line endings untouched)."""
        ...

    def write_text(self, path: PurePosixPath, text: str) -> None:
        """Atomically write UTF-8 text exactly as given, creating parent folders."""
        ...

    def write_bytes(self, path: PurePosixPath, data: bytes) -> None: ...

    def move(self, src: PurePosixPath, dest: PurePosixPath) -> None:
        """Move a file. Refuses to overwrite a different existing file."""
        ...

    def delete(self, path: PurePosixPath) -> None:
        """Delete a file and prune folders left empty."""
        ...
