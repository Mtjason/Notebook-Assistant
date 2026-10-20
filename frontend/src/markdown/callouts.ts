// Obsidian callouts: a blockquote whose first line is `[!type] Title` (`-`/`+` after the type
// folds it). The plugin marks the blockquote so the view renders a titled, coloured box.
import type { Blockquote, Paragraph, Root } from "mdast";
import { visit } from "unist-util-visit";

export interface Callout {
  kind: string;
  title: string;
  folded: boolean;
}

const HEAD = /^\[!([\w-]+)\]([+-]?)[ \t]*(.*)$/;

export function parseCallout(firstLine: string): Callout | null {
  const match = HEAD.exec(firstLine.trim());
  if (!match) return null;
  const kind = (match[1] ?? "note").toLowerCase();
  return { kind, title: match[3]?.trim() || kind[0]?.toUpperCase() + kind.slice(1), folded: match[2] === "-" };
}

export function remarkCallouts() {
  return (tree: Root) => {
    visit(tree, "blockquote", (node: Blockquote) => {
      const first = node.children[0];
      if (first?.type !== "paragraph") return;
      const text = first.children[0];
      if (text?.type !== "text") return;
      const [line = "", ...rest] = text.value.split("\n");
      const callout = parseCallout(line);
      if (callout === null) return;
      // the rest of the first paragraph stays as the callout's body
      const remaining = rest.join("\n");
      if (remaining) text.value = remaining;
      else (first as Paragraph).children.shift();
      if ((first as Paragraph).children.length === 0) node.children.shift();
      node.data = {
        ...node.data,
        hProperties: {
          className: ["callout", `callout-${callout.kind}`],
          "data-callout": callout.kind,
          "data-title": callout.title,
          "data-folded": String(callout.folded),
        },
      };
    });
  };
}
