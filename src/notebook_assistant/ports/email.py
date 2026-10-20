"""The email reader port: an email file in one of the formats Handbook §12 captures, read as an
:class:`~notebook_assistant.domain.capture.Email`. Adapter: ``adapters/email_files.py``."""

from __future__ import annotations

from typing import Protocol

from notebook_assistant.domain.capture import Email


class EmailError(Exception):
    """The file isn't a readable email."""


class EmailReader(Protocol):
    def __call__(self, name: str, data: bytes) -> Email: ...
