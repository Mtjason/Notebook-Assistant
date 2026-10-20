// Every note renders the same way everywhere (design.html, Main pane): Obsidian wiki links and
// embeds, callouts, tables, task lists and math. A note link opens that note in the preview.
import "katex/dist/katex.min.css";
import type { ReactNode } from "react";
import Markdown, { type Components, defaultUrlTransform } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { remarkCallouts } from "./markdown/callouts";
import { NOTE_SCHEME, remarkWikiLinks } from "./markdown/wikilinks";

interface Props {
  text: string;
  onOpenNote: (target: string) => void;
}

/** Note links pass; everything else gets react-markdown's sanitizing (no `javascript:`). */
export function safeUrl(url: string): string {
  return url.startsWith(NOTE_SCHEME) ? url : defaultUrlTransform(url);
}

export function noteTarget(href: string | undefined): string | null {
  if (!href?.startsWith(NOTE_SCHEME)) return null;
  const rest = href.slice(NOTE_SCHEME.length);
  const hash = rest.indexOf("#");
  return decodeURIComponent(hash >= 0 ? rest.slice(0, hash) : rest);
}

export function MarkdownView({ text, onOpenNote }: Props) {
  const components: Components = {
    a({ href, children, title }) {
      const target = noteTarget(href);
      if (target === null) {
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      }
      return (
        <button
          type="button"
          className={title === "embed" ? "wikilink embed" : "wikilink"}
          onClick={() => target && onOpenNote(target)}
        >
          {children}
        </button>
      );
    },
    blockquote(props) {
      const { children } = props;
      const attrs = props as Record<string, unknown>; // remarkCallouts' data-* attributes
      const kind = attrs["data-callout"];
      if (typeof kind !== "string") return <blockquote>{children}</blockquote>;
      const title = String(attrs["data-title"] ?? kind);
      const body: ReactNode = <div className="callout-body">{children}</div>;
      return attrs["data-folded"] === "true" ? (
        <details className={`callout callout-${kind}`}>
          <summary className="callout-title">{title}</summary>
          {body}
        </details>
      ) : (
        <div className={`callout callout-${kind}`}>
          <div className="callout-title">{title}</div>
          {body}
        </div>
      );
    },
  };
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm, remarkMath, remarkWikiLinks, remarkCallouts]}
        rehypePlugins={[rehypeKatex]}
        components={components}
        urlTransform={safeUrl}
      >
        {text}
      </Markdown>
    </div>
  );
}
