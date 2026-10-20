// The context panel (design.html, region 4): a preview of the selected note, its backlinks, and
// Open in Obsidian, without leaving the app.
import { useQuery } from "@tanstack/react-query";
import { api, obsidianLink } from "./api";
import { MarkdownView } from "./MarkdownView";

interface Props {
  path: string | null;
  vault: string | undefined;
  onOpenPath: (path: string) => void;
  onOpenLink: (target: string) => void;
}

function formatProps(props: Record<string, unknown>): string {
  return Object.entries(props)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join(" · ");
}

export function ContextPanel({ path, vault, onOpenPath, onOpenLink }: Props) {
  const note = useQuery({
    queryKey: ["note", path],
    queryFn: () => api.note(path ?? ""),
    enabled: path !== null,
  });
  if (path === null) {
    return (
      <aside className="ctx" aria-label="Context panel">
        <p className="muted">Press Ctrl+K (⌘K) to find a note and preview it here.</p>
      </aside>
    );
  }
  return (
    <aside className="ctx" aria-label="Context panel">
      {note.isPending && <p className="muted">Loading…</p>}
      {note.isError && <p className="error">Couldn't load {path}: {note.error.message}</p>}
      {note.data && (
        <article className="preview">
          <h2>{note.data.title}</h2>
          <p className="props">{formatProps(note.data.props)}</p>
          <MarkdownView text={note.data.body} onOpenNote={onOpenLink} />
          {vault && (
            <a className="btn" href={obsidianLink(vault, note.data.path)}>
              Open in Obsidian
            </a>
          )}
          {note.data.backlinks.length > 0 && (
            <>
              <h3>Linked from</h3>
              <ul className="backlinks">
                {note.data.backlinks.map((source) => (
                  <li key={source}>
                    <button type="button" className="wikilink" onClick={() => onOpenPath(source)}>
                      {source.split("/").pop()?.replace(/\.md$/, "")}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </article>
      )}
    </aside>
  );
}
