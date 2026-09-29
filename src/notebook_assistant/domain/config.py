"""A vault's tunables: the typed, validated contents of ``Config.md`` (docs/architecture.md §4.1.1).

The schema is the dataclasses below (names and types); the values live only in the packaged
default ``Config.md``. A vault's own ``Config.md`` overrides any key. Every value is checked when
it's loaded, and anything wrong stops loading with a :class:`ConfigError` that names the key:

- a mapping at the top level must be a known section, and each key inside it a known setting;
- a value must have its setting's type (an ``int`` where a ``float`` is expected is fine);
- numbers must be positive, and a fraction at most 1.

Top-level keys that aren't mappings (``type``, ``kind``, dates) are the note's own properties,
not settings, and are ignored.

Pure: takes text, returns data. Reading the files is :mod:`notebook_assistant.config`.
"""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass
from typing import Any

import yaml

from notebook_assistant.domain.frontmatter import load_yaml
from notebook_assistant.domain.note import split_frontmatter


class ConfigError(ValueError):
    """A ``Config.md`` value is unknown, missing or of the wrong type."""


@dataclass(frozen=True)
class Models:
    """Model ID per task."""

    classify: str
    transform: str
    digest: str
    chat: str
    fallback: str


@dataclass(frozen=True)
class Limits:
    monthly_spend_usd: float
    max_tokens_per_job: int


@dataclass(frozen=True)
class Checks:
    preservation_similarity: float  # a fraction: at most 1


@dataclass(frozen=True)
class Coordination:
    stale_run_minutes: int


@dataclass(frozen=True)
class Extraction:
    related_notes: int


@dataclass(frozen=True)
class Config:
    models: Models
    limits: Limits
    checks: Checks
    coordination: Coordination
    extraction: Extraction


_FRACTIONS = {("checks", "preservation_similarity")}


def _settings(text: str, source: str) -> dict[str, Any]:
    """The mapping-valued top-level entries of a ``Config.md`` note's frontmatter."""
    fm_text, _ = split_frontmatter(text.replace("\r\n", "\n"))
    if fm_text is None:
        raise ConfigError(f"{source}: no frontmatter block")
    try:
        data = load_yaml(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: frontmatter must be a mapping")
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _check_value(section: str, key: str, value: object, expected: object, source: str) -> object:
    where = f"{source}: {section}.{key}"
    if expected is str:
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{where} must be a non-empty text value, not {value!r}")
        return value
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where} must be a whole number, not {value!r}")
    elif expected is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{where} must be a number, not {value!r}")
        value = float(value)
    else:
        raise TypeError(f"unsupported setting type for {section}.{key}: {expected!r}")
    assert isinstance(value, int | float)
    if value <= 0:
        raise ConfigError(f"{where} must be greater than 0, not {value!r}")
    if (section, key) in _FRACTIONS and value > 1:
        raise ConfigError(f"{where} must be at most 1, not {value!r}")
    return value


def _build_section(cls: type[Any], name: str, values: dict[str, Any], source: str) -> Any:
    hints = typing.get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise ConfigError(f"{source}: unknown setting(s) in {name}: {', '.join(unknown)}")
    missing = [f for f in fields if f not in values]
    if missing:
        raise ConfigError(f"{source}: {name} is missing {', '.join(missing)}")
    return cls(**{f: _check_value(name, f, values[f], hints[f], source) for f in fields})


def parse_config(default_text: str, vault_text: str | None = None) -> Config:
    """The effective config: the defaults, overridden key by key by the vault's ``Config.md``."""
    defaults = _settings(default_text, "default Config.md")
    overrides = _settings(vault_text, "Config.md") if vault_text is not None else {}
    sections = typing.get_type_hints(Config)
    unknown = sorted(set(overrides) - set(sections))
    if unknown:
        raise ConfigError(f"Config.md: unknown section(s): {', '.join(unknown)}")
    built: dict[str, Any] = {}
    for name, cls in sections.items():
        if name not in defaults:
            raise ConfigError(f"default Config.md: section {name} is missing")
        source = "Config.md" if name in overrides else "default Config.md"
        merged = {**defaults[name], **overrides.get(name, {})}
        built[name] = _build_section(cls, name, merged, source)
    return Config(**built)
