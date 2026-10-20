import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { noteTarget, safeUrl, MarkdownView } from "./MarkdownView";
import { parseCallout } from "./markdown/callouts";
import { parseWikiLink, splitWikiLinks } from "./markdown/wikilinks";

describe("wiki links", () => {
  it("parses every form", () => {
    expect(parseWikiLink("Polars with_columns", false)).toEqual({
      target: "Polars with_columns", subpath: "", label: "Polars with_columns", embed: false,
    });
    expect(parseWikiLink("Polars with_columns#Chaining|chaining", false)).toMatchObject({
      target: "Polars with_columns", subpath: "#Chaining", label: "chaining",
    });
    expect(parseWikiLink("60-Knowledge/Software/Polars with_columns\\|with_columns", false))
      .toMatchObject({ target: "60-Knowledge/Software/Polars with_columns", label: "with_columns" });
    expect(parseWikiLink("#Local", false)).toMatchObject({ target: "", label: "Local" });
  });

  it("splits text around links and embeds", () => {
    const parts = splitWikiLinks("See [[A]] and ![[img.png]].");
    expect(parts).toHaveLength(5);
    expect(parts[1]).toMatchObject({ target: "A", embed: false });
    expect(parts[3]).toMatchObject({ target: "img.png", embed: true });
    expect(splitWikiLinks("no links")).toEqual(["no links"]);
  });

  it("note links pass the URL filter, javascript: doesn't", () => {
    expect(safeUrl("note:A")).toBe("note:A");
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(noteTarget("note:Polars%20with_columns#Chaining")).toBe("Polars with_columns");
    expect(noteTarget("https://example.com")).toBeNull();
  });
});

describe("callouts", () => {
  it("reads the type, title and fold marker", () => {
    expect(parseCallout("[!warning] Conflict")).toEqual({ kind: "warning", title: "Conflict", folded: false });
    expect(parseCallout("[!quote]- Original capture")).toMatchObject({ kind: "quote", folded: true });
    expect(parseCallout("[!TIP]")).toEqual({ kind: "tip", title: "Tip", folded: false });
    expect(parseCallout("plain quote")).toBeNull();
  });
});

describe("MarkdownView", () => {
  it("renders wiki links as buttons that open the note", async () => {
    const open = vi.fn();
    render(<MarkdownView text={"See [[Polars with_columns|with_columns]] and `[[not a link]]`."} onOpenNote={open} />);
    await userEvent.click(screen.getByRole("button", { name: "with_columns" }));
    expect(open).toHaveBeenCalledWith("Polars with_columns");
    expect(screen.getByText("[[not a link]]")).toBeTruthy(); // code is left alone
  });

  it("renders callouts, folded ones as details, tables and math", () => {
    const { container } = render(
      <MarkdownView
        onOpenNote={() => undefined}
        text={"> [!warning] Conflict\n> Two versions.\n\n> [!quote]- Original\n> raw\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n$x^2$"}
      />,
    );
    expect(container.querySelector(".callout-warning .callout-title")?.textContent).toBe("Conflict");
    expect(container.querySelector("details.callout-quote summary")?.textContent).toBe("Original");
    expect(container.querySelector("table")).toBeTruthy();
    expect(container.querySelector(".katex")).toBeTruthy();
  });

  it("opens external links in a new tab and drops javascript: links", () => {
    render(<MarkdownView onOpenNote={() => undefined} text={"[docs](https://docs.kedro.org) [x](javascript:alert(1))"} />);
    expect(screen.getByRole("link", { name: "docs" }).getAttribute("target")).toBe("_blank");
    expect(screen.getByText("x").closest("a")?.getAttribute("href") ?? "").toBe("");
  });
});
