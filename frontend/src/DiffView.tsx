// Side-by-side diff of one operation (design.html, Review: DiffView): lines first, then the
// words that changed inside a changed line.
import { diffLines, diffWordsWithSpace } from "diff";

export interface Row {
  left: string | null; // null: nothing on this side (an added or removed line)
  right: string | null;
  changed: boolean;
}

/** Rows of a side-by-side view: removed lines pair with the added lines that replace them. */
export function diffRows(before: string, after: string): Row[] {
  const rows: Row[] = [];
  let removed: string[] = [];
  const flush = (added: string[]) => {
    const n = Math.max(removed.length, added.length);
    for (let i = 0; i < n; i++) {
      rows.push({ left: removed[i] ?? null, right: added[i] ?? null, changed: true });
    }
    removed = [];
  };
  for (const part of diffLines(before, after)) {
    const lines = part.value.replace(/\n$/, "").split("\n");
    if (part.removed) {
      removed.push(...lines);
    } else if (part.added) {
      flush(lines);
    } else {
      flush([]);
      for (const line of lines) rows.push({ left: line, right: line, changed: false });
    }
  }
  flush([]);
  return rows;
}

function Words({ text, other, side }: { text: string; other: string | null; side: "left" | "right" }) {
  if (other === null) return <>{text}</>;
  const parts = side === "left" ? diffWordsWithSpace(text, other) : diffWordsWithSpace(other, text);
  return (
    <>
      {parts
        .filter((p) => (side === "left" ? !p.added : !p.removed))
        .map((p, i) =>
          p.added || p.removed ? (
            <mark key={i} className={side === "left" ? "del" : "ins"}>
              {p.value}
            </mark>
          ) : (
            <span key={i}>{p.value}</span>
          ),
        )}
    </>
  );
}

export function DiffView({ before, after }: { before: string | null; after: string | null }) {
  const rows = diffRows(before ?? "", after ?? "");
  return (
    <div className="diff" role="table" aria-label="Before and after">
      <div className="diff-head" role="row">
        <span role="columnheader">{before === null ? "new file" : "before"}</span>
        <span role="columnheader">{after === null ? "deleted" : "after"}</span>
      </div>
      {rows.map((row, i) => (
        <div key={i} role="row" className={row.changed ? "diff-row changed" : "diff-row"}>
          <code role="cell" className={row.left === null ? "side empty" : row.changed ? "side old" : "side"}>
            {row.left !== null && <Words text={row.left} other={row.changed ? row.right : null} side="left" />}
          </code>
          <code role="cell" className={row.right === null ? "side empty" : row.changed ? "side new" : "side"}>
            {row.right !== null && <Words text={row.right} other={row.changed ? row.left : null} side="right" />}
          </code>
        </div>
      ))}
    </div>
  );
}
