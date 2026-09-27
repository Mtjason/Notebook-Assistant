"""A note: its vault-relative path, frontmatter and body.

Line endings are preserved: the text is normalized to ``\\n`` internally and rendered back with
the note's original newline style (Handbook-independent file rule, docs/architecture.md §5.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from notebook_assistant.domain.frontmatter import Frontmatter

NOTE_SUFFIX = ".md"
CANVAS_SUFFIX = ".canvas"
EXCALIDRAW_SUFFIX = ".excalidraw.md"


def detect_newline(text: str) -> str:
    """Return ``\\r\\n`` if the text uses Windows line endings, else ``\\n``."""
    return "\r\n" if "\r\n" in text else "\n"


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split normalized text into (frontmatter text or None, body).

    Obsidian only recognizes frontmatter when ``---`` is the very first line and a closing
    ``---`` line follows.
    """
    if not text.startswith("---\n") and text != "---":
        return None, text
    end = text.find("\n---", 3)
    while end != -1:
        after = end + len("\n---")
        if after == len(text) or text[after] == "\n":
            fm_text = text[4:end] if end > 3 else ""
            body = text[after + 1 :] if after < len(text) else ""
            return fm_text, body
        end = text.find("\n---", end + 1)
    return None, text


def title_of(path: PurePosixPath) -> str:
    """The note title Obsidian shows: the file name without ``.md`` (``.excalidraw`` kept)."""
    name = path.name
    return name[: -len(NOTE_SUFFIX)] if name.endswith(NOTE_SUFFIX) else name


@dataclass
class Note:
    """A Markdown note. ``frontmatter`` is ``None`` when the note has no frontmatter block."""

    path: PurePosixPath
    body: str
    frontmatter: Frontmatter | None = None
    newline: str = "\n"
    _raw_fm: str | None = field(default=None, repr=False)

    @classmethod
    def parse(cls, path: PurePosixPath | str, text: str) -> Note:
        path = PurePosixPath(path)
        newline = detect_newline(text)
        normalized = text.replace("\r\n", "\n")
        fm_text, body = split_frontmatter(normalized)
        fm = Frontmatter.parse(fm_text) if fm_text is not None else None
        return cls(path=path, body=body, frontmatter=fm, newline=newline, _raw_fm=fm_text)

    # ----- convenience accessors

    @property
    def title(self) -> str:
        return title_of(self.path)

    @property
    def props(self) -> dict[str, Any]:
        return self.frontmatter.to_dict() if self.frontmatter else {}

    def prop(self, key: str, default: Any = None) -> Any:
        return self.frontmatter.get(key, default) if self.frontmatter else default

    @property
    def type(self) -> str | None:
        value = self.prop("type")
        return value if isinstance(value, str) else None

    @property
    def note_id(self) -> str | None:
        value = self.prop("id")
        return value if isinstance(value, str) else None

    def ensure_frontmatter(self) -> Frontmatter:
        if self.frontmatter is None:
            self.frontmatter = Frontmatter()
        return self.frontmatter

    # ----- output

    def render(self) -> str:
        """Full file text, with the note's original line endings."""
        if self.frontmatter is None:
            text = self.body
        else:
            fm_text = self.frontmatter.render()
            text = f"---\n{fm_text}\n---\n{self.body}" if fm_text else f"---\n---\n{self.body}"
        return text.replace("\n", self.newline) if self.newline != "\n" else text


def is_note_path(path: PurePosixPath) -> bool:
    return path.name.endswith(NOTE_SUFFIX)


def is_canvas_path(path: PurePosixPath) -> bool:
    return path.name.endswith(CANVAS_SUFFIX)
