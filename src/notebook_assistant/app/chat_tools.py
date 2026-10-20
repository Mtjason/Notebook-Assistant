"""The tools the chat model may call (docs/architecture.md §3.3), in two tiers:

- **read** (always allowed): ``search``, ``read_note``;
- **propose** (returns a pending changeset, writes nothing): ``propose_note``, ``propose_edit``,
  and ``propose_digest`` (paste-to-digest through the extraction planner, Handbook §19.6).

The model can never apply: applying happens only through the approval endpoints. A note marked
``sensitive`` is shown with its values hidden (§4.2). The scope (all, work or personal) limits
what the tools read and change. Each tool returns text for the model; a refused call says why,
so the model can correct itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.browse import find_note
from notebook_assistant.app.extract import Capture, ExtractionError, plan_extraction
from notebook_assistant.app.index import VaultIndex, is_state_path
from notebook_assistant.app.search import Meaning
from notebook_assistant.app.search import search as find
from notebook_assistant.domain.changeset import Changeset, Operation
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.ids import content_hash
from notebook_assistant.domain.invariants import check_note, new_violations
from notebook_assistant.domain.jsontypes import JsonObject, JsonValue
from notebook_assistant.domain.names import name_key
from notebook_assistant.domain.note import NOTE_SUFFIX, Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import LanguageModel, LLMError, ToolSpec
from notebook_assistant.ports.search import SearchIndex
from notebook_assistant.ports.vault import VaultStore
from notebook_assistant.store import changesets as cs_store

ALL_SCOPES = "all"
SEARCH_HITS = 8
HIDDEN = "(sensitive: the values in this note are hidden from the chat)"


class ToolError(ValueError):
    """The call can't be done as asked; its message goes back to the model."""


@dataclass
class ToolContext:
    store: VaultStore
    search_index: SearchIndex
    rules: Rules
    config: Config
    handbook: str
    now: datetime
    scope: str  # "all", or a `scope` value the turn is limited to
    created_by: str  # "session:<id>"
    planner: Callable[[], LanguageModel]  # for propose_digest
    meaning: Meaning | None = None  # this PC's embeddings, if on
    cited: list[str] = field(default_factory=list)  # note titles read
    changesets: list[str] = field(default_factory=list)  # proposed changeset ids

    def index(self) -> VaultIndex:
        return VaultIndex.build(self.store)


def in_scope(note: Note, scope: str) -> bool:
    return scope == ALL_SCOPES or note.prop("scope") == scope


def shown(note: Note) -> str:
    """The note as the model may see it: its values hidden when it's marked ``sensitive``."""
    if note.prop("sensitive") is not True:
        return note.render()
    headings = [line for line in note.body.splitlines() if line.startswith("#")]
    keys = ", ".join(note.props)
    return f"Properties: {keys}\n" + "\n".join(headings) + f"\n{HIDDEN}\n"


def resolve(index: VaultIndex, ref: str) -> Note | None:
    """A note by path, id, title or alias (case-insensitive)."""
    found = find_note(index, ref) or find_note(index, ref + NOTE_SUFFIX)
    if found is not None:
        return found
    key = name_key(ref.strip("[]").split("|")[0])
    for note in index.notes.values():
        aliases = note.frontmatter.get_list("aliases") if note.frontmatter else []
        if not is_state_path(note.path) and (
            name_key(note.title) == key or key in {name_key(str(a)) for a in aliases}
        ):
            return note
    return None


def _text(args: JsonObject, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"`{key}` is required text")
    return value


def _search(ctx: ToolContext, args: JsonObject) -> str:
    index = ctx.index()
    lines: list[str] = []
    query = _text(args, "query")
    for hit in find(
        ctx.store, ctx.search_index, ctx.rules, query, limit=SEARCH_HITS * 2, meaning=ctx.meaning
    ):
        note = index.note(PurePosixPath(hit.path))
        if note is None or not in_scope(note, ctx.scope):
            continue
        lines.append(f"- [[{hit.title}]] ({hit.path}): {hit.snippet}")
        if len(lines) == SEARCH_HITS:
            break
    return "\n".join(lines) or "No note matches."


def _read_note(ctx: ToolContext, args: JsonObject) -> str:
    note = resolve(ctx.index(), _text(args, "note"))
    if note is None or not in_scope(note, ctx.scope):
        raise ToolError("no such note in this scope; search for it first")
    ctx.cited.append(note.title)
    return f"{note.path.as_posix()}\n\n{shown(note)}"


def _save(ctx: ToolContext, reason: str, ops: list[Operation]) -> str:
    cs = Changeset(
        reason=reason,
        created_by=ctx.created_by,
        created=ctx.now.isoformat(timespec="seconds"),
        ops=ops,
    )
    cs_store.save(ctx.store, cs)
    ctx.changesets.append(cs.id)
    return f"Proposed as changeset {cs.id}; the user reviews and applies it. Nothing changed yet."


def _properties(args: JsonObject) -> dict[str, JsonValue]:
    props = args.get("properties")
    if not isinstance(props, dict):
        raise ToolError("`properties` must be an object of Handbook §4 properties")
    return props


def _propose_note(ctx: ToolContext, args: JsonObject) -> str:
    title, folder, body = (
        _text(args, "title"),
        _text(args, "folder").strip("/"),
        _text(args, "body"),
    )
    index = ctx.index()
    if resolve(index, title) is not None:
        raise ToolError(f"a note titled {title!r} exists; propose_edit it instead (§15 rule 3)")
    note = Note(path=PurePosixPath(folder) / f"{title}{NOTE_SUFFIX}", body=body.strip() + "\n")
    fm = note.ensure_frontmatter()
    for key, value in _properties(args).items():
        fm.set(key, value)
    if not in_scope(note, ctx.scope):
        raise ToolError(f"this chat is limited to scope {ctx.scope!r}")
    problems = check_note(note, index.facts())
    if problems:
        raise ToolError(
            "breaks the handbook: " + "; ".join(f"{v.message} ({v.section})" for v in problems)
        )
    op = Operation("create", note.path, content=note.render(), label="new note")
    return _save(ctx, f"Chat: new note {title}", [op])


def _propose_edit(ctx: ToolContext, args: JsonObject) -> str:
    index = ctx.index()
    before = resolve(index, _text(args, "note"))
    if before is None or not in_scope(before, ctx.scope) or before.prop("sensitive") is True:
        raise ToolError(
            "no such note to edit in this scope (sensitive notes are edited in Obsidian)"
        )
    after = Note.parse(before.path, _text(args, "new_text"))
    problems = new_violations(before, after, index.facts())
    if problems:
        raise ToolError(
            "breaks the handbook: " + "; ".join(f"{v.message} ({v.section})" for v in problems)
        )
    stored = index.text(before.path)
    assert stored is not None, "the note comes from the index"
    if after.render() == stored:
        raise ToolError("the new text is the same as the note")
    op = Operation(
        "write", before.path, content=after.render(), base_hash=content_hash(stored), label="edit"
    )
    return _save(ctx, f"Chat: edit {before.title}", [op])


def _propose_digest(ctx: ToolContext, args: JsonObject) -> str:
    origin = str(args.get("origin") or ctx.rules.default_origin)
    if origin not in ctx.rules.common_enums["origin"]:
        raise ToolError(f"origin must be one of {sorted(ctx.rules.common_enums['origin'])}")
    capture = Capture(_text(args, "text"), origin, "chat paste")
    try:
        result = plan_extraction(
            capture,
            ctx.index(),
            ctx.planner(),
            config=ctx.config,
            handbook=ctx.handbook,
            now=ctx.now,
            created_by=ctx.created_by,
        )
    except (ExtractionError, LLMError) as exc:
        raise ToolError(
            f"the extraction planner couldn't plan it: {str(exc).splitlines()[0]}"
        ) from exc
    cs_store.save(ctx.store, result.changeset)
    ctx.changesets.append(result.changeset.id)
    titles = ", ".join(o.after.title for o in result.outcomes.values())
    cs_id = result.changeset.id
    return f"Proposed as changeset {cs_id} with its split map: {titles}. Nothing changed yet."


def _schema(**props: str) -> JsonObject:
    properties: dict[str, JsonValue] = {k: {"type": v} for k, v in props.items()}
    return {"type": "object", "properties": properties, "required": list(props)}


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    tier: str  # "read" | "propose"
    run: Callable[[ToolContext, JsonObject], str]


NOTE_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "folder": {"type": "string"},
        "body": {"type": "string"},
        "properties": {"type": "object"},
    },
    "required": ["title", "folder", "body", "properties"],
}

TOOLS: dict[str, Tool] = {
    t.spec.name: t
    for t in (
        Tool(
            ToolSpec(
                "search",
                "Full-text search over the vault's notes (Chinese and English). "
                "Returns titles, paths and snippets.",
                _schema(query="string"),
            ),
            "read",
            _search,
        ),
        Tool(
            ToolSpec(
                "read_note",
                "Read one note by title, alias or path. Cite it as [[title]] when you use it.",
                _schema(note="string"),
            ),
            "read",
            _read_note,
        ),
        Tool(
            ToolSpec(
                "propose_note",
                "Propose a new note: its title, its folder (Handbook §2, §3), a body starting at "
                "`##` headings, and its Handbook §4 properties. The user approves it.",
                NOTE_SCHEMA,
            ),
            "propose",
            _propose_note,
        ),
        Tool(
            ToolSpec(
                "propose_edit",
                "Propose replacing a note's full text (frontmatter and body). Keep the user's "
                "wording; the user approves it.",
                _schema(note="string", new_text="string"),
            ),
            "propose",
            _propose_edit,
        ),
        Tool(
            ToolSpec(
                "propose_digest",
                "Digest pasted material into notes through the extraction planner (Handbook "
                "§19.6), which splits it into every note it yields. `origin` is ai-chat for an "
                "AI answer.",
                _schema(text="string", origin="string"),
            ),
            "propose",
            _propose_digest,
        ),
    )
}


def run_tool(ctx: ToolContext, name: str, args: JsonObject) -> tuple[str, bool]:
    """(the result text, whether it's an error) for one call."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"no tool {name!r}", True
    try:
        return tool.run(ctx, args), False
    except ToolError as exc:
        return str(exc), True
