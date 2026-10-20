// ⌘K / Ctrl+K: find a note by title, alias or path and preview it (design.html, Top bar).
// Full-text and session search arrive with the search index (architecture.md §5.4.1, branch 9).
import { useEffect, useMemo, useRef, useState } from "react";
import type { NoteSummary } from "./api";
import { filterNotes } from "./notes";

interface Props {
  notes: NoteSummary[];
  onPick: (note: NoteSummary) => void;
  onClose: () => void;
}

export function SearchPalette({ notes, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const found = useMemo(() => filterNotes(notes, query, 20), [notes, query]);

  useEffect(() => input.current?.focus(), []);

  function onKey(event: React.KeyboardEvent) {
    if (event.key === "Escape") onClose();
    else if (event.key === "ArrowDown") setActive((i) => Math.min(i + 1, found.length - 1));
    else if (event.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
    else if (event.key === "Enter" && found[active]) onPick(found[active]);
    else return;
    event.preventDefault();
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" role="dialog" aria-label="Search notes" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={query}
          placeholder="Search notes by title, alias or path…"
          aria-label="Search notes"
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
        />
        <ul role="listbox" aria-label="Matching notes">
          {found.map((note, i) => (
            <li key={note.path} role="option" aria-selected={i === active}>
              <button type="button" onMouseEnter={() => setActive(i)} onClick={() => onPick(note)}>
                <span className="palette-title">{note.title}</span>
                <span className="palette-path">{note.path}</span>
              </button>
            </li>
          ))}
          {found.length === 0 && <li className="palette-empty">No note matches.</li>}
        </ul>
      </div>
    </div>
  );
}
