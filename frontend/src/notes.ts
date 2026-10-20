// Finding notes by what a reader types or what a link says, against the vault's note list.
import type { NoteSummary } from "./api";

const key = (text: string) => text.normalize("NFC").toLocaleLowerCase();

/** Notes whose title, alias or path contains every word of the query (titles first). */
export function filterNotes(notes: NoteSummary[], query: string, limit = 50): NoteSummary[] {
  const words = key(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return notes.slice(0, limit);
  const scored: [number, NoteSummary][] = [];
  for (const note of notes) {
    const title = key(note.title);
    const haystack = [title, ...note.aliases.map(key), key(note.path)].join("\n");
    if (words.every((w) => haystack.includes(w))) {
      const rank = title.startsWith(words[0] ?? "") ? 0 : words.every((w) => title.includes(w)) ? 1 : 2;
      scored.push([rank, note]);
    }
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].title.localeCompare(b[1].title));
  return scored.slice(0, limit).map(([, note]) => note);
}

/** The note a wiki link points to, like Obsidian: a path (suffix) or a title, then an alias. */
export function resolveLink(notes: NoteSummary[], target: string): NoteSummary | undefined {
  const wanted = key(target.replace(/\.md$/i, ""));
  if (wanted.includes("/")) {
    return notes.find((n) => key(n.path.replace(/\.md$/i, "")).endsWith(wanted));
  }
  return (
    notes.find((n) => key(n.title) === wanted) ??
    notes.find((n) => n.aliases.some((a) => key(a) === wanted))
  );
}
