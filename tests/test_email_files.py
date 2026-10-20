"""Email files (.eml, .msg) read as an Email (Handbook §12)."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import extract_msg
import pytest
from extract_msg.attachments import Attachment

from notebook_assistant.adapters.email_files import html_to_text, read_email
from notebook_assistant.ports.email import EmailError


def eml(
    *, html: bool = False, plain: bool = True, attach: bool = False, date: bool = True
) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Concur policy"
    msg["From"] = "Amy <amy@example.com>"
    msg["To"] = "jason@example.com, lee@example.com"
    msg["Cc"] = "boss@example.com"
    if date:
        msg["Date"] = "Sat, 26 Sep 2026 09:30:00 +0800"
    if plain:
        msg.set_content("Please file by Friday.\n")
    if html:
        if plain:
            msg.add_alternative("<p>Please <b>file</b></p>", subtype="html")
        else:
            msg.set_content("<p>Please <a href='https://x.example'>file</a></p>", subtype="html")
    if attach:
        msg.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="shot.png")
    return msg.as_bytes()


def test_an_eml_is_read_with_its_headers_body_and_attachments() -> None:
    email = read_email("Policy.EML", eml(html=True, attach=True))
    assert email.subject == "Concur policy" and email.sender == "Amy <amy@example.com>"
    assert email.recipients == ("jason@example.com", "lee@example.com", "boss@example.com")
    assert email.date == "2026-09-26" and email.body == "Please file by Friday."
    assert [(f.name, f.data) for f in email.attachments] == [("shot.png", b"\x89PNG")]


def test_an_html_only_eml_is_reduced_to_text() -> None:
    assert (
        read_email("a.eml", eml(plain=False, html=True)).body == "Please file (https://x.example)"
    )


def test_unreadable_emails_fail_loudly() -> None:
    with pytest.raises(EmailError, match="no headers"):
        read_email("a.eml", b"")
    with pytest.raises(EmailError, match="no date"):
        read_email("a.eml", eml(date=False))
    with pytest.raises(EmailError, match="isn't an email file"):
        read_email("a.pdf", b"%PDF")
    with pytest.raises(EmailError, match="not an Outlook message"):
        read_email("a.msg", b"not ole")


def test_html_becomes_lines_bullets_and_links() -> None:
    html = (
        "<head><style>p{}</style></head><h1>Title</h1><ul><li>one</li><li>two</li></ul>"
        "<p>see <a href='u'>this</a>&nbsp;now</p><a>bare</a><script>x()</script>"
    )
    assert html_to_text(html) == "Title\n\n- one\n- two\n\nsee this (u) now\nbare"


class FakeAttachment(Attachment):
    def __init__(self, name: str, data: Any) -> None:  # no OLE stream behind it
        self._name, self._data = name, data

    longFilename = property(lambda self: self._name)
    shortFilename = property(lambda self: None)
    data = property(lambda self: self._data)


class FakeMsg(extract_msg.Message):
    def __init__(self, **fields: Any) -> None:  # no OLE file behind it
        self._fields = fields
        self.closed_ = False

    def close(self) -> None:
        self.closed_ = True

    subject = property(lambda self: self._fields["subject"])
    sender = property(lambda self: "Amy")
    to = property(lambda self: "jason@example.com; lee@example.com")
    cc = property(lambda self: None)
    date = property(lambda self: self._fields["date"])
    body = property(lambda self: self._fields["body"])
    htmlBody = property(lambda self: b"<p>from html</p>")
    attachments = property(lambda self: self._fields["attachments"])


def test_a_msg_is_read_through_extract_msg(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[FakeMsg] = []

    def open_msg(data: bytes) -> FakeMsg:
        msg = FakeMsg(
            subject="Badge",
            date=datetime(2026, 9, 26, tzinfo=UTC),
            body="",
            attachments=[FakeAttachment("a.pdf", b"%PDF"), FakeAttachment("x", None)],
        )
        opened.append(msg)
        return msg

    monkeypatch.setattr("extract_msg.openMsg", open_msg)
    email = read_email("a.msg", b"ole")
    assert (email.subject, email.sender, email.date) == ("Badge", "Amy", "2026-09-26")
    assert email.recipients == ("jason@example.com", "lee@example.com")
    assert email.body == "from html" and [f.name for f in email.attachments] == ["a.pdf"]
    assert opened[0].closed_


def test_a_msg_that_isnt_an_email_or_has_no_date_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("extract_msg.openMsg", lambda data: object())
    with pytest.raises(AttributeError):  # anything not an email has no close(); not swallowed
        read_email("a.msg", b"ole")
    no_date = FakeMsg(subject="s", date=None, body="b", attachments=[])
    monkeypatch.setattr("extract_msg.openMsg", lambda data: no_date)
    with pytest.raises(EmailError, match="no date"):
        read_email("a.msg", b"ole")
    assert no_date.closed_
