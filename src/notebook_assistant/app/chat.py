"""Chat (docs/architecture.md §2.2, §3.4): one turn of a conversation with the vault.

:func:`start_session` creates the session note; :func:`answer` runs a plain tool-use loop: the
model sees the instructions and the handbook (a cached prefix), the conversation so far (read
back from the session note, so either PC continues it), the notes you pinned, the notes the
index finds for your question, and your question. It calls tools (:mod:`app.chat_tools`) until
it answers, at most ``limits.tool_calls_per_turn`` times. Every event (each piece of text, each
tool call, each proposed changeset) goes to ``emit`` as it happens; the turn is then appended to
the session note with what it cited and proposed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from notebook_assistant.app.chat_tools import TOOLS, ToolContext, in_scope, resolve, run_tool, shown
from notebook_assistant.app.index import VaultIndex
from notebook_assistant.app.search import Meaning
from notebook_assistant.app.search import search as find
from notebook_assistant.domain import session
from notebook_assistant.domain.config import Config
from notebook_assistant.domain.ids import new_ulid
from notebook_assistant.domain.jsontypes import JsonObject, JsonValue
from notebook_assistant.domain.note import Note
from notebook_assistant.domain.rules import Rules
from notebook_assistant.ports.llm import (
    ChatMessage,
    ChatModel,
    ChatRequest,
    LanguageModel,
    ToolResult,
)
from notebook_assistant.ports.search import SearchIndex
from notebook_assistant.ports.vault import VaultStore

Emit = Callable[[JsonObject], None]
RETRIEVED = 5  # notes the index finds for the question, shown with their snippets
TITLE_CHARS = 60

INSTRUCTIONS = """\
You are the assistant of an Obsidian vault kept under the Vault Handbook that follows. Answer from
the user's notes first: search and read them, and cite every note you use as [[its title]]. Say
plainly when the notes don't cover something; mark anything you add from general knowledge as such.

You can't change the vault. To change it, call a propose tool: propose_note, propose_edit, or
propose_digest for pasted material to digest (Handbook §19.6). Each becomes a changeset the user
reviews and applies; tell them what you proposed. Obey the handbook exactly in what you propose.
Answer in the language of the user's question, whatever language the notes are in: a question
in English gets an English answer, one in Chinese a Chinese answer.
"""


class ChatError(ValueError):
    """No such session."""


@dataclass(frozen=True)
class Answer:
    session: str  # the session note's path
    text: str
    changesets: list[str]
    cited: list[str]


def start_session(
    store: VaultStore,
    rules: Rules,
    *,
    title: str,
    now: datetime,
    device: str,
    model: str,
    scope: str,
) -> Note:
    sid = f"ses-{new_ulid()}"
    note = session.new_session(
        rules.review.sessions,
        sid,
        title=title[:TITLE_CHARS] or sid,
        started=now,
        device=device,
        model=model,
        scope=scope,
    )
    store.write_text(note.path, note.render())
    return note


def _session(store: VaultStore, path: str) -> Note:
    note = VaultIndex.build(store).note(PurePosixPath(path))
    if note is None:
        raise ChatError(f"no session {path!r}")
    return note


def history(note: Note) -> list[ChatMessage]:
    """The conversation so far as model messages (text only; tool calls aren't replayed)."""
    return [
        ChatMessage("user" if t.role == session.YOU else "assistant", t.text)
        for t in session.turns(note)
        if t.text
    ]


def context(ctx: ToolContext, question: str, pinned: list[str]) -> str:
    """Pinned notes in full, then the notes the index finds for the question."""
    index = VaultIndex.build(ctx.store)
    parts: list[str] = []
    for ref in pinned:
        note = resolve(index, ref)
        if note is not None and in_scope(note, ctx.scope):
            ctx.cited.append(note.title)
            parts.append(f"## Pinned: [[{note.title}]]\n\n{shown(note)}")
    hits = find(
        ctx.store,
        ctx.search_index,
        ctx.rules,
        question,
        limit=RETRIEVED,
        kind="note",
        every_word=False,
        meaning=ctx.meaning,
    )
    found = [f"- [[{h.title}]] ({h.path}): {h.snippet}" for h in hits]
    if found:
        parts.append("## Notes the search found for this question\n\n" + "\n".join(found))
    parts.append(f"## The question\n\n{question}")
    return "\n\n".join(parts)


def answer(
    store: VaultStore,
    session_path: str,
    question: str,
    *,
    pinned: list[str],
    chat: ChatModel,
    planner: Callable[[], LanguageModel],
    search_index: SearchIndex,
    config: Config,
    rules: Rules,
    handbook: str,
    now: datetime,
    emit: Emit,
    meaning: Meaning | None = None,
) -> Answer:
    note = _session(store, session_path)
    scope = str(note.prop("scope") or "all")
    ctx = ToolContext(
        store,
        search_index,
        rules,
        config,
        handbook,
        now,
        scope,
        created_by=f"session:{note.prop('id')}",
        planner=planner,
        meaning=meaning,
    )
    messages = [*history(note), ChatMessage("user", context(ctx, question, pinned))]
    tools = tuple(t.spec for t in TOOLS.values())
    text_parts: list[str] = []
    used: list[str] = []
    tokens_in = tokens_out = 0
    # one step per tool call, plus the step that's told the limit is reached, plus its answer
    for _ in range(config.limits.tool_calls_per_turn + 2):
        reply = chat.converse(
            ChatRequest(
                config.models.chat,
                (INSTRUCTIONS, handbook),
                tuple(messages),
                tools,
                config.limits.max_tokens_per_job,
            ),
            lambda piece: emit({"type": "token", "text": piece}),
        )
        tokens_in, tokens_out = tokens_in + reply.input_tokens, tokens_out + reply.output_tokens
        text_parts.append(reply.text)
        if not reply.tool_calls:
            break
        results: list[ToolResult] = []
        for call in reply.tool_calls:
            label = f"{call.name}({', '.join(str(v)[:40] for v in call.input.values())})"
            used.append(label)
            emit({"type": "tool", "text": label})
            if len(used) > config.limits.tool_calls_per_turn:
                results.append(ToolResult(call.id, "tool-call limit reached; answer now", True))
                continue
            before = len(ctx.changesets)
            content, failed = run_tool(ctx, call.name, call.input)
            for cs_id in ctx.changesets[before:]:
                emit({"type": "changeset", "text": cs_id})
            results.append(ToolResult(call.id, content, failed))
        messages += [
            ChatMessage("assistant", reply.text, reply.tool_calls),
            ChatMessage("user", tool_results=tuple(results)),
        ]
    final = "\n\n".join(p.strip() for p in text_parts if p.strip())
    asked = session.with_turn(note, session.YOU, now, question)
    answered = session.with_turn(asked, session.ASSISTANT, now, final, used)
    cited = list(dict.fromkeys(ctx.cited))
    recorded = session.with_meta(
        answered, cited=cited, changesets=ctx.changesets, tokens_in=tokens_in, tokens_out=tokens_out
    )
    store.write_text(recorded.path, recorded.render())
    emit({"type": "done", "text": final, "changesets": list[JsonValue](ctx.changesets)})
    return Answer(recorded.path.as_posix(), final, list(ctx.changesets), cited)
