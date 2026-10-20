import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { obsidianLink, type NoteSummary } from "./api";
import { filterNotes, resolveLink } from "./notes";
import { SearchPalette } from "./SearchPalette";

const NOTES: NoteSummary[] = [
  { path: "60-Knowledge/Software/Polars with_columns.md", title: "Polars with_columns", type: "knowledge", aliases: [] },
  { path: "60-Knowledge/Software/Polars LazyFrame dt error.md", title: "Polars LazyFrame dt error", type: "knowledge", aliases: [] },
  { path: "30-SOPs/SOP - Install uv (Linux).md", title: "SOP - Install uv (Linux)", type: "sop", aliases: ["Install uv", "安裝 uv"] },
];

describe("filterNotes", () => {
  it("matches every word in title, alias or path, titles first", () => {
    expect(filterNotes(NOTES, "polars").map((n) => n.title)).toEqual(["Polars LazyFrame dt error", "Polars with_columns"]);
    expect(filterNotes(NOTES, "安裝")[0]?.title).toBe("SOP - Install uv (Linux)");
    expect(filterNotes(NOTES, "sops linux")).toHaveLength(1);
    expect(filterNotes(NOTES, "kedro")).toEqual([]);
    expect(filterNotes(NOTES, "", 2)).toHaveLength(2);
  });
});

describe("resolveLink", () => {
  it("finds by title, alias or path suffix, like Obsidian", () => {
    expect(resolveLink(NOTES, "polars WITH_COLUMNS")?.path).toBe(NOTES[0]?.path);
    expect(resolveLink(NOTES, "Install uv")?.title).toBe("SOP - Install uv (Linux)");
    expect(resolveLink(NOTES, "Software/Polars with_columns.md")?.path).toBe(NOTES[0]?.path);
    expect(resolveLink(NOTES, "missing")).toBeUndefined();
  });
});

describe("obsidianLink", () => {
  it("uses the vault folder's name and the path without .md", () => {
    expect(obsidianLink("/mnt/c/Users/user/Documents/Jason's Vault", "30-SOPs/SOP - Install uv (Linux).md"))
      .toBe("obsidian://open?vault=Jason's%20Vault&file=30-SOPs%2FSOP%20-%20Install%20uv%20(Linux)");
    expect(obsidianLink("C:\\Vaults\\Work", "a.md")).toContain("vault=Work");
  });
});

describe("SearchPalette", () => {
  it("filters as you type and picks with Enter or a click", async () => {
    const pick = vi.fn();
    const close = vi.fn();
    render(<SearchPalette notes={NOTES} onPick={pick} onClose={close} />);
    const input = screen.getByRole("textbox", { name: "Search notes" });
    await userEvent.type(input, "polars{ArrowDown}{Enter}");
    expect(pick).toHaveBeenCalledWith(NOTES[0]);
    await userEvent.clear(input);
    await userEvent.type(input, "zzz");
    expect(screen.getByText("No note matches.")).toBeTruthy();
    await userEvent.type(input, "{Escape}");
    expect(close).toHaveBeenCalled();
  });
});
