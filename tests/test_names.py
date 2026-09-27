from pathlib import PurePosixPath

import pytest

from notebook_assistant.domain.names import name_key, sanitize_title, validate_name, validate_path
from notebook_assistant.handbook import load_rules

N = load_rules().names


@pytest.mark.parametrize(
    "name",
    ["Polars with_columns", "Why does import fail？", "條件句 As if", "SOP - Install uv", "a.b.c"],
)
def test_valid_names(name: str) -> None:
    assert validate_name(name, N, is_note_title=True) == []


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
    assert any(fragment in p for p in validate_name(name, N))


def test_title_only_rules() -> None:
    assert validate_name("C# notes", N) == []
    assert any("break links" in p for p in validate_name("C# notes", N, is_note_title=True))


def test_nfd_is_rejected_and_keys_match() -> None:
    nfd = "Café".replace("é", "é")
    assert any("NFC" in p for p in validate_name(nfd, N))
    assert name_key(nfd) == name_key("CAFÉ")


def test_validate_path_checks_every_part_and_length() -> None:
    assert validate_path(PurePosixPath("60-Knowledge/ML/Confusion matrix.md"), N) == []
    assert validate_path(PurePosixPath("../escape.md"), N)
    assert any("folder?" in p for p in validate_path(PurePosixPath("folder?/note.md"), N))
    long = PurePosixPath("/".join(["abcdefghij" * 5] * 5) + "/n.md")
    assert any("path longer" in p for p in validate_path(long, N))


def test_sanitize_title() -> None:
    assert sanitize_title("Why does it fail?", N) == "Why does it fail？"
    assert sanitize_title("Kedro: hooks [draft]", N) == "Kedro - hooks draft"
    assert sanitize_title("   ", N) == "Untitled"
    assert validate_name(sanitize_title('a<b>c|d"e*f#g^h', N), N, is_note_title=True) == []


def test_name_rules_come_from_the_handbook() -> None:
    assert N.max_name == 100 and N.max_path == 200
    assert {"CON", "NUL", "COM1", "COM9", "LPT9"} <= N.reserved and "COM10" not in N.reserved
    assert set('<>:"/\\|?*') == N.forbidden
    assert set("#^[]") == N.forbidden_in_titles
