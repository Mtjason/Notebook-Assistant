from datetime import timedelta
from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import plan_move
from notebook_assistant.domain.invariants import is_checked
from notebook_assistant.handbook import load_rules
from notebook_assistant.store import changesets, lease, runs, snapshots
from tests.conftest import NOW

P = PurePosixPath


def test_changeset_record_round_trip(memory_vault: MemoryVault) -> None:
    cs = plan_move(
        VaultIndex.build(memory_vault),
        P("60-Knowledge/Software/Polars with_columns.md"),
        P("60-Knowledge/Software/Polars cols.md"),
        reason="Rename for clarity",
        created_by="user:cli",
        now=NOW,
    )
    path = changesets.save(memory_vault, cs)
    assert path == P(f"99-System/Assistant/Changesets/2026-09/{cs.id}.md")
    text = memory_vault.read_text(path)
    assert text.startswith("---\nid: cs-")
    assert "# Rename for clarity" in text and "````diff" in text
    assert "+aliases: [with_columns, Polars with_columns]" in text

    loaded = changesets.load(memory_vault, path)
    assert loaded.ops == cs.ops and loaded.status == cs.status and loaded.reason == cs.reason

    assert apply_changeset(memory_vault, loaded, now=NOW).ok
    changesets.save(memory_vault, loaded, with_diff=False)
    assert "+aliases: [with_columns, Polars with_columns]" in memory_vault.read_text(path)
    again = changesets.load(memory_vault, path)
    assert again.status.value == "applied" and again.reverse_ops == loaded.reverse_ops
    assert changesets.list_records(memory_vault) == [path]
    assert not is_checked(path, load_rules())  # machine state is exempt from the invariants


def test_state_files_are_outside_the_link_graph(memory_vault: MemoryVault) -> None:
    cs = plan_move(
        VaultIndex.build(memory_vault),
        P("60-Knowledge/Software/Python os.execv.md"),
        P("60-Knowledge/Software/Python execv.md"),
        reason="r",
        created_by="t",
        now=NOW,
    )
    changesets.save(memory_vault, cs)  # the record mentions [[Polars with_columns]] in JSON
    index = VaultIndex.build(memory_vault)
    sources = {
        r.source.as_posix()
        for r in index.backlinks(P("60-Knowledge/Software/Polars with_columns.md"))
    }
    assert not any(s.startswith("99-System/Assistant/") for s in sources)


def test_lease(memory_vault: MemoryVault) -> None:
    ttl = timedelta(minutes=30)
    assert lease.try_acquire(memory_vault, "personal-pc", NOW, ttl)
    assert not lease.try_acquire(memory_vault, "work-pc", NOW + timedelta(minutes=5), ttl)
    assert lease.try_acquire(memory_vault, "personal-pc", NOW + timedelta(minutes=5), ttl)  # renew
    assert lease.try_acquire(memory_vault, "work-pc", NOW + timedelta(hours=1), ttl)  # expired
    current = lease.read(memory_vault)
    assert current is not None and current.holder == "work-pc"
    lease.release(memory_vault, "work-pc", NOW + timedelta(hours=1))
    assert lease.try_acquire(memory_vault, "personal-pc", NOW + timedelta(hours=1), ttl)


def test_runs_and_snapshots(memory_vault: MemoryVault) -> None:
    runs.append(memory_vault, NOW, "personal-pc", "lint", "0 violations")
    runs.append(memory_vault, NOW, "work-pc", "digest", "ok")
    text = memory_vault.read_text(runs.runs_path(NOW))
    assert text.count("\n- 2026-09-27T10:00:00+00:00") == 2
    snapshots.save(memory_vault, "n-1", "body")
    assert snapshots.load(memory_vault, "n-1") == "body"
    assert snapshots.load(memory_vault, "n-2") is None
