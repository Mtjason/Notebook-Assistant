"""The images a note embeds, read for the model (Handbook §19.3: screenshots are read and cited
as "screenshot N"), and which file types count as images."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.note import Note
from notebook_assistant.ports.llm import Image, MediaType
from notebook_assistant.ports.vault import VaultStore

IMAGE_TYPES: dict[str, MediaType] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def media_type(path: PurePosixPath) -> MediaType | None:
    return IMAGE_TYPES.get(path.suffix.lower())


def embedded_images(index: VaultIndex, note: Note) -> list[PurePosixPath]:
    """The vault paths of the images ``note`` embeds, in order, each once."""
    found: list[PurePosixPath] = []
    for link in find_links(note.body):
        target = index.resolver.resolve(link, note.path) if link.embed else None
        if target is not None and media_type(target) and target not in found:
            found.append(target)
    return found


def screenshots(store: VaultStore, index: VaultIndex, note: Note) -> list[Image]:
    """The images the note embeds, labelled "screenshot N: <file>" (§19.3)."""
    images: list[Image] = []
    for n, path in enumerate(embedded_images(index, note), start=1):
        media = media_type(path)
        assert media is not None
        images.append(Image(f"screenshot {n}: {path.name}", media, store.read_bytes(path)))
    return images
