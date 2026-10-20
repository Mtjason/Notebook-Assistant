// ⌘K / Ctrl+K: find a note by title, alias or path at once, and by its text through this PC's
// search index (design.html, Top bar; architecture.md §4.2). Picking one previews it.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type NoteSummary } from "./api";
import { filterNotes } from "./notes";
import { Snippet } from "./Snippet";

interface Props {
  notes: NoteSummary[];
  onPick: (note: NoteSummary) => void;
  onClose: () => void;
}

const DEBOUNCE_MS = 250; // wait for a pause in typing before asking the index

interface Choice {
  note: NoteSummary;
  snippet: string | null;
}

export function SearchPalette({ notes, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [settled, setSettled] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const byTitle = useMemo(() => filterNotes(notes, query, 20), [notes, query]);
  const text = useQuery({
    queryKey: ["search", settled],
    queryFn: () => api.search(settled),
    enabled: settled.trim().length >= 2,
  });

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(query), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const choices: Choice[] = useMemo(() => {
    const seen = new Set(byTitle.map((n) => n.path));
    const hits = (settled === query ? text.data ?? [] : [])
      .filter((h) => !seen.has(h.path))
      .map((h) => ({ note: { path: h.path, title: h.title, type: null, aliases: [] }, snippet: h.snippet }));
    return [...byTitle.map((note) => ({ note, snippet: null })), ...hits];
  }, [byTitle, text.data, settled, query]);

  function onKey(event: React.KeyboardEvent) {
    if (event.key === "Escape") onClose();
    else if (event.key === "ArrowDown") setActive((i) => Math.min(i + 1, choices.length - 1));
    else if (event.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
    else if (event.key === "Enter" && choices[active]) onPick(choices[active].note);
    else return;
    event.preventDefault();
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" role="dialog" aria-label="Search notes" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={query}
          placeholder="Search notes by title, alias, path or text…"
          aria-label="Search notes"
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
        />
        <ul role="listbox" aria-label="Matching notes">
          {choices.map((choice, i) => (
            <li key={choice.note.path} role="option" aria-selected={i === active}>
              <button type="button" onMouseEnter={() => setActive(i)} onClick={() => onPick(choice.note)}>
                <span className="palette-title">{choice.note.title}</span>
                <span className="palette-path">{choice.note.path}</span>
                {choice.snippet && <Snippet text={choice.snippet} />}
              </button>
            </li>
          ))}
          {choices.length === 0 && <li className="palette-empty">No note matches.</li>}
        </ul>
      </div>
    </div>
  );
}
