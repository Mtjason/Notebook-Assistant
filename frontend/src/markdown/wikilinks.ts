// Obsidian links in Markdown text: [[Target]], [[Target|alias]], [[Target#Heading]] and the
// embed form ![[Target]]. The remark plugin turns each into a link whose URL carries the target
// (`note:` scheme), so the view can resolve it against the vault's notes.
import type { Link, PhrasingContent, Root, Text } from "mdast";
import { visit } from "unist-util-visit";

export interface WikiLink {
  target: string; // the note part, e.g. "Polars with_columns"
  subpath: string; // "#Heading" or "", kept for display
  label: string; // what the reader sees
  embed: boolean;
}

const WIKI = /(!?)\[\[([^[\]\n]+?)\]\]/g;

export function parseWikiLink(inner: string, embed: boolean): WikiLink {
  const [ref = "", alias] = inner.split(/\\?\|/, 2);
  const hash = ref.indexOf("#");
  const target = (hash >= 0 ? ref.slice(0, hash) : ref).trim();
  const subpath = hash >= 0 ? ref.slice(hash) : "";
  const label = (alias ?? (target || subpath.slice(1))).trim();
  return { target, subpath, label, embed };
}

/** Text split into plain pieces and wiki links, in order. */
export function splitWikiLinks(text: string): (string | WikiLink)[] {
  const parts: (string | WikiLink)[] = [];
  let last = 0;
  for (const match of text.matchAll(WIKI)) {
    const index = match.index;
    if (index > last) parts.push(text.slice(last, index));
    parts.push(parseWikiLink(match[2] ?? "", match[1] === "!"));
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export const NOTE_SCHEME = "note:";

export function remarkWikiLinks() {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (parent === undefined || index === undefined || !node.value.includes("[[")) return;
      const pieces = splitWikiLinks(node.value);
      if (pieces.length === 1 && typeof pieces[0] === "string") return;
      const replacement: PhrasingContent[] = pieces.map((piece) =>
        typeof piece === "string"
          ? { type: "text", value: piece }
          : ({
              type: "link",
              url: `${NOTE_SCHEME}${encodeURIComponent(piece.target)}${piece.subpath}`,
              title: piece.embed ? "embed" : null,
              children: [{ type: "text", value: piece.embed ? `⧉ ${piece.label}` : piece.label }],
            } satisfies Link),
      );
      parent.children.splice(index, 1, ...replacement);
      return index + replacement.length;
    });
  };
}
