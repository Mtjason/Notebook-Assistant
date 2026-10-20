"""``doctor``: check that this host can run the assistant (docs/architecture.md §5.5).

Each check returns a :class:`Check` (ok, warn or fail, with a one-line detail). A failure means
the assistant can't work here; a warning means a feature is off or degraded. Checks that reach
outside (the vault, the Claude API) take their effect as an argument, so they're testable.
"""

from __future__ import annotations

import locale
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from notebook_assistant.domain.config import ConfigError
from notebook_assistant.host import Host
from notebook_assistant.machine import SEARCH_OPTIONS
from notebook_assistant.ports.embedder import EmbedderError
from notebook_assistant.ports.llm import LLMError
from notebook_assistant.ports.vault import VaultError, VaultStore
from notebook_assistant.store import ASSISTANT_DIR

WRITE_TEST = ASSISTANT_DIR / "doctor write test.md"


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def check_profile(host: Host) -> Check:
    detail = (
        f"{host.profile.value} · file changes: {host.watch.value} · machine: {host.machine.name}"
    )
    return Check("profile", Status.OK, detail)


def check_encoding(utf8_mode: bool, preferred: str) -> Check:
    """UTF-8 everywhere (§5.2): Traditional-Chinese Windows would otherwise use cp950."""
    if utf8_mode or preferred.replace("-", "").lower() == "utf8":
        return Check("encoding", Status.OK, "UTF-8")
    return Check("encoding", Status.FAIL, f"{preferred}; set PYTHONUTF8=1 (§5.2)")


def check_vault(store: VaultStore | None, where: str | None) -> Check:
    """The vault exists and the assistant can write to its state folder (and clean up)."""
    if store is None:
        return Check("vault", Status.FAIL, "no vault: pass --vault or set vault in config.yaml")
    try:
        store.write_text(WRITE_TEST, "doctor write test\n")
        store.delete(WRITE_TEST)
    except (OSError, VaultError) as exc:
        return Check("vault", Status.FAIL, f"{where}: can't write to {ASSISTANT_DIR}: {exc}")
    return Check("vault", Status.OK, f"{where} · writable")


def check_config(load: Callable[[], object]) -> Check:
    """The vault's Config.md (over the packaged defaults) loads."""
    try:
        load()
    except ConfigError as exc:
        return Check("Config.md", Status.FAIL, str(exc))
    return Check("Config.md", Status.OK, "loads")


def check_bitwarden(host: Host) -> Check:
    found = host.bitwarden_path
    if not host.machine.bitwarden:
        return Check("bitwarden", Status.OK, "disabled on this machine (features.bitwarden)")
    if found is None:
        return Check("bitwarden", Status.WARN, "enabled, but `bw` isn't on PATH")
    return Check("bitwarden", Status.OK, found)


def check_claude_api(count_models: Callable[[], int]) -> Check:
    """The API is reachable and the credentials work: listing models is free and needs both."""
    try:
        count = count_models()
    except LLMError as exc:
        return Check("Claude API", Status.FAIL, str(exc))
    return Check("Claude API", Status.OK, f"reachable · authenticated · {count} models")


def check_search(host: Host, time_embedding: Callable[[], float]) -> Check:
    """The search option; with an embedding model, how long 16 passages take on this CPU
    (docs/architecture.md §4.3), or why the model can't run."""
    if host.machine.search == SEARCH_OPTIONS[0]:
        return Check("search", Status.OK, "keyword (full-text index)")
    try:
        seconds = time_embedding()
    except EmbedderError as exc:
        return Check("search", Status.WARN, f"{host.machine.search}: {exc}")
    return Check(
        "search", Status.OK, f"{host.machine.search}: 16 passages embedded in {seconds:.1f}s"
    )


def run_checks(
    host: Host,
    store: VaultStore | None,
    vault_label: str | None,
    *,
    load_config: Callable[[], object],
    count_models: Callable[[], int],
    time_embedding: Callable[[], float],
) -> list[Check]:
    checks = [
        check_profile(host),
        check_encoding(bool(sys.flags.utf8_mode), locale.getpreferredencoding(False)),
        check_vault(store, vault_label),
    ]
    if store is not None and checks[-1].status is Status.OK:
        checks.append(check_config(load_config))
    checks += [
        check_bitwarden(host),
        check_claude_api(count_models),
        check_search(host, time_embedding),
    ]
    return checks


def worst(checks: list[Check]) -> Status:
    order = [Status.OK, Status.WARN, Status.FAIL]
    return max((c.status for c in checks), key=order.index, default=Status.OK)
