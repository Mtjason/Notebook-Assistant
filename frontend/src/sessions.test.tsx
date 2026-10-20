import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionsScreen } from "./SessionsScreen";

const SESSION = {
  path: "99-System/Assistant/Sessions/2026/10/ses-1.md", id: "ses-1", title: "Kedro credentials",
  started: "2026-10-20T09:00+08:00", device: "work-pc", changesets: 1, preview: "where do kedro credentials go?",
};
let urls: string[] = [];

beforeEach(() => {
  urls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    const q = new URL(url, "http://x").searchParams.get("q");
    if (q === "nothing") return new Response(JSON.stringify([]));
    return new Response(JSON.stringify([{ session: SESSION, snippet: q ? "kedro **credentials**" : null }]));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderSessions(onOpenPath = vi.fn()) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queries}><SessionsScreen onOpenPath={onOpenPath} /></QueryClientProvider>);
  return onOpenPath;
}

describe("SessionsScreen", () => {
  it("lists sessions and opens one in the preview", async () => {
    const open = renderSessions();
    await userEvent.click(await screen.findByRole("button", { name: /Kedro credentials/ }));
    expect(open).toHaveBeenCalledWith(SESSION.path);
    expect(screen.getByText(/work-pc · 1 changeset/)).toBeTruthy();
  });

  it("searches by word and shows where it matched", async () => {
    renderSessions();
    await userEvent.type(screen.getByLabelText("Search sessions"), "credentials");
    expect(await screen.findByText("credentials", { selector: "b" })).toBeTruthy();
    expect(urls.at(-1)).toBe("/api/sessions?q=credentials");
    await userEvent.clear(screen.getByLabelText("Search sessions"));
    await userEvent.type(screen.getByLabelText("Search sessions"), "nothing");
    expect(await screen.findByText("No session matches.")).toBeTruthy();
  });
});
