"""File and folder names that are valid on Windows, macOS and Linux at once.

The rules (forbidden characters, reserved names, length limits) are defined once, in Handbook
§5.1, and arrive here as :class:`NameRules` parsed from it. This module only applies them.
Case-insensitive, NFC-normalized comparison (:func:`name_key`) is how §5.1's "same name" is
implemented.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class NameRules:
    """Handbook §5.1, as parsed by :func:`notebook_assistant.domain.rules.parse_handbook`."""

    forbidden: frozenset[str]  # in any file or folder name (control characters always)
    forbidden_in_titles: frozenset[str]  # additionally in note titles
    reserved: frozenset[str]  # upper-case stems
    max_name: int
    max_path: int


def nfc(text: str) -> str:
    """Return ``text`` in Unicode NFC (composed) form."""
    return unicodedata.normalize("NFC", text)


def name_key(name: str) -> str:
    """Comparison key for names: NFC-normalized and case-folded.

    Two names with the same key are the same file on NTFS and default APFS.
    """
    return nfc(name).casefold()


def validate_name(name: str, rules: NameRules, *, is_note_title: bool = False) -> list[str]:
    """Return every §5.1 rule ``name`` breaks, as human-readable messages (empty if valid).

    ``name`` is a single path component (file or folder name, extension included for files).
    With ``is_note_title`` the title-only characters are checked too.
    """
    problems: list[str] = []
    if not name or not name.strip():
        return ["name is empty"]
    if name != nfc(name):
        problems.append("name is not NFC-normalized")
    bad = sorted({c for c in name if c in rules.forbidden or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c) for c in bad)
        problems.append(f"contains characters not allowed in file names: {shown}")
    if is_note_title:
        bad_title = sorted({c for c in name if c in rules.forbidden_in_titles})
        if bad_title:
            problems.append(f"contains characters that break links: {' '.join(bad_title)}")
    if name.endswith((".", " ")):
        problems.append("ends with a dot or a space")
    if name.startswith(" "):
        problems.append("starts with a space")
    stem = name.split(".", 1)[0].strip().upper()
    if stem in rules.reserved:
        problems.append(f"{stem} is a reserved device name on Windows")
    if len(name) > rules.max_name:
        problems.append(f"longer than {rules.max_name} characters")
    return problems


def validate_path(path: PurePosixPath, rules: NameRules) -> list[str]:
    """Validate every component of a vault-relative path, plus the total length."""
    problems: list[str] = []
    if path.is_absolute():
        return ["path must be relative to the vault root"]
    if any(part in ("", ".", "..") for part in path.parts):
        return ["path must not contain '.' or '..' components"]
    for i, part in enumerate(path.parts):
        is_title = i == len(path.parts) - 1 and part.endswith(".md")
        title = part[: -len(".md")] if is_title else part
        for problem in validate_name(title, rules, is_note_title=is_title):
            problems.append(f"{part!r}: {problem}")
    if len(path.as_posix()) > rules.max_path:
        problems.append(f"path longer than {rules.max_path} characters")
    return problems


def sanitize_title(title: str, rules: NameRules) -> str:
    """Make ``title`` usable as a note title by replacing the characters §5.1 forbids.

    ``?`` becomes the full-width ``？`` (Handbook §5: question tasks); ``:`` becomes `` -``;
    other forbidden runs become a single space. The result is trimmed and cut to length.
    """
    text = nfc(title).replace("?", "？").replace(":", " -")
    unsafe = rules.forbidden | rules.forbidden_in_titles
    text = "".join(" " if c in unsafe or ord(c) < 32 else c for c in text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) > rules.max_name - 3:  # leave room for ".md"
        text = text[: rules.max_name - 3].rstrip(" .")
    return text or "Untitled"
