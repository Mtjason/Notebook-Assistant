"""Read the vault rules from the Vault Handbook itself (single source of truth).

There is no hand-written schema. :func:`parse_handbook` extracts the rules the checker needs
from the handbook's own tables, so changing the handbook changes the code's behaviour, and a
handbook edit that the parser can't read fails loudly (:class:`HandbookFormatError`) instead of
drifting silently. Sections read:

- top matter: ``version`` in the frontmatter;
- §0.1: invariant scope (exempt folders), I-5 link exemptions, I-6 folder depth;
- §2.1: container member types; §2.3: knowledge topics;
- §3: type → folder (decision order and structural types);
- §4.1: common required properties and their vocabularies; §4.2: per-type required properties
  and vocabularies; §4.3: allowed statuses; §5: title patterns;
- §13: the archive folder.

Pure: takes text, returns data. Loading the file is :mod:`notebook_assistant.handbook`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from notebook_assistant.domain.frontmatter import load_yaml
from notebook_assistant.domain.names import NameRules
from notebook_assistant.domain.note import split_frontmatter


class HandbookFormatError(ValueError):
    """The handbook changed in a way the rule parser can't read."""


@dataclass(frozen=True)
class TypeRule:
    """What the handbook requires of one note type."""

    name: str
    folders: tuple[str, ...] = ()  # exact vault-relative folders; () = containers only
    required: tuple[str, ...] = ()
    one_of: tuple[tuple[str, ...], ...] = ()  # groups where at least one key is required
    enums: dict[str, frozenset[str]] = field(default_factory=dict)
    statuses: frozenset[str] = frozenset()
    title_pattern: re.Pattern[str] | None = None
    hub_of: str | None = None  # container root this type is the hub of, e.g. "20-Projects"
    container_member: bool = False  # may live inside any container (Handbook §2.1)


@dataclass(frozen=True)
class Rules:
    version: str
    common_required: tuple[str, ...]
    common_enums: dict[str, frozenset[str]]
    types: dict[str, TypeRule]
    topics: tuple[str, ...]
    unchecked_roots: frozenset[str]  # top-level folders exempt from the invariants
    state_prefix: str  # the assistant's state folder, e.g. "99-System/Assistant/"
    link_exempt_roots: frozenset[str]
    max_folder_depth: int
    archive_root: str
    max_tags: int
    tag_registry: str  # vault path of the tag registry (§6)
    names: NameRules  # §5.1
    code_folders: frozenset[str]  # folder names that hold project code (§11)

    @property
    def container_roots(self) -> frozenset[str]:
        return frozenset(r.hub_of for r in self.types.values() if r.hub_of)

    def hub_type_for(self, root: str) -> str | None:
        return next((r.name for r in self.types.values() if r.hub_of == root), None)


# --------------------------------------------------------------------------- section helpers


def _section(text: str, number: str) -> str:
    """Body of the section headed ``## <number>.`` or ``### <number> `` up to the next heading
    of the same or a higher level."""
    level = "###" if "." in number else "##"
    head = re.search(rf"^{level} {re.escape(number)}\.?\s.*$", text, re.M)
    if not head:
        raise HandbookFormatError(f"section §{number} not found")
    stop = r"^#{2,3} " if level == "###" else r"^## "
    nxt = re.compile(stop, re.M).search(text, head.end())
    return text[head.end() : nxt.start() if nxt else len(text)]


def _table_rows(block: str) -> list[list[str]]:
    """Rows of every Markdown table in ``block`` (header and separator rows excluded)."""
    rows: list[list[str]] = []
    lines = block.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        if re.fullmatch(r"\|[\s:|-]+\|?", line.strip()):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if re.fullmatch(r"\|[\s:|-]+\|?", nxt.strip()):
            continue  # header row
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        rows.append(cells)
    return rows


def _ticks(cell: str) -> list[str]:
    """Contents of `backtick` spans, with Markdown table escapes (``\\|``) removed."""
    return [t.replace("\\|", "|") for t in re.findall(r"`([^`]+)`", cell)]


def _folder(tick: str) -> str:
    return tick.rstrip("/")


# --------------------------------------------------------------------------- parsers


def _version(text: str) -> str:
    fm, _ = split_frontmatter(text.replace("\r\n", "\n"))
    data = load_yaml(fm or "") or {}
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str | int | float):
        raise HandbookFormatError("frontmatter has no version")
    return str(version)


def _scope(text: str) -> tuple[frozenset[str], str]:
    s01 = _section(text, "0.1")
    m = re.search(r"^\*\*Scope:\*\*(.*)$", s01, re.M)
    if not m:
        raise HandbookFormatError("§0.1 has no **Scope:** sentence")
    folders = list(dict.fromkeys(t for t in _ticks(m.group(1)) if t.endswith("/")))
    state = [f for f in folders if f.count("/") > 1]
    if len(state) != 1:
        raise HandbookFormatError("§0.1 Scope must name exactly one nested state folder")
    roots = frozenset(_folder(f) for f in folders if f.count("/") == 1)
    return roots, state[0]


def _invariant_rows(text: str) -> dict[str, str]:
    return {r[0]: r[1] for r in _table_rows(_section(text, "0.1")) if len(r) >= 2}


def _link_exempt(text: str) -> frozenset[str]:
    row = _invariant_rows(text).get("I-5", "")
    after = row.split("Exceptions:", 1)
    if len(after) != 2:
        raise HandbookFormatError("I-5 has no 'Exceptions:' list")
    return frozenset(_folder(t) for t in _ticks(after[1]) if t.endswith("/"))


def _max_depth(text: str) -> int:
    m = re.search(r"at most \*\*(\d+) levels\*\*", _invariant_rows(text).get("I-6", ""))
    if not m:
        raise HandbookFormatError("I-6 has no 'at most **N levels**'")
    return int(m.group(1))


def _topics(text: str) -> tuple[str, ...]:
    topics = tuple(_folder(_ticks(r[0])[0]) for r in _table_rows(_section(text, "2.3")) if r)
    if not topics:
        raise HandbookFormatError("§2.3 lists no topic folders")
    return topics


def _containers(text: str) -> dict[str, str]:
    """hub type -> container root, from §2.1: "`15-Incubator/<Name>/`, … are containers … (type
    `idea`, `project` or `area`)" (roots and hub types in the same order)."""
    s21 = _section(text, "2.1")
    first = s21.strip().split("\n", 1)[0]
    roots = [t.split("<Name>")[0].rstrip("/") for t in _ticks(first) if "<Name>" in t]
    hub_line = re.search(r"hub note with the same name \((.*?)\)", s21)
    hubs = [t for t in _ticks(hub_line.group(1)) if "<" not in t] if hub_line else []
    if not roots or len(roots) != len(hubs):
        raise HandbookFormatError("§2.1 must list container roots and their hub types in order")
    return dict(zip(hubs, roots, strict=True))


def _container_members(text: str) -> frozenset[str]:
    members = re.findall(r"\*\*`([\w-]+)`\*\* notes", _section(text, "2.1"))
    if not members:
        raise HandbookFormatError("§2.1 names no container member types")
    return frozenset(members)


def _placements(text: str, topics: tuple[str, ...]) -> dict[str, dict[str, object]]:
    """type -> {"folders": [...], "hub_of": root | None} from the §3 tables."""
    out: dict[str, dict[str, object]] = {}
    for row in _table_rows(_section(text, "3")):
        cell = row[-1]
        if "→" not in cell:
            continue
        left, right = cell.split("→", 1)
        names = _ticks(left)
        if not names:
            continue
        folders: list[str] = []
        for tick in _ticks(right):
            if not tick.endswith("/"):
                continue
            if "<Name>" in tick:
                continue  # container hubs come from §2.1
            if "<Topic>" in tick:
                base = _folder(tick.split("<Topic>")[0])
                folders.extend(f"{base}/{t}" for t in topics)
            else:
                folders.append(_folder(tick))
        out[names[0]] = {"folders": folders, "hub_of": None}
    return out


_ENUM_TICK = re.compile(r"^([a-z_]+):\s*(.+\|.+)$")


def _enum_from_tick(tick: str) -> tuple[str, frozenset[str]] | None:
    m = _ENUM_TICK.match(tick)
    if not m:
        return None
    return m.group(1), frozenset(v.strip() for v in m.group(2).split("|"))


def _name_rules(text: str) -> NameRules:
    s51 = _section(text, "5.1")

    def bullet(start: str) -> str:
        m = re.search(rf"^- {re.escape(start)}(.*)$", s51, re.M)
        if not m:
            raise HandbookFormatError(f"§5.1 has no bullet starting {start!r}")
        return m.group(1)

    def chars(line: str) -> frozenset[str]:
        ticks = _ticks(line)
        return frozenset(ticks[0].split()) if ticks else frozenset()

    reserved: set[str] = set()
    for tick in _ticks(bullet("Reserved names")):
        m = re.fullmatch(r"([A-Z]+)(\d)–\1(\d)", tick)
        if m:
            reserved |= {f"{m.group(1)}{i}" for i in range(int(m.group(2)), int(m.group(3)) + 1)}
        else:
            reserved.add(tick.upper())
    lengths = re.findall(r"\*\*(\d+)\*\*", bullet("A name is at most"))
    forbidden = chars(bullet("Characters never allowed in a file or folder name"))
    in_titles = chars(bullet("Characters also never allowed in a note title"))
    if not forbidden or not in_titles or not reserved or len(lengths) != 2:
        raise HandbookFormatError("§5.1 name rules are incomplete")
    return NameRules(
        forbidden=forbidden,
        forbidden_in_titles=in_titles,
        reserved=frozenset(reserved),
        max_name=int(lengths[0]),
        max_path=int(lengths[1]),
    )


def _code_folders(text: str) -> frozenset[str]:
    first = next((ln for ln in _section(text, "11").split("\n") if ln.startswith("- ")), "")
    folders = frozenset(_folder(t) for t in _ticks(first) if t.endswith("/"))
    if not folders:
        raise HandbookFormatError("§11 names no code folders")
    return folders


def _tag_registry(text: str) -> str:
    m = re.search(r"allowed tags are listed in `([^`]+\.md)`", _section(text, "6"))
    if not m:
        raise HandbookFormatError("§6 doesn't name the tag registry note")
    return m.group(1)


def _max_tags(text: str) -> int:
    m = re.search(r"^tags:.*#\s*max (\d+)", _section(text, "4.1"), re.M)
    if not m:
        raise HandbookFormatError("§4.1 doesn't state the maximum number of tags")
    return int(m.group(1))


def _common(text: str) -> tuple[tuple[str, ...], dict[str, frozenset[str]]]:
    block = re.search(r"```yaml\n(.*?)\n```", _section(text, "4.1"), re.S)
    if not block:
        raise HandbookFormatError("§4.1 has no yaml block")
    required: list[str] = []
    enums: dict[str, frozenset[str]] = {}
    for line in block.group(1).split("\n"):
        m = re.match(r"^([a-z_]+):\s*(\*)?\s*(?:#\s*(.*))?$", line)
        if not m:
            continue
        key, star, comment = m.group(1), m.group(2), m.group(3) or ""
        if star:
            required.append(key)
        vocab = re.match(r"^([a-z][\w-]*(?:\s*\|\s*[a-z][\w-]*)+)", comment)
        if vocab:
            enums[key] = frozenset(v.strip() for v in vocab.group(1).split("|"))
    if not required:
        raise HandbookFormatError("§4.1 marks no required properties")
    return tuple(required), enums


def _per_type(text: str) -> dict[str, dict[str, object]]:
    """type -> required keys, one-of groups and vocabularies, from the §4.2 table and notes."""
    s42 = _section(text, "4.2")
    out: dict[str, dict[str, object]] = {}
    for row in _table_rows(s42):
        if len(row) < 3 or not _ticks(row[0]):
            continue
        name = _ticks(row[0])[0]
        required: list[str] = []
        one_of: list[tuple[str, ...]] = []
        enums: dict[str, frozenset[str]] = {}
        req_cell, opt_cell = row[1], row[2]
        if " or " in req_cell:
            one_of.append(tuple(_ticks(req_cell)))
        else:
            for tick in _ticks(req_cell):
                parsed = _enum_from_tick(tick)
                if parsed:
                    required.append(parsed[0])
                    enums[parsed[0]] = parsed[1]
                else:
                    required.append(tick.split(":")[0].strip())
        for tick in _ticks(opt_cell):
            parsed = _enum_from_tick(tick)
            if parsed:
                enums[parsed[0]] = parsed[1]
        out[name] = {"required": required, "one_of": one_of, "enums": enums}
    # vocabulary notes below the table: "`domain` values for SOPs: `a | b | c`."
    for m in re.finditer(r"`([a-z_]+)` values for (\w+?)s?: `([^`]+)`", s42):
        key, type_name, values = m.group(1), m.group(2).lower(), m.group(3)
        if type_name not in out:
            raise HandbookFormatError(f"§4.2 vocabulary note names unknown type {type_name!r}")
        vocab = out[type_name]["enums"]
        assert isinstance(vocab, dict)
        vocab[key] = frozenset(v.strip() for v in values.split("|"))
    return out


def _statuses(text: str) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for row in _table_rows(_section(text, "4.3")):
        if len(row) < 2:
            continue
        values = {w for tick in _ticks(row[1]) for w in re.findall(r"[a-z][\w-]*", tick)}
        if "archived" in row[1]:
            values.add("archived")
        for name in _ticks(row[0]):
            out[name] = frozenset(values)
    return out


def _title_patterns(text: str) -> dict[str, re.Pattern[str]]:
    """Types whose §5 naming pattern is a single `template` get an enforced regex."""
    out: dict[str, re.Pattern[str]] = {}
    for row in _table_rows(_section(text, "5")):
        if len(row) < 2:
            continue
        ticks = _ticks(row[1])
        if len(ticks) != 1 or row[1].strip() != f"`{ticks[0]}`":
            continue  # free-form pattern ("Short name", "Verb phrase …"): not enforced
        template = ticks[0]
        if re.fullmatch(r"<[^>]+>", template):
            continue  # "<Name>": any name
        regex = re.escape(template)
        regex = regex.replace(re.escape("YYYY-MM-DD"), r"\d{4}-\d{2}-\d{2}")
        regex = regex.replace("\\<", "<").replace("\\>", ">")
        # adjacent placeholders ("<verb> <object>") match any text: `SOP - 採購辦公設備` is valid
        regex = re.sub(r"<[^>]+>(?:\\? <[^>]+>)*", ".+", regex)
        for name in re.split(r"\s*/\s*", row[0]):
            out[name.strip()] = re.compile(f"^{regex}$")
    return out


def _archive_root(text: str) -> str:
    m = re.search(r"moving a note into `([^`]+)/`", _section(text, "13"))
    if not m:
        raise HandbookFormatError("§13 doesn't name the archive folder")
    return m.group(1)


def parse_handbook(text: str) -> Rules:
    text = text.replace("\r\n", "\n")
    topics = _topics(text)
    placements = _placements(text, topics)
    per_type = _per_type(text)
    statuses = _statuses(text)
    patterns = _title_patterns(text)
    members = _container_members(text)
    containers = _containers(text)

    names = set(per_type)
    missing = sorted(names - set(placements) - members - set(containers))
    if missing:
        raise HandbookFormatError(f"§3 gives no folder for types: {', '.join(missing)}")
    no_status = sorted(names - set(statuses))
    if no_status:
        raise HandbookFormatError(f"§4.3 gives no statuses for types: {', '.join(no_status)}")

    types: dict[str, TypeRule] = {}
    for name in sorted(names):
        place = placements.get(name, {"folders": [], "hub_of": None})
        spec = per_type[name]
        folders = place["folders"]
        assert isinstance(folders, list)
        required = spec["required"]
        one_of = spec["one_of"]
        enums = spec["enums"]
        assert isinstance(required, list) and isinstance(one_of, list) and isinstance(enums, dict)
        types[name] = TypeRule(
            name=name,
            folders=tuple(folders),
            required=tuple(required),
            one_of=tuple(one_of),
            enums=dict(enums),
            statuses=statuses[name],
            title_pattern=patterns.get(name),
            hub_of=containers.get(name),
            container_member=name in members,
        )
    unchecked, state_prefix = _scope(text)
    common_required, common_enums = _common(text)
    return Rules(
        version=_version(text),
        common_required=common_required,
        common_enums=common_enums,
        types=types,
        topics=topics,
        unchecked_roots=unchecked,
        state_prefix=state_prefix,
        link_exempt_roots=_link_exempt(text),
        max_folder_depth=_max_depth(text),
        archive_root=_archive_root(text),
        max_tags=_max_tags(text),
        tag_registry=_tag_registry(text),
        names=_name_rules(text),
        code_folders=_code_folders(text),
    )
