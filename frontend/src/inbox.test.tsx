import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobView } from "./api";
import { InboxScreen } from "./InboxScreen";
import { onJob } from "./useEvents";

const PATH = "00-Inbox/2026-10-20 1402.md";
const ITEM = {
  path: PATH, title: "2026-10-20 1402", kind: "image", origin: "own", captured: "2026-10-20",
  preview: "Kedro hooks run before and after each node.", files: ["Attachments/2026-10-20 1402 - 1.png", "Attachments/a.pdf"],
  gap: null,
};
let posts: { url: string; body: BodyInit | null | undefined }[] = [];

beforeEach(() => {
  posts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ url: decodeURIComponent(url), body: init.body });
      if (url === "/api/capture") return new Response(JSON.stringify({ paths: [PATH], changeset: "cs-1" }));
      return new Response(JSON.stringify({
        id: "job-1", kind: "process", ref: PATH, state: "running", steps: [], message: "", changeset: null,
      }));
    }
    return new Response(JSON.stringify({ items: [ITEM], origins: ["ai-chat", "own"], default_origin: "own" }));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderInbox(onOpenReview = vi.fn()) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queries}><InboxScreen onOpenReview={onOpenReview} /></QueryClientProvider>);
  return { queries, onOpenReview };
}

describe("InboxScreen", () => {
  it("lists what waits in the Inbox, with its screenshot and files", async () => {
    renderInbox();
    expect(await screen.findByRole("heading", { name: "2026-10-20 1402" })).toBeTruthy();
    expect(screen.getByText("image · 2 file(s)")).toBeTruthy();
    expect(screen.getByRole("img", { name: /screenshot 1/ }).getAttribute("src")).toBe(
      "/api/files/Attachments/2026-10-20%201402%20-%201.png",
    );
    expect(screen.getByText(/a\.pdf/)).toBeTruthy();
  });

  it("saves a capture as multipart with its origin and files", async () => {
    renderInbox();
    const box = await screen.findByLabelText("Capture text");
    const save = screen.getByRole("button", { name: "Save to Inbox" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(box, "要學 Kedro hooks");
    await userEvent.selectOptions(screen.getByRole("combobox"), "ai-chat");
    const file = new File(["png"], "shot.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Add files"), file);
    expect(screen.getByRole("button", { name: "shot.png ×" })).toBeTruthy();
    await userEvent.click(save);
    const form = posts[0]?.body as FormData;
    expect(posts[0]?.url).toBe("/api/capture");
    expect([form.get("text"), form.get("origin"), (form.get("files") as File).name]).toEqual([
      "要學 Kedro hooks", "ai-chat", "shot.png",
    ]);
    expect(posts).toHaveLength(1);
  });

  it("save and process starts processing what was saved", async () => {
    renderInbox();
    await userEvent.type(await screen.findByLabelText("Capture text"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save and process" }));
    await vi.waitFor(() => expect(posts.map((p) => p.url)).toEqual(["/api/capture", `/api/inbox/process/${PATH}`]));
  });

  it("removes a file before saving", async () => {
    renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add files"), new File(["a"], "a.txt"));
    await userEvent.click(screen.getByRole("button", { name: "a.txt ×" }));
    expect(screen.queryByRole("button", { name: "a.txt ×" })).toBeNull();
  });

  it("processes an item, shows its steps and opens the proposal in Review", async () => {
    const { queries, onOpenReview } = renderInbox();
    await userEvent.click(await screen.findByRole("button", { name: "Process" }));
    await vi.waitFor(() => expect(screen.getByRole("list", { name: "Progress" })).toBeTruthy());
    expect(posts[0]?.url).toBe(`/api/inbox/process/${PATH}`);
    const job = (state: JobView["state"], changeset: string | null, message = ""): JobView => ({
      id: "job-1", kind: "process", ref: PATH, state, steps: ["Reading the capture", "Planning the notes"], message, changeset,
    });
    act(() => onJob(queries, job("running", null)));
    expect((await screen.findByText("Planning the notes")).className).toBe("run");
    act(() => onJob(queries, job("done", "cs-9", "1 note(s) proposed")));
    await userEvent.click(await screen.findByRole("button", { name: "Open in Review" }));
    expect(onOpenReview).toHaveBeenCalledWith("cs-9");
    act(() => onJob(queries, job("failed", null, "can't reach the Claude API")));
    expect(await screen.findByText("can't reach the Claude API")).toBeTruthy();
  });
});
