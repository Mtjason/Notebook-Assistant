"""The Lint button: every rule check, mechanical fixes in one pending changeset with the report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.lint import fixed, lint_changeset, lint_vault, report_note
from notebook_assistant.domain.note import Note

P = PurePosixPath
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
POLARS = P("60-Knowledge/Software/Polars with_columns.md")


def test_a_clean_vault_has_no_findings(memory_vault: MemoryVault) -> None:
    assert lint_vault(VaultIndex.build(memory_vault)) == []


def broken(store: MemoryVault) -> None:
    text = store.read_text(POLARS)
    text = text.replace("tags: [tool/polars]", "tags: [Tool/Polars, nope]").replace(
        "updated: ", "was_updated: "
    )
    store.write_text(POLARS, text + "\nSee [[Nowhere note]].\n")
    store.write_text(P("60-Knowledge/Software/Bad.md"), "---\ntype: [unclosed\n---\nx\n")


def test_findings_cover_rules_links_and_unreadable_notes(memory_vault: MemoryVault) -> None:
    broken(memory_vault)
    findings = lint_vault(VaultIndex.build(memory_vault))
    codes = {(f.path, f.code) for f in findings}
    assert (POLARS.as_posix(), "I-3") in codes  # updated is required
    assert (POLARS.as_posix(), "tag") in codes and (POLARS.as_posix(), "link") in codes
    assert ("60-Knowledge/Software/Bad.md", "parse") in codes


def test_the_batch_fixes_what_code_can_and_reports_the_rest(memory_vault: MemoryVault) -> None:
    broken(memory_vault)
    report, cs = lint_changeset(VaultIndex.build(memory_vault), now=NOW, created_by="sweep:lint")
    assert report.fixable == 1 and report.by_code["tag"] == 2
    assert [(op.kind, op.path.as_posix()) for op in cs.ops] == [
        ("write", POLARS.as_posix()),
        ("create", "99-System/Lint 2026-10.md"),
    ]
    assert apply_changeset(memory_vault, cs, now=NOW, machine="t").ok
    polars = Note.parse(POLARS, memory_vault.read_text(POLARS))
    assert polars.props["updated"] == "2026-10-21"
    assert polars.props["tags"] == ["tool/polars", "nope"]  # case fixed; unknown tag left for you
    lint = Note.parse(
        P("99-System/Lint 2026-10.md"), memory_vault.read_text(P("99-System/Lint 2026-10.md"))
    )
    assert lint.props["type"] == "system" and "[[Polars with_columns]]" in lint.body
    again, cs2 = lint_changeset(VaultIndex.build(memory_vault), now=NOW, created_by="t")
    assert again.fixable == 0 and cs2.ops[-1].kind == "write"  # this month's report is updated


def test_fixed_leaves_raw_and_compliant_notes_alone() -> None:
    raw = Note.parse(P("00-Inbox/r.md"), "just text\n")
    assert fixed(raw, None, "2026-10-21") is None
    ok = Note.parse(P("a.md"), "---\ntype: fact\nupdated: 2026-01-01\ntags: [a]\n---\n")
    assert fixed(ok, frozenset({"a"}), "2026-10-21") is None


def test_the_report_escapes_table_pipes(memory_vault: MemoryVault) -> None:
    broken(memory_vault)
    report, _ = lint_changeset(VaultIndex.build(memory_vault), now=NOW, created_by="t")
    text = report_note(P("99-System/Lint 2026-10.md"), report, today="2026-10-21")
    assert text.count("| [[") == len(report.findings)
