import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobView, ServiceStatus } from "./api";
import { SettingsScreen } from "./SettingsScreen";
import { onJob } from "./useEvents";

const STATUS: ServiceStatus = {
  version: "0.1", handbook_version: "2.14", machine: "laptop", machine_id: "id-1",
  profile: "linux", watch: "native", vault: "/v",
};
const REPORT = {
  kind: "lint", ran_at: "2026-10-21T09:00:00+08:00", summary: "13 notes, 1 finding(s), 1 fixable",
  rows: [{ path: "60-Knowledge/a.md", label: "tag", detail: "tag 'X' is not in the registry (Handbook §6)" }],
  changesets: ["cs-7"],
};
let posts: { url: string; body: unknown }[] = [];
let ran = false;

beforeEach(() => {
  posts = [];
  ran = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      ran = true;
      return new Response(JSON.stringify({
        id: "job-1", kind: "lint", ref: "maintenance", state: "running", steps: [], message: "", changeset: null,
      }));
    }
    return new Response(JSON.stringify(ran ? { lint: REPORT } : {}));
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("SettingsScreen", () => {
  it("shows this PC and runs a maintenance button as a job, then its report", async () => {
    const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onOpenReview = vi.fn();
    render(<QueryClientProvider client={queries}><SettingsScreen status={STATUS} onOpenReview={onOpenReview} /></QueryClientProvider>);
    expect(screen.getByText("laptop (id-1)")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Lint" }));
    expect(posts).toEqual([{ url: "/api/sweep/run", body: { kind: "lint" } }]);
    const job = (state: JobView["state"]): JobView => ({
      id: "job-1", kind: "lint", ref: "maintenance", state, steps: ["Checking every note"], message: "", changeset: "cs-7",
    });
    act(() => onJob(queries, job("running")));
    expect((await screen.findByText("Checking every note")).className).toBe("run");
    expect((screen.getByRole("button", { name: "Deep pass" }) as HTMLButtonElement).disabled).toBe(true);
    act(() => onJob(queries, job("done")));
    expect(await screen.findByText("13 notes, 1 finding(s), 1 fixable")).toBeTruthy();
    expect(screen.getByText(/not in the registry/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Open 1 proposal(s) in Review" }));
    expect(onOpenReview).toHaveBeenCalledWith("cs-7");
  });

  it("waits for the status", () => {
    const queries = new QueryClient();
    render(<QueryClientProvider client={queries}><SettingsScreen status={undefined} onOpenReview={vi.fn()} /></QueryClientProvider>);
    expect(screen.getByText("Loading…")).toBeTruthy();
  });
});
