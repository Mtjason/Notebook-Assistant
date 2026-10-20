import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";

const STATUS = {
  version: "0.1.0", handbook_version: "2.13", machine: "test-pc", machine_id: "id-1",
  profile: "wsl-drvfs", watch: "polling", vault: "/mnt/c/Vault",
};
const NOTES = [
  { path: "60-Knowledge/Software/Polars with_columns.md", title: "Polars with_columns", type: "knowledge", aliases: [] },
  { path: "60-Knowledge/Software/MOC - Software.md", title: "MOC - Software", type: "moc", aliases: [] },
];
const DETAILS: Record<string, unknown> = {
  "60-Knowledge/Software/Polars with_columns.md": {
    path: NOTES[0]?.path, title: "Polars with_columns", props: { type: "knowledge", aliases: ["cols"] },
    body: "## Summary\n\nSee [[MOC - Software]].", backlinks: ["60-Knowledge/Software/MOC - Software.md"],
  },
  "60-Knowledge/Software/MOC - Software.md": {
    path: NOTES[1]?.path, title: "MOC - Software", props: { type: "moc" }, body: "Index.", backlinks: [],
  },
};

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, () => void> = {};
  closed = false;
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(kind: string, listener: () => void) {
    this.listeners[kind] = listener;
  }
  close() {
    this.closed = true;
  }
}

let counts = { inbox: 2, digest: 5, review: 1 };

beforeEach(() => {
  FakeEventSource.instances = [];
  counts = { inbox: 2, digest: 5, review: 1 };
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const path = decodeURIComponent(input);
    const body =
      path === "/api/status" ? STATUS
      : path === "/api/counts" ? counts
      : path === "/api/notes" ? NOTES
      : DETAILS[path.replace("/api/notes/", "")];
    return body === undefined
      ? new Response("missing", { status: 404, statusText: "Not Found" })
      : new Response(JSON.stringify(body), { status: 200 });
  }));
});

afterEach(() => vi.unstubAllGlobals());

function renderApp() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queries}><App /></QueryClientProvider>);
}

it("shows the PC, live counts, and screens with the branch that builds them", async () => {
  renderApp();
  expect(await screen.findByText("test-pc")).toBeTruthy();
  const nav = screen.getByRole("navigation", { name: "Screens" });
  expect(await within(nav).findByText("5")).toBeTruthy(); // digest queue
  expect(screen.getByText(/arrives with branch 10 feat\/chat/)).toBeTruthy();
  await userEvent.click(within(nav).getByRole("button", { name: /Settings/ }));
  expect(screen.getByText("wsl-drvfs · file changes: polling")).toBeTruthy();
});

it("refetches counts when the service announces a change", async () => {
  renderApp();
  const nav = screen.getByRole("navigation", { name: "Screens" });
  await within(nav).findByText("5");
  counts = { ...counts, digest: 6 };
  FakeEventSource.instances[0]?.listeners["counts"]?.();
  expect(await within(nav).findByText("6")).toBeTruthy();
});

it("Ctrl+K finds a note; the preview follows links and backlinks", async () => {
  renderApp();
  await screen.findByText("test-pc");
  await userEvent.keyboard("{Control>}k{/Control}");
  await userEvent.type(screen.getByRole("textbox", { name: "Search notes" }), "with_col{Enter}");
  const panel = screen.getByRole("complementary", { name: "Context panel" });
  expect(await within(panel).findByRole("heading", { name: "Polars with_columns" })).toBeTruthy();
  expect(within(panel).getByText("type: knowledge · aliases: cols")).toBeTruthy();
  expect(within(panel).getByRole("link", { name: "Open in Obsidian" }).getAttribute("href"))
    .toBe("obsidian://open?vault=Vault&file=60-Knowledge%2FSoftware%2FPolars%20with_columns");
  const [link] = within(panel).getAllByRole("button", { name: "MOC - Software" });
  if (link === undefined) throw new Error("the preview has no link to MOC - Software");
  await userEvent.click(link);
  expect(await within(panel).findByRole("heading", { name: "MOC - Software" })).toBeTruthy();
});

it("says so when the service doesn't answer", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 502, statusText: "Bad Gateway" })));
  renderApp();
  expect(await screen.findByText(/The service isn't answering/)).toBeTruthy();
});
