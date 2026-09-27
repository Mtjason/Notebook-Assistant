"""The Vault Handbook's structural rules as data (Handbook §2, §4, §5).

This module is the machine-readable twin of the handbook sections it cites. The handbook is the
source of truth: when it changes, this file changes in the same pull request, and the golden
test against the real vault shows the effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HANDBOOK_VERSION = "2.8"

COMMON_REQUIRED: tuple[str, ...] = ("type", "scope", "status", "created", "updated")

SCOPES = frozenset({"work", "personal"})
ORIGINS = frozenset({"own", "ai-chat", "web", "colleague", "course"})
DIGEST_STATES = frozenset({"pending", "approved", "review", "graduated"})

CONTAINER_ROOTS: tuple[str, ...] = ("15-Incubator", "20-Projects", "25-Areas")
HUB_TYPE_FOR_ROOT = {"15-Incubator": "idea", "20-Projects": "project", "25-Areas": "area"}
ARCHIVE_ROOT = "95-Archive"

#: Folders where the invariants don't apply at all (Handbook §0.1, §10, §11).
UNCHECKED_ROOTS = frozenset({"00-Inbox", "90-Views", "98-Templates", "Attachments", ".obsidian"})
#: The assistant's own state files (changesets, sessions, snapshots): machine-managed notes,
#: exempt from the invariants (Handbook §0.1, I-6 exception).
STATE_PREFIX = "99-System/Assistant/"
#: Folders exempt from I-5 (at least one outbound link).
LINK_EXEMPT_ROOTS = frozenset({"00-Inbox", "01-Daily", "90-Views", "98-Templates", "99-System"})

KNOWLEDGE_TOPICS: tuple[str, ...] = (
    "ML", "Data Science", "Statistics", "Software", "Systems", "Semiconductor", "CS", "English",
)  # fmt: skip

MAX_FOLDER_DEPTH = 3  # I-6: at most 3 folder levels below the vault root


@dataclass(frozen=True)
class TypeRule:
    """What the handbook requires of one note type."""

    name: str
    folders: tuple[str, ...]  # vault-relative folders (prefix match); () = containers only
    required: tuple[str, ...] = ()
    enums: dict[str, frozenset[str]] = field(default_factory=dict)
    statuses: frozenset[str] = frozenset({"active", "archived"})
    title_pattern: re.Pattern[str] | None = None
    in_containers: bool = False  # may live inside 15-Incubator/20-Projects/25-Areas containers


def _p(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


_DATE_TITLE = _p(r"^\d{4}-\d{2}-\d{2}( .+)?$")
_ACTIVE_RETIRED = frozenset({"active", "retired", "archived"})

TYPES: dict[str, TypeRule] = {
    r.name: r
    for r in (
        TypeRule(
            "task",
            ("10-Tasks",),
            required=("kind", "priority"),
            enums={
                "kind": frozenset({"action", "question", "learn"}),
                "priority": frozenset({"p1", "p2", "p3"}),
            },
            statuses=frozenset(
                {"someday", "todo", "doing", "waiting", "done", "dropped", "archived"}
            ),
        ),
        TypeRule(
            "idea",
            (),
            required=("question",),
            statuses=frozenset(
                {"exploring", "shaping", "promoted", "parked", "dropped", "archived"}
            ),
            in_containers=True,
        ),
        TypeRule(
            "project",
            (),
            required=("started",),
            statuses=frozenset({"active", "paused", "done", "dropped", "archived"}),
            in_containers=True,
        ),
        TypeRule(
            "area",
            (),
            statuses=frozenset({"active", "dormant", "archived"}),
            in_containers=True,
        ),
        TypeRule(
            "project-doc",
            (),
            enums={"kind": frozenset({"design", "plan", "spec", "essay", "notes"})},
            statuses=frozenset({"draft", "final", "archived"}),
            in_containers=True,
        ),
        TypeRule(
            "log",
            ("01-Daily",),
            required=("date",),
            title_pattern=_DATE_TITLE,
            in_containers=True,
        ),
        TypeRule(
            "sop",
            ("30-SOPs",),
            required=("domain", "trigger", "last_verified"),
            enums={
                "domain": frozenset(
                    {
                        "dev-env",
                        "IT",
                        "finance",
                        "facilities",
                        "admin",
                        "fab-tools",
                        "study",
                        "personal-admin",
                    }
                )
            },
            statuses=frozenset({"draft", "active", "stale", "deprecated", "archived"}),
            title_pattern=_p(r"^SOP - .+"),
        ),
        TypeRule(
            "credential",
            ("40-Reference/Credentials",),
            required=("service",),
            statuses=_ACTIVE_RETIRED,
            title_pattern=_p(r"^Cred - .+"),
        ),
        TypeRule(
            "fact",
            ("40-Reference/Facts",),
            required=("key", "value"),
            statuses=_ACTIVE_RETIRED,
            title_pattern=_p(r"^Fact - .+"),
        ),
        TypeRule(
            "resource",
            ("40-Reference/Resources",),
            required=("kind",),
            enums={
                "kind": frozenset(
                    {"doc", "tool", "product", "dataset", "repo", "course", "paper", "link"}
                )
            },
            statuses=_ACTIVE_RETIRED,
        ),
        TypeRule("person", ("40-Reference/People",), statuses=_ACTIVE_RETIRED),
        TypeRule("meeting", ("50-Meetings",), required=("date",), title_pattern=_DATE_TITLE),
        TypeRule(
            "writing",
            ("80-Writing",),
            required=("kind",),
            enums={"kind": frozenset({"essay", "story", "speech", "post", "draft"})},
            statuses=frozenset({"draft", "final", "archived"}),
        ),
        TypeRule(
            "knowledge",
            tuple(f"60-Knowledge/{t}" for t in KNOWLEDGE_TOPICS),
            required=("kind", "topic"),
            enums={
                "kind": frozenset(
                    {"concept", "snippet", "troubleshooting", "collection", "course-note"}
                )
            },
            statuses=frozenset({"seed", "evergreen", "deprecated", "archived"}),
        ),
        TypeRule(
            "source",
            ("70-Sources",),
            required=("kind", "captured"),
            enums={
                "kind": frozenset(
                    {
                        "text",
                        "email",
                        "chat",
                        "image",
                        "meeting-audio",
                        "transcript",
                        "ai-chat",
                        "file",
                    }
                )
            },
            title_pattern=_DATE_TITLE,
        ),
        TypeRule(
            "moc",
            tuple(f"60-Knowledge/{t}" for t in KNOWLEDGE_TOPICS),
            required=("topic",),
            title_pattern=_p(r"^MOC - .+"),
        ),
        TypeRule(
            "daily",
            ("01-Daily",),
            required=("date",),
            title_pattern=_p(r"^\d{4}-\d{2}-\d{2}$"),
        ),
        TypeRule("system", ("99-System",)),
    )
}

#: Types a container may hold besides its hub (Handbook §2.1).
CONTAINER_MEMBER_TYPES = frozenset({"project-doc", "log"})
