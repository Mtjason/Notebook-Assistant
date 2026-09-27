"""File and folder names that are valid on Windows, macOS and Linux at once.

The vault syncs between operating systems, so every host applies the strictest combined rules
(Handbook §5, docs/architecture.md §5.2):

- no ``< > : " / \\ | ? *`` or control characters, no trailing dot or space;
- no Windows reserved device names (``CON``, ``NUL``, ``COM1`` …), with or without an extension;
- names compared case-insensitively after Unicode NFC normalization;
- name ≤ 100 characters and vault-relative path ≤ 200 characters.

Handbook §5 additionally forbids ``# ^ [ ]`` in note titles because they break Obsidian links.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

MAX_NAME_LENGTH = 100
MAX_PATH_LENGTH = 200

_FORBIDDEN_FS = set('<>:"/\\|?*')
_FORBIDDEN_TITLE = set("#^[]")
_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def nfc(text: str) -> str:
    """Return ``text`` in Unicode NFC (composed) form."""
    return unicodedata.normalize("NFC", text)


def name_key(name: str) -> str:
    """Comparison key for names: NFC-normalized and case-folded.

    Two names with the same key are the same file on NTFS and default APFS.
    """
    return nfc(name).casefold()


def validate_name(name: str, *, is_note_title: bool = False) -> list[str]:
    """Return every rule ``name`` breaks, as human-readable messages (empty if valid).

    ``name`` is a single path component (file or folder name, extension included for files).
    With ``is_note_title`` the Obsidian-specific title rules (Handbook §5) are applied too.
    """
    problems: list[str] = []
    if not name or not name.strip():
        return ["name is empty"]
    if name != nfc(name):
        problems.append("name is not NFC-normalized")
    bad = sorted({c for c in name if c in _FORBIDDEN_FS or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c) for c in bad)
        problems.append(f"contains characters not allowed in file names: {shown}")
    if is_note_title:
        bad_title = sorted({c for c in name if c in _FORBIDDEN_TITLE})
        if bad_title:
            problems.append(f"contains characters that break links: {' '.join(bad_title)}")
    if name.endswith((".", " ")):
        problems.append("ends with a dot or a space")
    if name.startswith(" "):
        problems.append("starts with a space")
    stem = name.split(".", 1)[0].strip().upper()
    if stem in _RESERVED:
        problems.append(f"{stem} is a reserved device name on Windows")
    if len(name) > MAX_NAME_LENGTH:
        problems.append(f"longer than {MAX_NAME_LENGTH} characters")
    return problems


def validate_path(path: PurePosixPath) -> list[str]:
    """Validate every component of a vault-relative path, plus the total length."""
    problems: list[str] = []
    if path.is_absolute():
        return ["path must be relative to the vault root"]
    if any(part in ("", ".", "..") for part in path.parts):
        return ["path must not contain '.' or '..' components"]
    for i, part in enumerate(path.parts):
        is_title = i == len(path.parts) - 1 and part.endswith(".md")
        title = part[: -len(".md")] if is_title else part
        for problem in validate_name(title, is_note_title=is_title):
            problems.append(f"{part!r}: {problem}")
    if len(path.as_posix()) > MAX_PATH_LENGTH:
        problems.append(f"path longer than {MAX_PATH_LENGTH} characters")
    return problems


_UNSAFE_RUN = re.compile(r'[<>:"/\\|?*#^\[\]\x00-\x1f]+')


def sanitize_title(title: str) -> str:
    """Make ``title`` usable as a note title by replacing forbidden characters.

    ``?`` becomes the full-width ``？`` (Handbook §5: question tasks); ``:`` becomes `` -``;
    other forbidden runs become a single space. The result is trimmed and cut to length.
    """
    text = nfc(title).replace("?", "？").replace(":", " -")
    text = _UNSAFE_RUN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) > MAX_NAME_LENGTH - 3:  # leave room for ".md"
        text = text[: MAX_NAME_LENGTH - 3].rstrip(" .")
    return text or "Untitled"
