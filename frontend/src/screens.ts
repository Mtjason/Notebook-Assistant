// The eight screens of the nav rail (design.html, UI schematic).
export type ScreenId =
  | "chat" | "inbox" | "digest" | "review" | "incubator" | "tasks" | "sessions" | "settings";

export interface Screen {
  id: ScreenId;
  label: string;
  count?: "inbox" | "digest" | "review"; // a live count from /api/counts
}

export const SCREENS: Screen[] = [
  { id: "chat", label: "Chat" },
  { id: "inbox", label: "Inbox", count: "inbox" },
  { id: "digest", label: "Digest", count: "digest" },
  { id: "review", label: "Review", count: "review" },
  { id: "incubator", label: "Incubator" },
  { id: "tasks", label: "Tasks" },
  { id: "sessions", label: "Sessions" },
  { id: "settings", label: "Settings" },
];
