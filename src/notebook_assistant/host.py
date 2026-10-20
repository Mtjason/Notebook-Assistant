"""Who and where this install is: its machine config and its host profile, resolved once.

The profile is chosen in this order (docs/architecture.md §5.1): ``--profile``, then
``NA_PROFILE``, then ``profile`` in the per-machine ``config.yaml``, then detection from the host
and the vault's location.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from notebook_assistant.machine import MachineConfig, load_machine_config
from notebook_assistant.platform.profiles import (
    Profile,
    WatchMode,
    bitwarden_command,
    detect_profile,
    host_facts,
    parse_profile,
    watch_mode,
)


@dataclass(frozen=True)
class Host:
    machine: MachineConfig
    profile: Profile

    @property
    def watch(self) -> WatchMode:
        return watch_mode(self.profile)

    @property
    def bitwarden_path(self) -> str | None:
        """Where ``bw`` is on ``PATH``, or None when it's missing."""
        return shutil.which(bitwarden_command(self.profile))


def current_host(vault: str | None, profile_flag: str | None = None) -> Host:
    detected = detect_profile(host_facts(), vault)
    found = shutil.which(bitwarden_command(detected)) is not None
    machine = load_machine_config(profile=detected, bitwarden_found=found)
    chosen = profile_flag or os.environ.get("NA_PROFILE")
    if chosen:
        profile = parse_profile(chosen)
    else:
        profile = machine.profile or detect_profile(host_facts(), vault or machine.vault)
    return Host(machine, profile)
