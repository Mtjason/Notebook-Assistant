"""Identifiers and content hashes."""

from __future__ import annotations

import hashlib
import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now_ms: int | None = None, randomness: bytes | None = None) -> str:
    """A 26-character ULID: sortable by creation time, unique without coordination.

    A ULID is 48 bits of millisecond timestamp plus 80 random bits, in Crockford base32.
    Two PCs can create IDs at the same moment without colliding.
    """
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    rand = os.urandom(10) if randomness is None else randomness
    value = (ms << 80) | int.from_bytes(rand, "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_note_id() -> str:
    """Stable note identity, stored as the ``id`` property (Handbook §4.1, §5.1)."""
    return "n-" + new_ulid().lower()


def new_changeset_id() -> str:
    return "cs-" + new_ulid()


def content_hash(data: bytes | str) -> str:
    """Fingerprint of exact file content (the "base hash" of a changeset target).

    Any byte difference, including line endings, changes it.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:16]
