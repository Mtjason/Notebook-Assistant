import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IncubatorScreen } from "./IncubatorScreen";
import { TasksScreen } from "./TasksScreen";

const row = (title: string, kind: string, status = "todo") => ({
  path: `10-Tasks/${title}.md`, title, kind, status, priority: "p2", due: null, topic: null,
  waiting_on: null, produced: [], updated: "2026-10-01",
});
const TASKS = {
  views: [
    { name: "Today", groups: [{ label: "Overdue", tasks: [] }] },
    { name: "Next", groups: [{ label: "To do", tasks: [row("Ask Amy", "action"), row("Learn Kedro hooks", "learn")] }] },
  ],
  statuses: ["someday", "todo", "doing", "waiting", "done", "dropped"],
};
const NOTES = [{ path: "60-Knowledge/Software/Kedro hooks.md", title: "Kedro hooks", type: "knowledge", aliases: [] }];
const BOARD = {
  columns: {
    exploring: [{ path: "15-Incubator/Agent.md", title: "Agent", status: "exploring", question: "Can it heal?", next_step: null, updated: "2026-09-01" }],
    shaping: [], promoted: [], parked: [], dropped: [],
  },
};
let posts: { url: string; body: unknown }[] = [];

beforeEach(() => {
  posts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ url: decodeURIComponent(url), body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify({ changeset: "cs-5" }));
    }
    if (url === "/api/views/tasks") return new Response(JSON.stringify(TASKS));
    if (url === "/api/views/incubator") return new Response(JSON.stringify(BOARD));
    return new Response(JSON.stringify(NOTES));
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderWith(ui: React.ReactElement) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queries}>{ui}</QueryClientProvider>);
}

describe("TasksScreen", () => {
  it("shows the views, filters by kind, and changes a status after a one-line confirm", async () => {
    renderWith(<TasksScreen />);
    await userEvent.click(await screen.findByRole("tab", { name: "Next 2" }));
    expect(screen.getByText("Ask Amy")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "learn" }));
    expect(screen.queryByText("Ask Amy")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "all" }));
    await userEvent.click(screen.getByRole("button", { name: "Change status of Ask Amy" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(posts).toEqual([{ url: "/api/status/10-Tasks/Ask Amy.md", body: { status: "done", produced: null } }]);
  });

  it("asks a learn task for what it produced before it can be done", async () => {
    renderWith(<TasksScreen />);
    await userEvent.click(await screen.findByRole("tab", { name: "Next 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Change status of Learn Kedro hooks" }));
    const apply = screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    await userEvent.selectOptions(await screen.findByLabelText("Produced"), "Kedro hooks");
    await userEvent.click(apply);
    expect(posts[0]?.body).toEqual({ status: "done", produced: ["Kedro hooks"] });
  });

  it("says when a view is empty", async () => {
    renderWith(<TasksScreen />);
    expect(await screen.findByText("Nothing in this view.")).toBeTruthy();
  });
});

describe("IncubatorScreen", () => {
  it("moves a card and proposes a promotion, opened on Review", async () => {
    const onOpenReview = vi.fn();
    renderWith(<IncubatorScreen onOpenReview={onOpenReview} />);
    expect(await screen.findByText("Can it heal?")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Park" }));
    expect(posts[0]).toEqual({ url: "/api/status/15-Incubator/Agent.md", body: { status: "parked", produced: null } });
    await userEvent.click(screen.getByRole("button", { name: "Promote" }));
    const input = screen.getByLabelText("Project title");
    await userEvent.clear(input);
    await userEvent.type(input, "Self-healing agent");
    await userEvent.click(screen.getByRole("button", { name: "Propose project" }));
    expect(posts[1]).toEqual({ url: "/api/ideas/promote/15-Incubator/Agent.md", body: { title: "Self-healing agent" } });
    await vi.waitFor(() => expect(onOpenReview).toHaveBeenCalledWith("cs-5"));
  });
});
