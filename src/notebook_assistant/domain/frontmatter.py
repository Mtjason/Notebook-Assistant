"""YAML frontmatter: parse, edit with minimal diffs, and emit in the vault's style.

Frontmatter is the ``---``-delimited YAML block at the very top of a note (Handbook §4).

Design choices:

- **Minimal diffs.** A :class:`Frontmatter` keeps the original text of every top-level entry.
  Setting one property rewrites only that entry's lines; everything else stays byte-identical,
  including your own formatting and comments.
- **Strings stay strings.** Dates (``2026-09-27``) are kept as text, and only ``true``/``false``
  are booleans. YAML 1.1 would otherwise turn ``on``, ``yes`` or ``no`` into booleans.
- **Canonical key order** (:data:`KEY_ORDER`) decides where a *new* key is inserted, matching
  the order the migration used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

KEY_ORDER: tuple[str, ...] = (
    "id", "type", "kind", "scope", "status", "created", "updated", "date", "started", "ended",
    "topic", "project", "area", "idea", "domain", "trigger", "last_verified", "platform",
    "service", "url", "username", "auth", "key", "value", "context", "priority", "due",
    "waiting_on", "recurrence", "produced", "resource", "outcome", "effort", "question",
    "next_step", "promoted_to", "symptom", "fix", "captured", "processed", "attendees",
    "decisions", "source", "aliases", "tags", "origin", "sensitive", "needs_review",
    "handbook_gap", "assistant", "digest", "digest_reason", "digest_runner", "digest_started",
    "digest_feedback", "graduated_via", "archived", "archive_reason", "version", "assistant_hash",
)  # fmt: skip
_ORDER_INDEX = {k: i for i, k in enumerate(KEY_ORDER)}

_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:(?:[ \t]|$)")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLAIN_SAFE = re.compile(r"^[^\s\-?:,\[\]{}#&*!|>'\"%@`][^:#,\[\]{}\n]*$")
_YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}
_NON_PRINTABLE = re.compile(
    # characters YAML refuses, plus the Unicode line breaks it would fold to a space
    f"{yaml.reader.Reader.NON_PRINTABLE.pattern}|[\x85  ]"
)
_NUMBER = re.compile(r"^[-+]?(\d[\d_]*(\.\d*)?|\.\d+)([eE][-+]?\d+)?$|^0[xob][0-9a-fA-F_]+$")


class FrontmatterError(ValueError):
    """The frontmatter block exists but is not valid YAML mapping."""


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as strings and knows only true/false as booleans."""


_REPLACED_TAGS = {
    "tag:yaml.org,2002:timestamp",  # dates stay strings
    "tag:yaml.org,2002:bool",  # YAML 1.1 treats on/off/yes/no as booleans
    "tag:yaml.org,2002:int",  # YAML 1.1 reads 1:30 as a base-60 number
    "tag:yaml.org,2002:float",
}
_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag not in _REPLACED_TAGS]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _add_resolver(tag: str, pattern: str, first_chars: str) -> None:
    regexp = re.compile(pattern)
    for first in first_chars:
        _Loader.yaml_implicit_resolvers.setdefault(first, []).append((tag, regexp))


_add_resolver("tag:yaml.org,2002:bool", r"^(?:true|True|TRUE|false|False|FALSE)$", "tTfF")
_add_resolver("tag:yaml.org,2002:int", r"^[-+]?(?:0|[1-9][0-9]*)$", "-+0123456789")
_add_resolver(
    "tag:yaml.org,2002:float",
    r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$",
    "-+.0123456789",
)


def load_yaml(text: str) -> Any:
    """Parse YAML with the vault's rules (dates stay strings, only true/false are booleans)."""
    return yaml.load(text, Loader=_Loader)  # _Loader derives from SafeLoader


# --------------------------------------------------------------------------- emitting values


def _plain_ok(s: str) -> bool:
    if not s or s != s.strip() or s.lower() in _YAML_WORDS or _NUMBER.match(s):
        return False
    if not s.isprintable():  # control characters must be escaped in a quoted string
        return False
    if " #" in s or ": " in s or s.endswith(":"):
        return False
    return bool(_PLAIN_SAFE.match(s))


def format_scalar(value: Any, *, in_flow: bool = False) -> str:
    """Emit one scalar as YAML, plain when that is unambiguous, double-quoted otherwise."""
    if value is None:
        return "null" if in_flow else ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if not isinstance(value, str):
        raise TypeError(f"unsupported frontmatter value type: {type(value).__name__}")
    if _DATE.match(value):
        return value
    if _plain_ok(value) and not (in_flow and "," in value):
        return value
    return _quote(value)


def _quote(value: str) -> str:
    """A YAML double-quoted scalar. JSON escaping is valid YAML; characters YAML refuses even
    when quoted (DEL, C1 controls, lone surrogates) are escaped as well."""

    def esc(m: re.Match[str]) -> str:
        code = ord(m.group())
        return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"

    return _NON_PRINTABLE.sub(esc, json.dumps(value, ensure_ascii=False))


def format_entry(key: str, value: Any) -> str:
    """Emit ``key: value`` as one or more lines (no trailing newline).

    Scalar lists use flow style (``[a, b]``), as the vault does for ``aliases`` and ``tags``.
    Mappings and lists of mappings use block style.
    """
    if isinstance(value, list):
        if all(not isinstance(v, dict | list) for v in value):
            return f"{key}: [" + ", ".join(format_scalar(v, in_flow=True) for v in value) + "]"
        dumped = yaml.safe_dump(
            value, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        return f"{key}:\n" + "\n".join("  " + ln for ln in dumped.rstrip("\n").split("\n"))
    if isinstance(value, dict):
        dumped = yaml.safe_dump(
            value, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        return f"{key}:\n" + "\n".join("  " + ln for ln in dumped.rstrip("\n").split("\n"))
    scalar = format_scalar(value)
    return f"{key}: {scalar}" if scalar else f"{key}:"


# --------------------------------------------------------------------------- the block


@dataclass
class _Entry:
    key: str | None  # None for leading comments/blank lines before the first key
    lines: list[str]


@dataclass
class Frontmatter:
    """An editable frontmatter block that preserves the text of untouched entries."""

    _entries: list[_Entry] = field(default_factory=list)
    _values: dict[str, Any] = field(default_factory=dict)

    # ----- construction

    @classmethod
    def parse(cls, text: str) -> Frontmatter:
        """Parse the YAML between the ``---`` fences (without the fences)."""
        try:
            data = load_yaml(text) if text.strip() else {}
        except yaml.YAMLError as exc:
            raise FrontmatterError(f"invalid YAML: {exc}") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise FrontmatterError("frontmatter must be a mapping of properties")
        entries: list[_Entry] = []
        for line in text.split("\n") if text else []:
            m = _TOP_KEY.match(line)
            if m:
                entries.append(_Entry(m.group(1), [line]))
            elif entries:
                entries[-1].lines.append(line)
            else:
                entries.append(_Entry(None, [line]))
        values = {str(k): v for k, v in data.items()}
        return cls(entries, values)

    @classmethod
    def from_dict(cls, props: Mapping[str, Any]) -> Frontmatter:
        """Build a block from values, in canonical key order. ``None``/empty values are skipped."""
        fm = cls()
        for key in sorted(props, key=lambda k: (_ORDER_INDEX.get(k, len(KEY_ORDER)), 0)):
            value = props[key]
            if value is None or value == [] or value == "":
                continue
            fm.set(key, value)
        return fm

    # ----- reading

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def to_dict(self) -> dict[str, Any]:
        return dict(self._values)

    def get_list(self, key: str) -> list[Any]:
        """Return a property as a list (a scalar becomes a one-item list, missing → [])."""
        value = self._values.get(key)
        if value is None:
            return []
        return list(value) if isinstance(value, list) else [value]

    # ----- editing

    def set(self, key: str, value: Any) -> None:
        """Set a property. Only its own lines change; a new key is inserted in canonical order."""
        if key in self._values and self._values[key] == value:
            return
        new_lines = format_entry(key, value).split("\n")
        for entry in self._entries:
            if entry.key == key:
                trailing = _trailing_blank(entry.lines)
                entry.lines = new_lines + trailing
                self._values[key] = value
                return
        self._entries.insert(self._insert_at(key), _Entry(key, new_lines))
        self._values[key] = value

    def delete(self, key: str) -> None:
        """Remove a property (no-op if absent)."""
        self._entries = [e for e in self._entries if e.key != key]
        self._values.pop(key, None)

    def _insert_at(self, key: str) -> int:
        rank = _ORDER_INDEX.get(key, len(KEY_ORDER))
        position = len(self._entries)
        # after the last entry whose canonical rank is <= ours; unknown keys go last
        for i, entry in enumerate(self._entries):
            if entry.key is None:
                continue
            if _ORDER_INDEX.get(entry.key, len(KEY_ORDER)) > rank:
                position = i
                break
        return position

    # ----- output

    def render(self) -> str:
        """The block's text between the fences, without a trailing newline."""
        lines: list[str] = []
        for entry in self._entries:
            lines.extend(entry.lines)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)


def _trailing_blank(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in reversed(lines[1:]):
        if line.strip() == "" or line.lstrip().startswith("#"):
            out.append(line)
        else:
            break
    return list(reversed(out))
