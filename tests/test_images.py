"""The images a note embeds, read for the model."""

from __future__ import annotations

from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.images import embedded_images, media_type, screenshots
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.domain.note import Note

P = PurePosixPath
NOTE = Note(
    path=P("00-Inbox/n.md"),
    body="![[Polars with_columns - 1.png]] ![[Polars with_columns - 1.png]] ![[x.pdf]] [[y.png]]\n",
)


def test_media_types_come_from_the_suffix() -> None:
    assert media_type(P("a/B.JPG")) == "image/jpeg" and media_type(P("a.pdf")) is None


def test_embedded_images_are_listed_once_in_order(memory_vault: MemoryVault) -> None:
    index = VaultIndex.build(memory_vault)
    assert embedded_images(index, NOTE) == [P("Attachments/Polars with_columns - 1.png")]
    [image] = screenshots(memory_vault, index, NOTE)
    assert image.label == "screenshot 1: Polars with_columns - 1.png"
    assert image.media_type == "image/png" and image.data.startswith(b"\x89PNG")
