"""Saving a capture to the Inbox: one click, one applied changeset."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from notebook_assistant.adapters.memory_vault import MemoryVault
from notebook_assistant.app.capture import CaptureError, CaptureOutcome, capture_to_inbox
from notebook_assistant.app.clicks import ApplyRefusedError, Button
from notebook_assistant.domain.capture import CapturedFile, Email
from notebook_assistant.domain.note import Note
from notebook_assistant.handbook import load_rules
from notebook_assistant.ports.email import EmailError

P = PurePosixPath
RULES = load_rules()
CLICK = Button("test-pc", datetime(2026, 10, 20, 14, 2, tzinfo=UTC))
PNG = CapturedFile("Screenshot 0931.PNG", b"\x89PNG")
EMAIL = Email(
    subject="Concur policy",
    sender="Amy",
    recipients=("jason@example.com",),
    date="2026-09-26",
    body="Please file by Friday.",
    attachments=(CapturedFile("form.pdf", b"%PDF"),),
)


def read_email(name: str, data: bytes) -> Email:
    if data == b"broken":
        raise EmailError("no headers")
    return EMAIL


def save(
    store: MemoryVault, text: str = "", files: list[CapturedFile] | None = None, origin: str = "own"
) -> CaptureOutcome:
    return capture_to_inbox(
        store,
        text=text,
        files=files or [],
        origin=origin,
        rules=RULES,
        click=CLICK,
        read_email=read_email,
    )


def note(store: MemoryVault, path: str) -> Note:
    return Note.parse(P(path), store.read_text(P(path)))


def test_typed_text_becomes_an_inbox_note(memory_vault: MemoryVault) -> None:
    outcome = save(memory_vault, "  要學 Kedro hooks  ", origin="ai-chat")
    assert outcome.paths == ["00-Inbox/2026-10-20 1402.md"]
    saved = note(memory_vault, outcome.paths[0])
    assert saved.props == {"kind": "text", "origin": "ai-chat", "captured": "2026-10-20"}
    assert saved.body == "要學 Kedro hooks\n"
    again = save(memory_vault, "second")  # same minute: numbered
    assert again.paths == ["00-Inbox/2026-10-20 1402 2.md"]


def test_files_are_attached_under_the_note_s_name(memory_vault: MemoryVault) -> None:
    text_file = CapturedFile("notes.txt", b"from a file")
    outcome = save(memory_vault, "a screenshot", [PNG, text_file, CapturedFile("a.pdf", b"%PDF")])
    saved = note(memory_vault, outcome.paths[0])
    assert saved.props["kind"] == "file"
    assert saved.body == (
        "a screenshot\n\nfrom a file\n\n"
        "![[2026-10-20 1402 - 1.png]]\n![[2026-10-20 1402 - 2.pdf]]\n"
    )
    assert memory_vault.read_bytes(P("Attachments/2026-10-20 1402 - 1.png")) == b"\x89PNG"
    only_images = save(memory_vault, "", [PNG])
    assert note(memory_vault, only_images.paths[0]).props["kind"] == "image"


def test_each_email_becomes_its_own_note(memory_vault: MemoryVault) -> None:
    outcome = save(memory_vault, "", [CapturedFile("policy.eml", b"raw")])
    [path] = outcome.paths
    assert path == "00-Inbox/2026-09-26 email Concur policy.md"
    saved = note(memory_vault, path)
    assert saved.props["kind"] == "email" and saved.props["sender"] == "Amy"
    assert "![[2026-09-26 email Concur policy - 1.pdf]]" in saved.body
    assert "![[2026-09-26 email Concur policy - 2.eml]]" in saved.body
    assert (
        memory_vault.read_bytes(P("Attachments/2026-09-26 email Concur policy - 2.eml")) == b"raw"
    )
    with pytest.raises(CaptureError, match="already exists"):  # the same email twice
        save(memory_vault, "", [CapturedFile("policy.eml", b"raw")])


def test_what_cant_be_captured(memory_vault: MemoryVault) -> None:
    with pytest.raises(CaptureError, match="nothing to capture"):
        save(memory_vault, "  ")
    with pytest.raises(CaptureError, match="unknown origin"):
        save(memory_vault, "x", origin="dream")
    with pytest.raises(CaptureError, match=r"bad\.msg: no headers"):
        save(memory_vault, "", [CapturedFile("bad.msg", b"broken")])


def test_a_name_already_used_by_a_file_is_refused(memory_vault: MemoryVault) -> None:
    memory_vault.write_text(P("Attachments/2026-10-20 1402 - 1.png"), "")
    with pytest.raises(CaptureError, match="already exists"):
        save(memory_vault, "x", [PNG])


def test_a_refused_apply_is_a_capture_error(
    memory_vault: MemoryVault, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object) -> str:
        raise ApplyRefusedError("00-Inbox changed")

    monkeypatch.setattr("notebook_assistant.app.capture.apply_click", refuse)
    with pytest.raises(CaptureError, match="00-Inbox changed"):
        save(memory_vault, "x")
