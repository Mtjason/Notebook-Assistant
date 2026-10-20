"""A vault seen through an in-memory layer: reads fall through to the base vault, while writes,
moves and deletes stay in memory. Used for dry runs (the Review screen's checks apply a
changeset here first), so nothing is copied up front and the real vault is never touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import PurePosixPath

from notebook_assistant.domain.names import name_key, respell_folders
from notebook_assistant.ports.vault import FileExistsInVaultError, VaultError, VaultStore


class OverlayVault:
    def __init__(self, base: VaultStore) -> None:
        self._base = base
        self._written: dict[str, tuple[PurePosixPath, bytes]] = {}
        self._deleted: set[str] = set()
        self._times: dict[str, datetime] = {}

    @staticmethod
    def _key(path: PurePosixPath) -> str:
        return name_key(path.as_posix())

    def _base_has(self, path: PurePosixPath) -> bool:
        return self._key(path) not in self._deleted and self._base.exists(path)

    def iter_files(self) -> Iterator[PurePosixPath]:
        seen: set[str] = set()
        for path in self._base.iter_files():
            key = self._key(path)
            if key in self._deleted or key in self._written:
                continue
            seen.add(key)
            yield path
        for key, (path, _) in sorted(self._written.items(), key=lambda item: item[1][0].as_posix()):
            if key not in seen and not any(part.startswith(".") for part in path.parts[:-1]):
                yield path

    def exists(self, path: PurePosixPath) -> bool:
        return self._key(path) in self._written or self._base_has(path)

    def read_bytes(self, path: PurePosixPath) -> bytes:
        written = self._written.get(self._key(path))
        if written is not None:
            return written[1]
        if not self._base_has(path):
            raise VaultError(f"no such file: {path}")
        return self._base.read_bytes(path)

    def read_text(self, path: PurePosixPath) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: PurePosixPath, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def _stored(self, path: PurePosixPath) -> PurePosixPath:
        """How the file is spelled if it exists, else ``path`` with existing folders' spelling."""
        key = self._key(path)
        written = self._written.get(key)
        if written is not None:
            return written[0]
        current = list(self.iter_files())
        return next((p for p in current if self._key(p) == key), None) or respell_folders(
            path, current
        )

    def write_bytes(self, path: PurePosixPath, data: bytes) -> None:
        self._written[self._key(path)] = (self._stored(path), data)
        self._times[self._key(path)] = datetime.now(UTC)

    def modified(self, path: PurePosixPath) -> datetime:
        if self._key(path) in self._written:
            return self._times[self._key(path)]
        if not self._base_has(path):
            raise VaultError(f"no such file: {path}")
        return self._base.modified(path)

    def move(self, src: PurePosixPath, dest: PurePosixPath) -> None:
        data = self.read_bytes(src)
        if self.exists(dest) and self._key(src) != self._key(dest):
            raise FileExistsInVaultError(f"target exists: {dest}")
        when = self.modified(src)
        self.delete(src)
        self._written[self._key(dest)] = (respell_folders(dest, list(self.iter_files())), data)
        self._times[self._key(dest)] = when

    def delete(self, path: PurePosixPath) -> None:
        if not self.exists(path):
            raise VaultError(f"no such file: {path}")
        key = self._key(path)
        self._written.pop(key, None)
        self._deleted.add(key)
