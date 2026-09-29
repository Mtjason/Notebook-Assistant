from functools import partial

from notebook_assistant.config import load_default_config
from notebook_assistant.domain import preserve

check = partial(preserve.check, similarity=load_default_config().checks.preservation_similarity)

ORIGINAL = """要學 Kedro hooks
為什麼 polars lazyframe 不能 .dt？
The fix took 3 tries on 2026-09-08.
See https://docs.kedro.org/en/stable/hooks.html for details.

```python
df.with_columns(pl.col("t").dt.total_seconds())
```

![[Terminal setup - 1.png]]
- [ ] Ask about [[Kedro hooks]]
"""


def test_reformatted_content_passes() -> None:
    restructured = """# Kedro hooks

## Context
- 要學 Kedro hooks
- 為什麼 polars lazyframe 不能 .dt？

The **fix** took 3 tries on 2026-09-08. See https://docs.kedro.org/en/stable/hooks.html for details.

```python
df.with_columns(pl.col("t").dt.total_seconds())
```

![[Terminal setup - 1.png]]

## To do
- [ ] Ask about [[Kedro hooks]]
"""
    report = check(ORIGINAL, [restructured])
    assert report.ok, report


def test_split_across_notes_passes() -> None:
    part1 = "要學 Kedro hooks\n- [ ] Ask about [[Kedro hooks]]\n"
    part2 = ORIGINAL.replace("要學 Kedro hooks\n", "").replace(
        "- [ ] Ask about [[Kedro hooks]]\n", ""
    )
    assert check(ORIGINAL, [part1, part2]).ok


def test_dropped_sentence_fails() -> None:
    report = check(ORIGINAL, [ORIGINAL.replace("為什麼 polars lazyframe 不能 .dt？\n", "")])
    assert not report.ok and report.missing_text


def test_changed_code_fails() -> None:
    report = check(ORIGINAL, [ORIGINAL.replace("total_seconds", "seconds")])
    assert report.missing_exact


def test_missing_url_number_embed_link() -> None:
    assert check(
        ORIGINAL, [ORIGINAL.replace("https://docs.kedro.org/en/stable/hooks.html", "")]
    ).missing_exact
    assert check(ORIGINAL, [ORIGINAL.replace("3 tries", "three tries")]).missing_numbers
    assert check(ORIGINAL, [ORIGINAL.replace("![[Terminal setup - 1.png]]", "")]).missing_exact
    assert check(ORIGINAL, [ORIGINAL.replace("[[Kedro hooks]]", "Kedro hooks")]).missing_exact


def test_renumbered_list_is_fine() -> None:
    assert check("1. first step\n2. second step\n", ["1. first step\n1. second step\n"]).ok


def test_rewording_beyond_threshold_fails() -> None:
    report = check("The service restarts every night at midnight.\n", ["It reboots nightly.\n"])
    assert report.missing_text
    assert "missing or changed" in report.summary()


def test_shared_units_are_the_sentences_both_texts_contain() -> None:
    similarity = load_default_config().checks.preservation_similarity
    principle = "Curl follows redirects. It fails on HTTP errors.\n"
    note = "## Flags\n\n- It fails on HTTP errors!\n- An unrelated line here.\n"
    shared = preserve.shared_units(principle, note, similarity=similarity)
    assert shared == ["it fails on http errors."]
    assert preserve.shared_units(principle, "Nothing alike.", similarity=similarity) == []
