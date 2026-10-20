import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobView } from "./api";
import { DigestScreen } from "./DigestScreen";
import { type Jobs, onJob } from "./useEvents";

const STUB = "60-Knowledge/Software/Polars LazyFrame dt error.md";
const item = (state: string) => ({
  path: STUB, title: "Polars LazyFrame dt error", type: "knowledge", state,
  reasons: ["stub", "screenshot-only"], error: null, feedback: null, draft: null, runner: null,
});
let state = "pending";
let posts: { url: string; body: unknown }[] = [];

beforeEach(() => {
  state = "pending";
  posts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ url: decodeURIComponent(url), body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.includes("/approve/")) {
        return new Response(JSON.stringify({ id: "job-1", kind: "digest", ref: STUB, state: "running", steps: [], message: "" }));
      }
      return new Response(JSON.stringify({ ok: true, status: "graduated", problems: [] }));
    }
    if (url === "/api/digest") {
      return new Response(JSON.stringify({
        items: [item(state)], canvases: ["60-Knowledge/Software/Software map.canvas"], kinds: ["collection", "concept"],
      }));
    }
    return new Response(JSON.stringify({
      item: item(state), original: ".dt fails on a LazyFrame\n",
      draft: state === "review" ? "## Symptom\n\nThe draft." : null,
      screenshots: ["Attachments/Polars with_columns - 1.png"],
    }));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderDigest() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queries}><DigestScreen onOpenLink={() => undefined} /></QueryClientProvider>);
  return queries;
}

const job = (steps: string[], jobState: JobView["state"], message = ""): JobView => ({
  id: "job-1", kind: "digest", ref: STUB, state: jobState, steps, message, changeset: null,
});

describe("DigestScreen", () => {
  it("lists the queue by state, with the item's screenshot", async () => {
    renderDigest();
    expect(await screen.findByRole("tab", { name: "Needs digestion 1" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Ready to graduate 0" })).toBeTruthy();
    const img = await screen.findByRole("img", { name: /screenshot 1/ });
    expect(img.getAttribute("src")).toBe("/api/files/Attachments/Polars%20with_columns%20-%201.png");
    expect(screen.getByText("No draft yet. Approve to digest writes one.")).toBeTruthy();
  });

  it("Approve to digest starts a job and shows its steps live", async () => {
    const queries = renderDigest();
    await userEvent.click(await screen.findByRole("button", { name: "Approve to digest" }));
    expect(posts[0]?.url).toBe(`/api/digest/approve/${STUB}`);
    act(() => onJob(queries, job(["Approved on test-pc", "Drafting"], "running")));
    const steps = await screen.findByRole("list", { name: "Progress" });
    expect(within(steps).getByText("Drafting")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Approve to digest" }) as HTMLButtonElement).disabled).toBe(true);
    act(() => onJob(queries, job(["Approved on test-pc"], "failed", "can't reach the Claude API")));
    expect(await screen.findByText("can't reach the Claude API")).toBeTruthy();
  });

  it("a draft is graduated or sent back with feedback", async () => {
    state = "review";
    renderDigest();
    await userEvent.click(await screen.findByRole("tab", { name: "Ready to graduate 1" }));
    expect(await screen.findByText("The draft.")).toBeTruthy();
    await userEvent.type(screen.getByRole("textbox", { name: "Send back with feedback" }), "add the cause");
    await userEvent.click(screen.getByRole("button", { name: "Send back" }));
    expect(posts[0]).toEqual({ url: `/api/digest/send-back/${STUB}`, body: { feedback: "add the cause" } });
    await userEvent.click(screen.getByRole("button", { name: "Approve to graduate" }));
    expect(posts[1]?.url).toBe(`/api/digest/graduate/${STUB}`);
    expect(await screen.findByRole("status")).toBeTruthy();
  });

  it("a canvas graduates as-is with the kind you choose", async () => {
    renderDigest();
    const canvases = await screen.findByRole("list", { name: "Canvases" });
    await userEvent.click(within(canvases).getByRole("button", { name: "Graduate as-is" }));
    const dialog = screen.getByRole("dialog", { name: "Graduate as-is" });
    await userEvent.selectOptions(within(dialog).getByRole("combobox"), "concept");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(posts[0]).toEqual({ url: "/api/graduate/60-Knowledge/Software/Software map.canvas", body: { kind: "concept" } });
  });

  it("a note graduates as-is without a kind", async () => {
    renderDigest();
    const panel = await screen.findByRole("heading", { name: "Polars LazyFrame dt error" });
    const article = panel.closest("article");
    if (article === null) throw new Error("no item panel");
    await userEvent.click(within(article).getByRole("button", { name: "Graduate as-is" }));
    await userEvent.click(within(article).getByRole("button", { name: "Confirm" }));
    expect(posts[0]).toEqual({ url: `/api/graduate/${STUB}`, body: { kind: null } });
  });
});

describe("onJob", () => {
  it("keeps the latest job per note", () => {
    const queries = new QueryClient();
    onJob(queries, job(["a"], "running"));
    onJob(queries, job(["a", "b"], "done"));
    expect(queries.getQueryData<Jobs>(["jobs"])?.[STUB]?.steps).toEqual(["a", "b"]);
  });
});
