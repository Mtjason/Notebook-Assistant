"""Property-based test: random renames never break a link.

Hypothesis generates random small vaults (random titles, random links between notes in all link
forms) and a random valid new title; after planning and applying the rename, every link that
resolved before must resolve to the same note, and undo must restore the vault exactly.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.apply import apply_changeset, undo_changeset
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.rename import plan_move
from notebook_assistant.domain.names import name_key, validate_path
from notebook_assistant.handbook import load_rules
from tests.conftest import NOW

NAMES = load_rules().names

FOLDERS = ["60-Knowledge/ML", "60-Knowledge/Data Science", "10-Tasks"]
title_chars = st.characters(
    whitelist_categories=("Lu", "Ll", "Nd", "Lo"),
    whitelist_characters=" -_.()",
    max_codepoint=0x9FFF,
)
titles = st.text(title_chars, min_size=1, max_size=20).map(lambda s: s.strip(" .")).filter(bool)
link_forms = st.sampled_from(
    ["[[{t}]]", "[[{t}|alias]]", "[[{t}#Heading]]", "![[{t}]]", "[x]({p})", "| [[{t}\\|a]] |"]
)


@st.composite
def vaults(draw: st.DrawFn) -> tuple[dict[str, str], str, str]:
    names = draw(
        st.lists(
            titles.filter(lambda t: not validate_path(PurePosixPath(f"{t}.md"), NAMES)),
            min_size=2,
            max_size=6,
            unique_by=name_key,
        )
    )
    paths = [f"{draw(st.sampled_from(FOLDERS))}/{n}.md" for n in names]
    files: dict[str, str] = {}
    for path in paths:
        body = []
        for _ in range(draw(st.integers(0, 4))):
            target = draw(st.sampled_from(paths))
            t = PurePosixPath(target).stem
            p = target.replace(" ", "%20")
            body.append(draw(link_forms).format(t=t, p=p))
        files[path] = "---\ntype: knowledge\naliases: [x]\n---\n" + "\n".join(body) + "\n"
    src = draw(st.sampled_from(paths))
    new_title = draw(titles)
    return files, src, new_title


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(vaults())
def test_random_renames_never_break_links(case: tuple[dict[str, str], str, str]) -> None:
    files, src, new_title = case
    store = MemoryVault(files)
    src_path = PurePosixPath(src)
    dest = src_path.with_name(f"{new_title}.md")
    taken = {name_key(PurePosixPath(p).stem) for p in files if p != src}
    if name_key(new_title) in taken or name_key(dest.as_posix()) == name_key(src):
        return
    if validate_path(dest, NAMES):  # invalid names are refused by the planner (tested elsewhere)
        return
    before = store.snapshot()
    index = VaultIndex.build(store)
    broken_before = len(index.broken)
    cs = plan_move(index, src_path, dest, reason="p", created_by="t", now=NOW)
    result = apply_changeset(store, cs, now=NOW)
    assert result.ok, result.error
    after = VaultIndex.build(store)
    assert len(after.broken) == broken_before
    assert undo_changeset(store, cs, now=NOW).ok
    assert store.snapshot() == before
