"""The rules come from the handbook, and exist only there.

- The handbook parses, and the parsed rules are complete and consistent.
- A handbook edit the parser can't read fails loudly.
- Guard: no second copy of the handbook, and no hand-written rule tables, anywhere in the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from notebook_assistant.domain.rules import HandbookFormatError, parse_handbook
from notebook_assistant.handbook import handbook_path, handbook_text, load_rules

REPO = Path(__file__).resolve().parents[1]
HANDBOOK = REPO / "docs" / "handbook.md"
TEXT = HANDBOOK.read_text(encoding="utf-8")


def test_loader_uses_the_repo_handbook() -> None:
    assert handbook_path().resolve() == HANDBOOK.resolve()


def test_parsed_rules_are_complete() -> None:
    rules = load_rules()
    assert rules.version == re.search(r'^version: "([^"]+)"', TEXT, re.M).group(1)  # type: ignore[union-attr]
    assert {"type", "scope", "status", "created", "updated"} <= set(rules.common_required)
    assert rules.common_enums["scope"] == {"work", "personal"}
    assert "Data Science" in rules.topics and len(rules.topics) == len(set(rules.topics))
    assert rules.container_roots == {"15-Incubator", "20-Projects", "25-Areas"}
    assert rules.state_prefix == "99-System/Assistant/"
    assert rules.archive_root == "95-Archive" and rules.max_folder_depth == 3
    assert rules.inbox == "00-Inbox"
    assert rules.direct_capture_digest == ("knowledge", "review")
    assert rules.assistant_managed == {"id", "assistant_hash"}
    assert rules.default_origin == "own" and "own" in rules.common_enums["origin"]
    assert rules.digest_flow == ("pending", "approved", "review", "graduated")
    assert set(rules.digest_flow) == rules.common_enums["digest"]  # §19.1 agrees with §4.1
    d = rules.digestion
    assert d.reasons == {"raw-capture", "stub", "screenshot-only", "ai-unverified"}
    assert d.graduate == {"status": "evergreen", "origin": "own"}
    assert d.as_is == {
        "status": "evergreen",
        "origin": "own",
        "digest": "graduated",
        "graduated_via": "direct",
    }
    assert (d.task_done, d.produced) == ("done", "produced")
    assert d.original_box == "> [!quote]- Original capture"
    assert d.unverified_box == "> [!question] Unverified"
    assert d.as_is["digest"] == rules.digest_flow[-1]  # §19.5 agrees with §19.1
    c = rules.capture
    assert (c.long_text_lines, c.ai_origin, c.email_formats) == (30, "ai-chat", (".eml", ".msg"))
    assert c.attachments == "Attachments" and c.ai_origin in rules.common_enums["origin"]
    r = rules.review
    assert r.archive["task"].statuses == {"done", "dropped"} and r.archive["task"].days == 90
    assert r.archive["project"].days == 30 and "promoted" in r.archive["idea"].statuses
    assert (r.settle_minutes, r.waiting_nudge_days, r.session_days) == (30, 14, 90)
    assert r.learn_untouched_days == 90 and r.idea_untouched_days == 90
    assert r.lint_report == "99-System/Lint YYYY-MM.md"
    for rule in rules.types.values():
        placed = rule.folders or rule.hub_of or rule.container_member
        assert placed, f"{rule.name} has no folder"
        assert rule.statuses and "archived" in rule.statuses, rule.name
    # spot checks against the handbook's own examples (§5)
    assert rules.types["sop"].title_pattern.match("SOP - 採購辦公設備")  # type: ignore[union-attr]
    assert rules.types["daily"].title_pattern.match("2026-09-26")  # type: ignore[union-attr]
    assert rules.types["project-doc"].one_of == (("project", "area", "idea"),)
    assert "fab-tools" in rules.types["sop"].enums["domain"]


def test_topic_mocs_match_folders() -> None:
    """§2.3 topics and the knowledge folders derived from them are the same list."""
    rules = load_rules()
    assert rules.types["knowledge"].folders == tuple(f"60-Knowledge/{t}" for t in rules.topics)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("**Scope:**", "Scope:", "Scope"),
        ("at most **3 levels**", "at most three levels", "I-6"),
        ("# max 3, from the registry", "# from the registry", "tags"),
        ("`sop` → `30-SOPs/`", "`sopx` → `30-SOPs/`", "§3 gives no folder"),
        ("## 4.3", "## 4.3x", "§4.3"),
        ("| → `00-Inbox/` (§0.3) |", "| → Inbox (§0.3) |", "§3 names no Inbox"),
        ("get `digest: review`", "get the review state", "§19.6"),
        ("`pending → approved → review → graduated`", "pending, then approved", "§19.1"),
        ("the task is set `done` with `produced`", "the task is closed", "§19"),
        ("`> [!quote]- Original capture`", "an original box", "§19.3"),
        ("over about 30 lines", "that is long", "§12"),
        ("All embedded files", "Every embed", "§12"),
        ("30 minutes without edits", "half an hour without edits", "§16.2"),
        ("for 90+ days |", "for ninety days |", "§13"),
    ],
)
def test_unreadable_handbook_edits_fail_loudly(old: str, new: str, message: str) -> None:
    assert old in TEXT
    with pytest.raises(HandbookFormatError, match=re.escape(message.split()[0])):
        parse_handbook(TEXT.replace(old, new, 1))


def test_no_copy_of_the_handbook_in_the_repo() -> None:
    """The handbook's text exists exactly once (docs/handbook.md)."""
    marker = "This is the **golden rule** of the vault"
    hits = [
        p.relative_to(REPO).as_posix()
        for p in REPO.rglob("*")
        if p.is_file()
        and p.suffix in {".md", ".html", ".txt", ".yaml", ".yml"}
        and not any(part.startswith(".") or part in {"build", "dist"} for part in p.parts)
        and marker in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == ["docs/handbook.md"]


def test_no_hand_written_rule_tables_in_code() -> None:
    """Rule values are parsed from the handbook, never listed in source code."""
    src = REPO / "src" / "notebook_assistant"
    fingerprints = [
        r'"fab-tools"',  # SOP domains (§4.2)
        r'"course-note"',  # knowledge kinds (§4.2)
        r'"someday"',  # task statuses (§4.3)
        r'"40-Reference/',  # type folders (§3)
        r'"Data Science"',  # topics (§2.3)
    ]
    offenders = [
        f"{p.relative_to(REPO).as_posix()}: {fp}"
        for p in src.rglob("*.py")
        for fp in fingerprints
        if re.search(fp, p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_handbook_text_is_the_file_the_rules_come_from() -> None:
    assert handbook_text() == TEXT


def test_a_handbook_naming_no_assistant_managed_property_fails_loudly() -> None:
    text = TEXT.replace("by the assistant", "by code")
    with pytest.raises(HandbookFormatError, match=re.escape("§4.1 names no property managed")):
        parse_handbook(text)
