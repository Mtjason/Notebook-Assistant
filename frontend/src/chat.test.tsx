import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatScreen, message } from "./ChatScreen";
import { onChat } from "./useEvents";

const PATH = "99-System/Assistant/Sessions/2026/10/ses-1.md";
const SUMMARY = { path: PATH, id: "ses-1", title: "columns?", started: "2026-10-21T09:00+00:00", device: "pc", changesets: 0, preview: "" };
const NOTES = [{ path: "60-Knowledge/Software/Polars with_columns.md", title: "Polars with_columns", type: "knowledge", aliases: [] }];
const CS = {
  summary: { id: "cs-1", reason: "Chat: new note Polars select", created_by: "session:ses-1", created: "2026-10-21T09:00:00+00:00", status: "pending", operations: 1, targets: [] },
  operations: [{ index: 0, kind: "create", path: "60-Knowledge/Software/Polars select.md", dest: null, label: "new note", diff: "", before: null, after: "" }],
  checks: [{ name: "links", ok: true, problems: [] }],
  review: "", atoms: [], notes: [],
};
let posts: { url: string; body: unknown }[] = [];
let answered = false;

beforeEach(() => {
  posts = [];
  answered = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = decodeURIComponent(url);
    if (init?.method === "POST") {
      posts.push({ url: u, body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (u === "/api/sessions") return new Response(JSON.stringify(SUMMARY));
      if (u.startsWith("/api/sessions/turn/")) return new Response(JSON.stringify({ id: "job-1", kind: "chat", ref: PATH, state: "running", steps: [], message: "", changeset: null }));
      return new Response(JSON.stringify({ ok: true, status: "applied", problems: [] }));
    }
    if (u.startsWith("/api/sessions/view/")) {
      return new Response(JSON.stringify({
        session: SUMMARY,
        turns: answered
          ? [{ role: "You", time: "09:00", text: "columns?", tools: [] }, { role: "Assistant", time: "09:00", text: "Use [[Polars with_columns]].", tools: ["read_note(Polars with_columns)"] }]
          : [],
        changesets: answered ? ["cs-1"] : [],
      }));
    }
    if (u.startsWith("/api/changesets/")) return new Response(JSON.stringify(CS));
    return new Response(JSON.stringify(answered ? [{ session: SUMMARY, snippet: null }] : []));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderChat() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onOpenLink = vi.fn();
  const onOpenReview = vi.fn();
  render(<QueryClientProvider client={queries}><ChatScreen notes={NOTES} onOpenLink={onOpenLink} onOpenReview={onOpenReview} /></QueryClientProvider>);
  return { queries, onOpenLink, onOpenReview };
}

describe("message", () => {
  it("turns /digest into a request for the extraction planner", () => {
    expect(message("hello")).toBe("hello");
    expect(message("/digest uv installs fast")).toContain("propose_digest");
    expect(message("/digest uv installs fast")).toContain("uv installs fast");
  });
});

describe("ChatScreen", () => {
  it("starts a session, streams the answer, then shows the transcript and the changeset card", async () => {
    const { queries, onOpenLink, onOpenReview } = renderChat();
    await userEvent.type(screen.getByLabelText("Message"), "columns?{Enter}");
    await vi.waitFor(() => expect(posts.map((p) => p.url)).toEqual(["/api/sessions", `/api/sessions/turn/${PATH}`]));
    expect(posts[0]?.body).toEqual({ title: "columns?", scope: "all" });
    act(() => onChat(queries, { type: "tool", text: "read_note(Polars with_columns)", session: PATH }));
    act(() => onChat(queries, { type: "token", text: "Use with_columns", session: PATH }));
    expect(await screen.findByText("Use with_columns")).toBeTruthy();
    expect(screen.getByText(/tools: read_note/)).toBeTruthy();
    answered = true;
    act(() => onChat(queries, { type: "done", text: "", session: PATH, changesets: ["cs-1"] }));
    expect(await screen.findByText("tool trace ▸ 1 call(s)")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Polars with_columns" }));
    expect(onOpenLink).toHaveBeenCalledWith("Polars with_columns");
    expect(await screen.findByText("Chat: new note Polars select")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(posts.at(-1)?.url).toBe("/api/changesets/cs-1/apply");
    await userEvent.click(screen.getByRole("button", { name: "Open in Review" }));
    expect(onOpenReview).toHaveBeenCalledWith("cs-1");
  });

  it("pins a note with @ and shows a failed turn", async () => {
    const { queries } = renderChat();
    await userEvent.type(screen.getByLabelText("Message"), "explain @polars");
    await userEvent.click(screen.getByRole("button", { name: "Polars with_columns" }));
    expect(screen.getByRole("button", { name: "@Polars with_columns ×" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(posts[1]?.body).toEqual({ text: "explain", pinned: ["Polars with_columns"] }));
    act(() => onChat(queries, { type: "error", text: "can't reach the Claude API", session: PATH }));
    expect(await screen.findByText("can't reach the Claude API")).toBeTruthy();
  });
});
