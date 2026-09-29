"""Load a vault's tunables (docs/architecture.md §4.1.1).

The packaged ``default_config.md`` holds every setting's default; the vault's own
``99-System/Assistant/Config.md``, when it exists, overrides any of them. Parsing and validation
are :mod:`notebook_assistant.domain.config`.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from notebook_assistant.domain.config import Config, parse_config
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import ASSISTANT_DIR

CONFIG_NOTE = ASSISTANT_DIR / "Config.md"
DEFAULT_NAME = "default_config.md"


@cache
def default_config_text() -> str:
    return (resources.files("notebook_assistant") / DEFAULT_NAME).read_text(encoding="utf-8")


def load_default_config() -> Config:
    """The defaults alone, for a vault without its own ``Config.md``."""
    return parse_config(default_config_text())


def load_config(store: VaultStore) -> Config:
    """The effective config of the vault behind ``store``."""
    vault_text = store.read_text(CONFIG_NOTE) if store.exists(CONFIG_NOTE) else None
    return parse_config(default_config_text(), vault_text)
