import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { diffRows } from "./DiffView";
import { ReviewScreen } from "./ReviewScreen";

describe("diffRows", () => {
  it("pairs replaced lines and keeps unchanged ones", () => {
    expect(diffRows("a\nb\nc\n", "a\nB\nc\nd\n")).toEqual([
      { left: "a", right: "a", changed: false },
      { left: "b", right: "B", changed: true },
      { left: "c", right: "c", changed: false },
      { left: null, right: "d", changed: true },
    ]);
    expect(diffRows("", "new\n")).toEqual([{ left: null, right: "new", changed: true }]);
  });
});

const PENDING = {
  id: "cs-1", reason: "Digest uv answer", created_by: "user:cli", created: "2026-10-20T08:00:00+08:00",
  status: "pending", operations: 2,
};
const DETAIL = {
  summary: PENDING, error: null, review: "### Split map",
  operations: [
    { index: 0, kind: "write", path: "30-SOPs/SOP.md", dest: null, label: "add to note", before: "1. one\n", after: "1. one\n2. two\n" },
    { index: 1, kind: "create", path: "60-Knowledge/Systems/curl.md", dest: null, label: "new note", before: null, after: "## Summary\n" },
  ],
  checks: [
    { name: "nothing lost", ok: true, detail: "checked when the capture was planned" },
    { name: "links", ok: false, detail: "would break links" },
  ],
  atoms: [{ id: "zsh", role: "principle", notes: ["curl"], text: "source ~/.zshrc" }],
  planned_notes: ["SOP", "curl"],
};

let posts: { url: string; body: unknown; headers: HeadersInit | undefined }[] = [];
let detail: unknown = DETAIL;

beforeEach(() => {
  posts = [];
  detail = DETAIL;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: init.headers });
      const ok = !url.endsWith("/atoms/zsh");
      return new Response(JSON.stringify({ ok, status: ok ? "applied" : "pending", problems: ok ? [] : ["SOP doesn't link to curl"] }));
    }
    if (url === "/api/changesets") return new Response(JSON.stringify([PENDING]));
    if (url === "/api/changesets?status=history") return new Response(JSON.stringify([]));
    return new Response(JSON.stringify(detail));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderReview() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queries}><ReviewScreen onOpenLink={() => undefined} /></QueryClientProvider>);
}

describe("ReviewScreen", () => {
  it("shows the changeset, its checks and the first operation's diff", async () => {
    renderReview();
    expect(await screen.findByRole("heading", { name: "Digest uv answer" })).toBeTruthy();
    const checks = screen.getByRole("list", { name: "Checks" });
    expect(within(checks).getByText(/✗ links/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Before and after" }).textContent).toContain("2. two");
    await userEvent.click(screen.getByRole("button", { name: /create 60-Knowledge/ }));
    expect(screen.getByRole("columnheader", { name: "new file" })).toBeTruthy();
  });

  it("applies only the ticked operations, with the client header", async () => {
    renderReview();
    await screen.findByRole("heading", { name: "Digest uv answer" });
    await userEvent.click(screen.getByRole("checkbox", { name: /Apply create/ }));
    await userEvent.click(screen.getByRole("button", { name: "Apply 1 selected" }));
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(posts[0]).toMatchObject({ url: "/api/changesets/cs-1/apply", body: { ops: [0] } });
    expect(posts[0]?.headers).toMatchObject({ "X-Requested-With": "notebook-assistant" });
  });

  it("moving an atom the checks refuse shows why", async () => {
    renderReview();
    await screen.findByRole("heading", { name: "Digest uv answer" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Where atom zsh lands" }), "SOP");
    expect((await screen.findByRole("status")).textContent).toContain("SOP doesn't link to curl");
    expect(posts[0]).toMatchObject({ url: "/api/changesets/cs-1/atoms/zsh", body: { note: "SOP" } });
  });

  it("rejects a pending changeset", async () => {
    renderReview();
    await screen.findByRole("heading", { name: "Digest uv answer" });
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(posts[0]?.url).toBe("/api/changesets/cs-1/reject");
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("Nothing applied or rejected yet.")).toBeTruthy();
  });

  it("an applied changeset has no checkboxes or Apply, only Undo", async () => {
    detail = { ...DETAIL, checks: [], summary: { ...PENDING, status: "applied" } };
    renderReview();
    await screen.findByRole("heading", { name: "Digest uv answer" });
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Apply/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(posts[0]?.url).toBe("/api/changesets/cs-1/revert");
  });
});
