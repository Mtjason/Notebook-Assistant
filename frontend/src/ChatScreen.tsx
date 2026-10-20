// The Chat screen (design.html, Chat; architecture.md §2.2): questions answered from your notes
// with citations, and changes asked for in words, which come back as changeset cards to apply or
// reject. The answer streams in as `chat` events; the session is a note, so the transcript is
// read back from the vault and either PC can continue it.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type NoteSummary, type SessionTurn } from "./api";
import { MarkdownView } from "./MarkdownView";
import { filterNotes } from "./notes";
import { type ChatLive, useChatLive } from "./useEvents";

interface Props {
  notes: NoteSummary[];
  onOpenLink: (target: string) => void;
  onOpenReview: (id: string) => void;
}

const SCOPES = ["all", "personal", "work"] as const;
const DIGEST = "/digest";

/** What the composer sends: `/digest <text>` asks for the extraction planner (Handbook §19.6). */
export function message(text: string): string {
  if (!text.startsWith(DIGEST)) return text;
  const material = text.slice(DIGEST.length).trim();
  return `Digest this with propose_digest (origin ai-chat if it is an AI answer, else own):\n\n${material}`;
}

function ChangesetCard({ id, onOpenReview }: { id: string; onOpenReview: (id: string) => void }) {
  const queries = useQueryClient();
  const detail = useQuery({ queryKey: ["changeset", id], queryFn: () => api.changeset(id) });
  const done = () => {
    void queries.invalidateQueries({ queryKey: ["changeset", id] });
    void queries.invalidateQueries({ queryKey: ["counts"] });
  };
  const apply = useMutation({ mutationFn: () => api.apply(id, null), onSuccess: done });
  const reject = useMutation({ mutationFn: () => api.reject(id), onSuccess: done });
  if (!detail.data) return <div className="cs-card muted">Changeset {id}…</div>;
  const cs = detail.data;
  const pending = cs.summary.status === "pending";
  const failed = cs.checks.filter((c) => !c.ok);
  return (
    <div className="cs-card" aria-label={`Changeset ${id}`}>
      <strong>{cs.summary.reason}</strong>
      <ul>
        {cs.operations.map((op) => (
          <li key={op.index} className="mono">
            {op.kind} {op.path}
            {op.dest ? ` → ${op.dest}` : ""}
          </li>
        ))}
      </ul>
      <p className="muted">
        {cs.summary.status} · {failed.length ? `checks: ${failed.map((c) => c.name).join(", ")} failing` : "checks ✓"}
      </p>
      {(apply.data ?? reject.data)?.problems.map((p) => (
        <p key={p} className="error">{p}</p>
      ))}
      <div className="actions">
        {pending && (
          <>
            <button type="button" className="btn primary" disabled={apply.isPending} onClick={() => apply.mutate()}>
              Apply
            </button>
            <button type="button" className="btn" disabled={reject.isPending} onClick={() => reject.mutate()}>
              Reject
            </button>
          </>
        )}
        <button type="button" className="btn" onClick={() => onOpenReview(id)}>
          Open in Review
        </button>
      </div>
    </div>
  );
}

function Turn({ turn, onOpenLink }: { turn: SessionTurn; onOpenLink: (t: string) => void }) {
  const you = turn.role === "You";
  return (
    <div className={you ? "turn you" : "turn assistant"}>
      <span className="muted">
        {turn.role} · {turn.time}
      </span>
      {turn.tools.length > 0 && (
        <details className="tool-trace">
          <summary>tool trace ▸ {turn.tools.length} call(s)</summary>
          <ul>
            {turn.tools.map((t, i) => (
              <li key={i} className="mono">
                {t}
              </li>
            ))}
          </ul>
        </details>
      )}
      {you ? <p className="you-text">{turn.text}</p> : <MarkdownView text={turn.text} onOpenNote={onOpenLink} />}
    </div>
  );
}

function Live({ live, onOpenLink }: { live: ChatLive; onOpenLink: (t: string) => void }) {
  return (
    <div className="turn assistant live" aria-live="polite">
      <span className="muted">Assistant · writing…</span>
      {live.tools.length > 0 && <p className="muted mono">tools: {live.tools.join(" → ")}</p>}
      <MarkdownView text={live.text || "…"} onOpenNote={onOpenLink} />
      {live.error && <p className="error">{live.error}</p>}
    </div>
  );
}

function Composer({
  notes,
  disabled,
  onSend,
}: {
  notes: NoteSummary[];
  disabled: boolean;
  onSend: (text: string, pinned: string[]) => void;
}) {
  const [text, setText] = useState("");
  const [pinned, setPinned] = useState<string[]>([]);
  const mention = /@([^\s@]*)$/.exec(text)?.[1];
  const suggestions = useMemo(() => (mention === undefined ? [] : filterNotes(notes, mention, 6)), [notes, mention]);

  function send() {
    if (!text.trim() || disabled) return;
    onSend(message(text.trim()), pinned);
    setText("");
    setPinned([]);
  }

  return (
    <div className="composer">
      {pinned.length > 0 && (
        <div className="pins">
          {pinned.map((p) => (
            <button key={p} type="button" className="chip" onClick={() => setPinned(pinned.filter((x) => x !== p))}>
              @{p} ×
            </button>
          ))}
        </div>
      )}
      {suggestions.length > 0 && (
        <ul className="mentions" role="listbox" aria-label="Pin a note">
          {suggestions.map((n) => (
            <li key={n.path}>
              <button
                type="button"
                onClick={() => {
                  setPinned([...new Set([...pinned, n.title])]);
                  setText(text.replace(/@[^\s@]*$/, ""));
                }}
              >
                {n.title}
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        aria-label="Message"
        rows={3}
        placeholder="Ask about your notes, or ask for a change. @ pins a note, /digest digests pasted material."
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      <button type="button" className="btn primary" disabled={disabled || !text.trim()} onClick={send}>
        Send
      </button>
    </div>
  );
}

export function ChatScreen({ notes, onOpenLink, onOpenReview }: Props) {
  const queries = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions", ""], queryFn: () => api.sessions("") });
  const [current, setCurrent] = useState<string | null>(null);
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("all");
  const transcript = useQuery({
    queryKey: ["transcript", current],
    queryFn: () => api.transcript(current ?? ""),
    enabled: current !== null,
  });
  const live = useChatLive(current);
  const [error, setError] = useState<string | null>(null);
  const send = useMutation({
    mutationFn: async ({ text, pinned }: { text: string; pinned: string[] }) => {
      const path = current ?? (await api.newSession(text.slice(0, 60), scope)).path;
      setCurrent(path);
      queries.setQueryData<ChatLive>(["chat-live", path], { text: "", tools: [], changesets: [], error: null, running: true });
      await api.ask(path, text, pinned);
      return path;
    },
    onSuccess: () => {
      setError(null);
      void queries.invalidateQueries({ queryKey: ["sessions"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const proposed = [...new Set([...(transcript.data?.changesets ?? []), ...(live?.changesets ?? [])])];

  return (
    <section className="chat">
      <aside className="chat-sessions">
        <div className="actions">
          <button type="button" className="btn" onClick={() => setCurrent(null)}>
            New chat
          </button>
          <select aria-label="Scope" value={scope} disabled={current !== null} onChange={(e) => setScope(e.target.value as (typeof SCOPES)[number])}>
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <ul className="cs-list" aria-label="Chats">
          {sessions.data?.map(({ session }) => (
            <li key={session.path}>
              <button type="button" aria-current={session.path === current} onClick={() => setCurrent(session.path)}>
                <span className="cs-reason">{session.title}</span>
                <span className="muted">{session.started?.slice(0, 16).replace("T", " ")}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="chat-main">
        {current === null && <p className="muted">Ask anything about your notes. Answers cite the notes they come from.</p>}
        {transcript.data?.turns.map((t, i) => (
          <Turn key={i} turn={t} onOpenLink={onOpenLink} />
        ))}
        {live?.running && <Live live={live} onOpenLink={onOpenLink} />}
        {live?.error && !live.running && <p className="error">{live.error}</p>}
        {proposed.length > 0 && (
          <div className="cards">
            {proposed.map((id) => (
              <ChangesetCard key={id} id={id} onOpenReview={onOpenReview} />
            ))}
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <Composer notes={notes} disabled={send.isPending || Boolean(live?.running)} onSend={(text, pinned) => send.mutate({ text, pinned })} />
      </div>
    </section>
  );
}
