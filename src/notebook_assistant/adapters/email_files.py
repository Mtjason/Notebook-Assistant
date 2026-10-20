"""Reads ``.eml`` (the standard library) and Outlook ``.msg`` (``extract-msg``) files as an
:class:`~notebook_assistant.domain.capture.Email`: headers, the body as Markdown (the plain-text
part, else the HTML part reduced to text), and the attached files."""

from __future__ import annotations

import email
import email.policy
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath

import extract_msg
from extract_msg.attachments import Attachment

from notebook_assistant.domain.capture import CapturedFile, Email
from notebook_assistant.ports.email import EmailError

_BREAKS = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}  # start a line
_BLOCKS = {"p", "div", "tr", "h1", "h2", "h3", "h4", "table", "ul", "ol"}  # end one


class _Text(HTMLParser):
    """HTML reduced to text: blocks become lines, list items bullets, links ``text (url)``."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._href: str | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script", "head"}:
            self._skip += 1
        if tag in _BREAKS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script", "head"}:
            self._skip = max(0, self._skip - 1)
        if tag in _BLOCKS:
            self.parts.append("\n")
        if tag == "a" and self._href:
            self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _date(value: datetime | None) -> str:
    if value is None:
        raise EmailError("the email has no date")
    return value.date().isoformat()


def read_eml(data: bytes) -> Email:
    message = email.message_from_bytes(data, policy=email.policy.default)
    if not isinstance(message, EmailMessage) or not message.keys():
        raise EmailError("not an email (no headers)")
    plain = message.get_body(("plain",))
    html = message.get_body(("html",))
    if plain is not None:
        body = str(plain.get_content())
    elif html is not None:
        body = html_to_text(str(html.get_content()))
    else:
        body = ""
    files: list[CapturedFile] = []
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            files.append(CapturedFile(part.get_filename() or "attachment", payload))
    raw_date = message.get("date")
    return Email(
        subject=str(message.get("subject", "")),
        sender=str(message.get("from", "")),
        recipients=tuple(
            a.strip() for h in ("to", "cc") for a in str(message.get(h, "")).split(",") if a.strip()
        ),
        date=_date(parsedate_to_datetime(str(raw_date)) if raw_date else None),
        body=body.strip(),
        attachments=tuple(files),
    )


def read_msg(data: bytes) -> Email:
    try:
        msg = extract_msg.openMsg(data)
    except Exception as exc:  # the library raises many kinds; all mean "not readable"
        raise EmailError(f"not an Outlook message: {exc}") from exc
    try:
        if not isinstance(msg, extract_msg.Message):
            raise EmailError("the .msg file isn't an email")
        body = msg.body or (
            html_to_text(msg.htmlBody.decode("utf-8", "replace")) if msg.htmlBody else ""
        )
        files = tuple(
            CapturedFile(a.longFilename or a.shortFilename or "attachment", a.data)
            for a in msg.attachments
            if isinstance(a, Attachment) and isinstance(a.data, bytes)
        )
        recipients = (r.strip() for h in (msg.to, msg.cc) for r in (h or "").split(";"))
        date = msg.date
        return Email(
            subject=msg.subject or "",
            sender=msg.sender or "",
            recipients=tuple(r for r in recipients if r),
            date=_date(date if isinstance(date, datetime) else None),
            body=body.strip(),
            attachments=files,
        )
    finally:
        msg.close()


def read_email(name: str, data: bytes) -> Email:
    """An email file by its suffix; :class:`EmailError` for anything else."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".eml":
        return read_eml(data)
    if suffix == ".msg":
        return read_msg(data)
    raise EmailError(f"{name} isn't an email file")
