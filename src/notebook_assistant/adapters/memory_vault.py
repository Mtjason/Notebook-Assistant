"""An in-memory vault, for tests and dry runs. Behaves like the filesystem adapter."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from notebook_assistant.domain.names import name_key
from notebook_assistant.ports.vault import FileExistsInVaultError, VaultError


class MemoryVault:
    def __init__(self, files: Mapping[str, str | bytes] | None = None) -> None:
        self._files: dict[str, tuple[PurePosixPath, bytes]] = {}
        for path, data in (files or {}).items():
            raw = data.encode("utf-8") if isinstance(data, str) else data
            self._put(PurePosixPath(path), raw)

    def _put(self, path: PurePosixPath, data: bytes) -> None:
        self._files[name_key(path.as_posix())] = (self._spell_folders(path), data)

    def _spell_folders(self, path: PurePosixPath) -> PurePosixPath:
        """Reuse the spelling of folders that already exist (as NTFS and APFS do)."""
        parts = list(path.parts)
        for stored, _ in self._files.values():
            folders = stored.parts[:-1]
            for i in range(min(len(folders), len(parts) - 1)):
                if name_key(folders[i]) != name_key(parts[i]):
                    break
                parts[i] = folders[i]
        return PurePosixPath(*parts)

    def _get(self, path: PurePosixPath) -> tuple[PurePosixPath, bytes]:
        try:
            return self._files[name_key(path.as_posix())]
        except KeyError:
            raise VaultError(f"no such file: {path}") from None

    def iter_files(self) -> Iterator[PurePosixPath]:
        for path, _ in sorted(self._files.values(), key=lambda item: item[0].as_posix()):
            if not any(part.startswith(".") for part in path.parts[:-1]):
                yield path

    def exists(self, path: PurePosixPath) -> bool:
        return name_key(path.as_posix()) in self._files

    def read_bytes(self, path: PurePosixPath) -> bytes:
        return self._get(path)[1]

    def read_text(self, path: PurePosixPath) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: PurePosixPath, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: PurePosixPath, data: bytes) -> None:
        key = name_key(path.as_posix())
        existing = self._files.get(key)
        # like NTFS: writing to an existing file keeps its original spelling
        self._files[key] = (existing[0] if existing else self._spell_folders(path), data)

    def move(self, src: PurePosixPath, dest: PurePosixPath) -> None:
        stored_src, data = self._get(src)
        same_file = name_key(src.as_posix()) == name_key(dest.as_posix())
        if self.exists(dest) and not same_file:
            raise FileExistsInVaultError(f"target exists: {dest}")
        del self._files[name_key(stored_src.as_posix())]
        self._put(dest, data)

    def delete(self, path: PurePosixPath) -> None:
        stored, _ = self._get(path)
        del self._files[name_key(stored.as_posix())]

    def snapshot(self) -> dict[str, bytes]:
        """All files as {path: bytes}, for assertions."""
        return {p.as_posix(): d for p, d in self._files.values()}
