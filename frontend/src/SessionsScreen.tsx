// The Sessions screen (design.html, Sessions): every past chat, newest first, searchable by word
// through this PC's index (Chinese split by jieba). A session is a note, so opening one previews
// it; continuing it arrives with Chat (architecture.md §5.4.1, branch 10).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import { Snippet } from "./Snippet";

const DEBOUNCE_MS = 250;

export function SessionsScreen({ onOpenPath }: { onOpenPath: (path: string) => void }) {
  const [query, setQuery] = useState("");
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSettled(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);
  const rows = useQuery({ queryKey: ["sessions", settled], queryFn: () => api.sessions(settled) });

  return (
    <section className="sessions">
      <input
        className="session-search"
        aria-label="Search sessions"
        placeholder="Search past conversations…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {rows.isError && <p className="error">{rows.error.message}</p>}
      <ul className="cs-list" aria-label="Sessions">
        {rows.data?.map(({ session, snippet }) => (
          <li key={session.path}>
            <button type="button" onClick={() => onOpenPath(session.path)}>
              <span className="cs-reason">{session.title}</span>
              <span className="muted">
                {session.started?.slice(0, 16).replace("T", " ") ?? "—"}
                {session.device ? ` · ${session.device}` : ""}
                {session.changesets ? ` · ${session.changesets} changeset(s)` : ""}
              </span>
              {snippet ? <Snippet text={snippet} /> : <span className="muted">{session.preview}</span>}
            </button>
          </li>
        ))}
        {rows.data?.length === 0 && (
          <li className="muted">{settled ? "No session matches." : "No sessions yet. Chat saves each one here."}</li>
        )}
      </ul>
      <p className="muted">Old sessions are removed in an approved batch: Handbook §8.4.</p>
    </section>
  );
}
