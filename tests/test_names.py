from pathlib import PurePosixPath

import pytest

from notebook_assistant.domain.names import name_key, sanitize_title, validate_name, validate_path


@pytest.mark.parametrize(
    "name",
    ["Polars with_columns", "Why does import fail？", "條件句 As if", "SOP - Install uv", "a.b.c"],
)
def test_valid_names(name: str) -> None:
    assert validate_name(name, is_note_title=True) == []


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("What?", "not allowed"),
        ("a:b", "not allowed"),
        ("trailing.", "ends with"),
        ("trailing ", "ends with"),
        ("CON", "reserved"),
        ("nul.txt", "reserved"),
        ("x" * 101, "longer"),
        ("", "empty"),
    ],
)
def test_invalid_names(name: str, fragment: str) -> None:
    assert any(fragment in p for p in validate_name(name))


def test_title_only_rules() -> None:
    assert validate_name("C# notes") == []
    assert any("break links" in p for p in validate_name("C# notes", is_note_title=True))


def test_nfd_is_rejected_and_keys_match() -> None:
    nfd = "Café".replace("é", "é")
    assert any("NFC" in p for p in validate_name(nfd))
    assert name_key(nfd) == name_key("CAFÉ")


def test_validate_path_checks_every_part_and_length() -> None:
    assert validate_path(PurePosixPath("60-Knowledge/ML/Confusion matrix.md")) == []
    assert validate_path(PurePosixPath("../escape.md"))
    assert any("folder?" in p for p in validate_path(PurePosixPath("folder?/note.md")))
    long = PurePosixPath("/".join(["abcdefghij" * 5] * 5) + "/n.md")
    assert any("path longer" in p for p in validate_path(long))


def test_sanitize_title() -> None:
    assert sanitize_title("Why does it fail?") == "Why does it fail？"
    assert sanitize_title("Kedro: hooks [draft]") == "Kedro - hooks draft"
    assert sanitize_title("   ") == "Untitled"
    assert validate_name(sanitize_title('a<b>c|d"e*f#g^h'), is_note_title=True) == []
