"""Read the vault rules from the Vault Handbook itself (single source of truth).

There is no hand-written schema. :func:`parse_handbook` extracts the rules the checker needs
from the handbook's own tables, so changing the handbook changes the code's behaviour, and a
handbook edit that the parser can't read fails loudly (:class:`HandbookFormatError`) instead of
drifting silently. Sections read:

- top matter: ``version`` in the frontmatter;
- §0.1: invariant scope (exempt folders), I-5 link exemptions, I-6 folder depth;
- §2.1: container member types; §2.3: knowledge topics;
- §3: type → folder (decision order and structural types), and the Inbox (row 1, the §0.3
  fallback);
- §4.1: common required properties, their vocabularies, and those the assistant manages;
  §4.2: per-type required properties and vocabularies; §4.3: allowed statuses; §5: title
  patterns;
- §2: the attachments folder; §12: which captures keep a ``source`` note, and the email formats;
- §13: the archive folder and archive ages; §8.4, §14, §16.2, §17.6, §18.4: the review time
  limits and the lint report; §17.5: the task views;
- §19.1: the digestion flow, in order, and the digest reasons; §19.2, §19.3, §19.5: what
  graduating sets, how a learn task closes, the Original capture and Unverified boxes;
- §19.6: the digest state of notes made from a direct capture.

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
    lifecycle: tuple[str, ...] = ()  # the same statuses in the §4.3 order
    title_pattern: re.Pattern[str] | None = None
    hub_of: str | None = None  # container root this type is the hub of, e.g. "20-Projects"
    container_member: bool = False  # may live inside any container (Handbook §2.1)


@dataclass(frozen=True)
class DigestionRules:
    """What the Digest buttons do to a note (Handbook §19.2, §19.3, §19.5)."""

    reasons: frozenset[str]  # digest_reason values (§19.1)
    graduate: dict[str, str]  # properties Approve to graduate sets (§19.2, step 4a)
    as_is: dict[str, str]  # properties Graduate as-is sets (§19.5)
    task_done: str  # the status a learn task gets when its draft graduates (§19.2)
    produced: str  # the task property linking what it produced (§19.2)
    original_box: str  # first line of the folded box keeping the original (§19.3)
    unverified_box: str  # first line of the box marking unsupported claims (§19.3)


@dataclass(frozen=True)
class CaptureRules:
    """What a capture becomes (Handbook §12) and where captured files go (§2)."""

    long_text_lines: int  # pasted text longer than this keeps a `source` note
    ai_origin: str  # the `origin` of a pasted AI answer, which never keeps a `source` note
    email_formats: tuple[str, ...]  # file suffixes captured as emails, e.g. ".eml"
    attachments: str  # the folder of every embedded file


@dataclass(frozen=True)
class AgeRule:
    """Notes of a type in one of ``statuses`` for at least ``days`` (§13 archive table)."""

    statuses: frozenset[str]
    days: int


@dataclass(frozen=True)
class ReviewRules:
    """The time limits the review buttons use (Handbook §8.4, §13, §16.2, §17.6, §18.4)."""

    archive: dict[str, AgeRule]  # type → when it's archived (§13)
    settle_minutes: int  # a note is swept only after this long without edits (§16.2)
    waiting_nudge_days: int  # `waiting` tasks older than this get a nudge (§17.6)
    learn_untouched_days: int  # learn tasks untouched this long: someday or dropped (§17.6)
    idea_untouched_days: int  # ideas untouched this long: parked or dropped (§18.4)
    session_days: int  # chat sessions older than this are deleted in a batch (§8.4)
    lint_report: str  # the monthly report's path, with YYYY-MM for the month (§14)
    sessions: str  # the folder of the assistant's chat sessions (§8.4)


@dataclass(frozen=True)
class TaskViews:
    """The task views (Handbook §17.5), in the handbook's order."""

    names: tuple[str, ...]
    recent_days: int  # "Recently learned" looks back this far


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
    inbox: str  # where unprocessed or uncertain notes go (§3 row 1, §0.3)
    assistant_managed: frozenset[str]  # properties only the assistant writes (§4.1)
    default_origin: str  # `origin` when a note doesn't say (§4.1)
    digest_flow: tuple[str, ...]  # digest states in order, the queue first (§19.1)
    digestion: DigestionRules  # §19.2, §19.3, §19.5
    direct_capture_digest: tuple[
        str, str
    ]  # (type, digest state) of notes from a direct capture (§19.6)
    capture: CaptureRules  # §12, §2
    review: ReviewRules  # §8.4, §13, §16.2, §17.6, §18.4
    task_views: TaskViews  # §17.5

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


def _assistant_managed(text: str) -> frozenset[str]:
    """§4.1 properties whose comment says the assistant assigns or manages them."""
    block = re.search(r"```yaml\n(.*?)\n```", _section(text, "4.1"), re.S)
    keys = re.findall(
        r"^([a-z_]+):[^#\n]*#.*\bby the assistant\b", block.group(1) if block else "", re.M
    )
    if not keys:
        raise HandbookFormatError("§4.1 names no property managed by the assistant")
    return frozenset(keys)


def _default_origin(text: str) -> str:
    m = re.search(r"^origin:.*\(default: ([\w-]+)\)", _section(text, "4.1"), re.M)
    if not m:
        raise HandbookFormatError("§4.1 doesn't give origin's default")
    return m.group(1)


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


def _statuses(text: str) -> dict[str, tuple[str, ...]]:
    """Each type's statuses in the order §4.3 lists them (its lifecycle)."""
    out: dict[str, tuple[str, ...]] = {}
    for row in _table_rows(_section(text, "4.3")):
        if len(row) < 2:
            continue
        values = [w for tick in _ticks(row[1]) for w in re.findall(r"[a-z][\w-]*", tick)]
        if "archived" in row[1]:
            values.append("archived")
        for name in _ticks(row[0]):
            out[name] = tuple(dict.fromkeys(values))
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


def _inbox(text: str) -> str:
    """The folder of the first §3 row that names a folder but no type: the Inbox (§0.3)."""
    for row in _table_rows(_section(text, "3")):
        left, _, right = row[-1].partition("→")
        folders = [t for t in _ticks(right) if t.endswith("/")]
        if right and folders and not _ticks(left):
            return _folder(folders[0])
    raise HandbookFormatError("§3 names no Inbox row (a folder without a type)")


def _digest_flow(text: str) -> tuple[str, ...]:
    """The ``digest`` row of the §19.1 table: `pending → approved → review → graduated`."""
    for row in _table_rows(_section(text, "19.1")):
        if _ticks(row[0]) == ["digest"] and len(row) > 1:
            flow = _ticks(row[1])
            if flow and "→" in flow[0]:
                return tuple(s.strip() for s in flow[0].split("→"))
    raise HandbookFormatError("§19.1 has no digest flow (`a → b → …`)")


def _pairs(cell: str) -> dict[str, str]:
    """`key: value` ticks of a sentence, in order."""
    found = (re.fullmatch(r"([a-z_]+): ([\w-]+)", t) for t in _ticks(cell))
    return {m.group(1): m.group(2) for m in found if m}


def _digestion(text: str) -> DigestionRules:
    s191, s192, s193, s195 = (_section(text, n) for n in ("19.1", "19.2", "19.3", "19.5"))
    reasons_row = next((r for r in _table_rows(s191) if _ticks(r[0]) == ["digest_reason"]), [])
    graduate_row = next((r for r in _table_rows(s192) if "Approve to graduate" in r[0]), [])
    as_is = re.search(r"^\s*- Sets (.+)$", s195, re.M)
    task = re.search(r"the task is set `([\w-]+)` with `([\w-]+)`", s192)
    boxes = re.findall(r"`(> \[![a-z]+\]-? [^`]+)`", s193)
    if not (reasons_row and graduate_row and as_is and task):
        raise HandbookFormatError("§19 doesn't define the digest reasons or graduation")
    original = next((b for b in boxes if "[!quote]" in b), None)
    unverified = next((b for b in boxes if "[!question]" in b), None)
    if original is None or unverified is None:
        raise HandbookFormatError("§19.3 names no Original capture or Unverified box")
    return DigestionRules(
        reasons=frozenset(_ticks(reasons_row[1])),
        graduate=_pairs(graduate_row[-1]),
        as_is=_pairs(as_is.group(1)),
        task_done=task.group(1),
        produced=task.group(2),
        original_box=original,
        unverified_box=unverified,
    )


def _direct_capture_digest(text: str) -> tuple[str, str]:
    m = re.search(r"New (\w[\w-]*) notes from it get `digest: ([\w-]+)`", _section(text, "19.6"))
    if not m:
        raise HandbookFormatError("§19.6 doesn't say which digest state direct-capture notes get")
    return m.group(1), m.group(2)


def _capture(text: str) -> CaptureRules:
    s12 = _section(text, "12")
    lines = re.search(r"over about (\d+) lines", s12)
    ai = re.search(r"always get `origin: ([\w-]+)`", s12)
    email = re.search(r"^- \*\*Emails\*\* \((.+?)\)", s12, re.M)
    attachments = re.search(r"^(\S+)/\s+All embedded files", _section(text, "2"), re.M)
    formats = tuple(t for t in _ticks(email.group(1)) if t.startswith(".")) if email else ()
    if not (lines and ai and formats and attachments):
        raise HandbookFormatError(
            "§12 or §2 doesn't define long text, AI answers, email formats or Attachments"
        )
    return CaptureRules(int(lines.group(1)), ai.group(1), formats, attachments.group(1))


def _number(block: str, pattern: str, where: str) -> int:
    m = re.search(pattern, block)
    if not m:
        raise HandbookFormatError(f"{where} doesn't give its time limit")
    return int(m.group(1))


def _review(text: str) -> ReviewRules:
    archive: dict[str, AgeRule] = {}
    for row in _table_rows(_section(text, "13")):
        days = re.search(r"for (\d+)\+ days", row[-1])
        if "days" in row[-1] and not days:
            raise HandbookFormatError(f"§13 row {row[0].strip()!r} gives no `for N+ days` age")
        if days and len(row) > 1:
            archive[row[0].strip()] = AgeRule(frozenset(_ticks(row[-1])), int(days.group(1)))
    if not archive:
        raise HandbookFormatError("§13 gives no archive ages (`for N+ days`)")
    s176 = _section(text, "17.6")
    return ReviewRules(
        archive=archive,
        settle_minutes=_number(_section(text, "16.2"), r"(\d+) minutes without edits", "§16.2"),
        waiting_nudge_days=_number(s176, r"`waiting` tasks older than (\d+) days", "§17.6"),
        learn_untouched_days=_number(s176, r"Learn tasks untouched for (\d+) days", "§17.6"),
        idea_untouched_days=_number(_section(text, "18.4"), r"untouched for (\d+) days", "§18.4"),
        session_days=_number(_section(text, "8.4"), r"older than (\d+) days", "§8.4"),
        lint_report=_lint_report(text),
        sessions=_sessions(text),
    )


def _sessions(text: str) -> str:
    m = re.search(r"chat sessions \(`([^`]+?)/?`\)", _section(text, "8.4"))
    if not m:
        raise HandbookFormatError("§8.4 doesn't name the chat sessions folder")
    return m.group(1)


def _task_views(text: str) -> TaskViews:
    block = _section(text, "17.5")
    names = tuple(m for row in _table_rows(block) for m in re.findall(r"\*\*(.+?)\*\*", row[0]))
    if not names:
        raise HandbookFormatError("§17.5 names no task views (**View**)")
    return TaskViews(names, _number(block, r"done in the last (\d+) days", "§17.5"))


def _lint_report(text: str) -> str:
    m = re.search(r"`([^`]*YYYY-MM\.md)`", _section(text, "14"))
    if not m:
        raise HandbookFormatError("§14 doesn't name the lint report (`…YYYY-MM.md`)")
    return m.group(1)


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
            statuses=frozenset(statuses[name]),
            lifecycle=statuses[name],
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
        inbox=_inbox(text),
        assistant_managed=_assistant_managed(text),
        default_origin=_default_origin(text),
        digest_flow=_digest_flow(text),
        digestion=_digestion(text),
        direct_capture_digest=_direct_capture_digest(text),
        capture=_capture(text),
        review=_review(text),
        task_views=_task_views(text),
    )
