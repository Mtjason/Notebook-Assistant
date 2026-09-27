"""Check one note against the handbook's invariants (Handbook §0.1) and value rules (§4, §6).

Each :class:`Violation` names the rule it breaks, so reports and fixes can cite the handbook.
The checks are pure: the rules (parsed from the handbook, :mod:`notebook_assistant.domain.rules`)
and vault-wide facts (title counts, the tag registry) come in a :class:`VaultFacts` built by
the caller. Nothing here restates a rule; every value comes from ``facts.rules``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from notebook_assistant.domain.links import find_links
from notebook_assistant.domain.names import name_key, validate_path
from notebook_assistant.domain.note import EXCALIDRAW_SUFFIX, Note
from notebook_assistant.domain.rules import Rules, TypeRule


@dataclass(frozen=True)
class Violation:
    code: str  # "I-1" … "I-6", "value", "tag", "name"
    message: str
    section: str  # handbook section, e.g. "§4.2"


@dataclass
class VaultFacts:
    """Vault-wide information the per-note checks need."""

    rules: Rules
    title_counts: Counter[str] = field(default_factory=Counter)  # name_key(title) -> count
    registered_tags: frozenset[str] | None = None  # None = registry unknown, skip tag checks


@dataclass(frozen=True)
class Location:
    """Where a path sits in the folder map."""

    path: PurePosixPath
    archived: bool
    inner: PurePosixPath  # path with the 95-Archive/ prefix removed
    root: str  # first folder of ``inner`` ("" for files at the vault root)
    container: str | None  # container name for 15-Incubator/20-Projects/25-Areas paths

    @classmethod
    def of(cls, path: PurePosixPath, rules: Rules) -> Location:
        parts = path.parts
        archived = bool(parts) and parts[0] == rules.archive_root
        inner = PurePosixPath(*parts[1:]) if archived and len(parts) > 1 else path
        root = inner.parts[0] if len(inner.parts) > 1 else ""
        container = (
            inner.parts[1] if root in rules.container_roots and len(inner.parts) > 2 else None
        )
        return cls(path, archived, inner, root, container, rules.code_folders)

    @property
    def is_hub(self) -> bool:
        return (
            self.container is not None
            and len(self.inner.parts) == 3
            and self.inner.name == f"{self.container}.md"
        )

    code_folders: frozenset[str] = frozenset()

    @property
    def in_code_folder(self) -> bool:
        """Inside a project container's code tree (Handbook §11)."""
        return self.container is not None and any(
            part in self.code_folders or part.startswith(".") for part in self.inner.parts[2:-1]
        )


def is_code_tree_file(note: Note, rules: Rules) -> bool:
    """Code-tree files (README, design docs read by code) carry no frontmatter (Handbook §11)."""
    loc = Location.of(note.path, rules)
    return loc.container is not None and (note.frontmatter is None or loc.in_code_folder)


def is_checked(path: PurePosixPath, rules: Rules) -> bool:
    """Whether the invariants apply to ``path`` at all (Handbook §0.1, Scope)."""
    loc = Location.of(path, rules)
    if not path.name.endswith(".md"):
        return False
    if path.as_posix().startswith(rules.state_prefix):
        return False
    return loc.root not in rules.unchecked_roots


def check_note(note: Note, facts: VaultFacts) -> list[Violation]:
    """All violations for one note. Unchecked locations and code-tree files return []."""
    rules = facts.rules
    if not is_checked(note.path, rules) or is_code_tree_file(note, rules):
        return []
    out: list[Violation] = []
    loc = Location.of(note.path, rules)

    for problem in validate_path(note.path, rules.names):
        out.append(Violation("name", problem, "§5"))

    # I-6: folder depth
    depth = rules.max_folder_depth
    if len(note.path.parts) - 1 > depth and not loc.in_code_folder:
        out.append(Violation("I-6", f"more than {depth} folder levels below the root", "§0.1"))

    # I-4: unique title
    if facts.title_counts.get(name_key(note.title), 0) > 1:
        out.append(Violation("I-4", f"title {note.title!r} is not unique in the vault", "§5"))

    # I-1: exactly one known type
    fm = note.frontmatter
    if fm is None:
        out.append(Violation("I-1", "no frontmatter", "§4"))
        return out
    note_type = fm.get("type")
    rule = rules.types.get(note_type) if isinstance(note_type, str) else None
    if rule is None:
        out.append(Violation("I-1", f"unknown or missing type: {note_type!r}", "§4.2"))
        return out

    out.extend(_check_properties(note, rule, rules))
    out.extend(_check_folder(note, rule, loc, rules))

    # I-4: naming pattern
    if rule.title_pattern and not rule.title_pattern.match(note.title):
        out.append(Violation("I-4", f"title doesn't follow the {rule.name} naming pattern", "§5"))

    # I-5: at least one outbound link (property links count)
    if loc.root not in rules.link_exempt_roots and not find_links(note.render()):
        out.append(Violation("I-5", "no outbound link (MOC, project/area, or source)", "§7"))

    # archive
    if loc.archived and fm.get("status") != "archived":
        out.append(
            Violation("value", f"notes in {rules.archive_root} must be status: archived", "§13")
        )

    out.extend(_check_tags(note, facts))
    return out


def _empty(value: object) -> bool:
    return value is None or value == "" or value == []


def _check_properties(note: Note, rule: TypeRule, rules: Rules) -> list[Violation]:
    out: list[Violation] = []
    props = note.props
    missing = [k for k in (*rules.common_required, *rule.required) if _empty(props.get(k))]
    for group in rule.one_of:
        if all(_empty(props.get(k)) for k in group):
            missing.append("|".join(group))
    if missing:
        out.append(Violation("I-3", f"missing required properties: {', '.join(missing)}", "§4"))

    def enum(key: str, allowed: frozenset[str], section: str) -> None:
        value = props.get(key)
        if not _empty(value) and value not in allowed:
            out.append(
                Violation("I-3", f"{key}: {value!r} is not one of {sorted(allowed)}", section)
            )

    for key, allowed in rules.common_enums.items():
        enum(key, allowed, "§4.1")
    enum("status", rule.statuses, "§4.3")
    for key, allowed in rule.enums.items():
        enum(key, allowed, "§4.2")
    # §4: "Dates are YYYY-MM-DD" — the date-valued properties named in §4.1, §4.2 and §13
    for key in (
        "created",
        "updated",
        "date",
        "due",
        "started",
        "ended",
        "last_verified",
        "captured",
        "archived",
    ):
        value = props.get(key)
        if not _empty(value) and not _is_date(value):
            out.append(Violation("value", f"{key}: {value!r} is not a YYYY-MM-DD date", "§4"))
    return out


def _is_date(value: object) -> bool:
    return isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-"


def _check_folder(note: Note, rule: TypeRule, loc: Location, rules: Rules) -> list[Violation]:
    ok: bool
    if loc.container is not None:
        if loc.is_hub:
            ok = rule.name == rules.hub_type_for(loc.root)
        else:
            # §2.1 container members; §10: a drawing takes its owner's type and sits beside it
            ok = rule.container_member or note.path.name.endswith(EXCALIDRAW_SUFFIX)
    else:
        parent = loc.inner.parent.as_posix()
        ok = any(
            parent == folder
            # the archive mirrors the original *top-level* folder (Handbook §13)
            or (loc.archived and parent in (folder, folder.split("/")[0]))
            for folder in rule.folders
        )
    if ok:
        return []
    where = "/".join(loc.inner.parts[:-1]) or "the vault root"
    return [Violation("I-2", f"type {rule.name!r} doesn't belong in {where}", "§2")]


def _check_tags(note: Note, facts: VaultFacts) -> list[Violation]:
    tags = note.frontmatter.get_list("tags") if note.frontmatter else []
    out: list[Violation] = []
    limit = facts.rules.max_tags
    if len(tags) > limit:
        out.append(Violation("tag", f"{len(tags)} tags; at most {limit} are allowed", "§4.1"))
    if facts.registered_tags is not None:
        for tag in tags:
            if str(tag).lstrip("#") not in facts.registered_tags:
                out.append(Violation("tag", f"tag {tag!r} is not in the registry", "§6"))
    return out
