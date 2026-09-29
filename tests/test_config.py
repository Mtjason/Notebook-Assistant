"""Config.md: defaults come from one packaged file, a vault overrides them, mistakes fail loudly."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.config import (
    CONFIG_NOTE,
    default_config_text,
    load_config,
    load_default_config,
)
from notebook_assistant.domain.config import ConfigError, parse_config

DEFAULT = default_config_text()
ARCHITECTURE = Path(__file__).resolve().parents[1] / "docs" / "architecture.md"


def vault_config(body: str) -> str:
    return f"---\ntype: system\nkind: config\n{body}---\n"


def test_defaults_parse_into_every_section() -> None:
    config = load_default_config()
    assert config.models.digest and config.models.fallback
    assert 0 < config.checks.preservation_similarity <= 1
    assert config.limits.max_tokens_per_job > 0
    assert config.coordination.stale_run_minutes > 0
    assert config.extraction.related_notes > 0


def test_a_vault_overrides_single_keys_and_keeps_the_rest() -> None:
    config = parse_config(DEFAULT, vault_config("checks:\n  preservation_similarity: 0.8\n"))
    assert config.checks.preservation_similarity == 0.8
    assert config.models == load_default_config().models


def test_load_config_reads_the_vault_note_when_present() -> None:
    assert load_config(MemoryVault()) == load_default_config()
    store = MemoryVault({CONFIG_NOTE.as_posix(): vault_config("extraction:\n  related_notes: 3\n")})
    assert load_config(store).extraction.related_notes == 3


def test_note_properties_are_not_settings() -> None:
    text = vault_config("created: 2026-09-30\naliases: [設定]\n")
    assert parse_config(DEFAULT, text) == load_default_config()


def test_whole_numbers_are_accepted_where_a_fraction_is_expected() -> None:
    config = parse_config(DEFAULT, vault_config("checks:\n  preservation_similarity: 1\n"))
    assert config.checks.preservation_similarity == 1.0


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("limts:\n  monthly_spend_usd: 5\n", "unknown section(s): limts"),
        ("limits:\n  monthly_spend: 5\n", "unknown setting(s) in limits: monthly_spend"),
        ("limits:\n  max_tokens_per_job: 1.5\n", "limits.max_tokens_per_job must be a whole"),
        ("limits:\n  max_tokens_per_job: true\n", "limits.max_tokens_per_job must be a whole"),
        ("limits:\n  monthly_spend_usd: lots\n", "limits.monthly_spend_usd must be a number"),
        ("limits:\n  monthly_spend_usd: 0\n", "must be greater than 0"),
        ("checks:\n  preservation_similarity: 1.5\n", "must be at most 1"),
        ("models:\n  chat: ''\n", "models.chat must be a non-empty text"),
    ],
)
def test_mistakes_fail_loudly_and_name_the_key(body: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        parse_config(DEFAULT, vault_config(body))


def test_a_note_without_frontmatter_or_with_bad_yaml_is_rejected() -> None:
    with pytest.raises(ConfigError, match="no frontmatter"):
        parse_config(DEFAULT, "just text\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        parse_config(DEFAULT, "---\nlimits: [\n---\n")


def test_a_default_missing_a_section_is_a_packaging_error() -> None:
    broken = DEFAULT.replace("extraction:", "extractions:")
    with pytest.raises(ConfigError, match=re.escape("section extraction is missing")):
        parse_config(broken)


def test_architecture_links_to_the_defaults_instead_of_copying_them() -> None:
    """§4.1.1 links to the packaged file for defaults instead of copying them (one source)."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "src/notebook_assistant/default_config.md" in text
    assert "preservation_similarity: 0.9" not in text
