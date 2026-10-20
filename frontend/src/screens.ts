// The eight screens of the nav rail (design.html, UI schematic) and the branch that builds each
// (architecture.md §5.4.1). Until then a screen says where it's coming from.
export type ScreenId =
  | "chat" | "inbox" | "digest" | "review" | "incubator" | "tasks" | "sessions" | "settings";

export interface Screen {
  id: ScreenId;
  label: string;
  branch: string; // the feature branch that delivers it
  count?: "inbox" | "digest" | "review"; // a live count from /api/counts
}

export const SCREENS: Screen[] = [
  { id: "chat", label: "Chat", branch: "10 feat/chat" },
  { id: "inbox", label: "Inbox", branch: "6 feat/capture", count: "inbox" },
  { id: "digest", label: "Digest", branch: "5 feat/digest", count: "digest" },
  { id: "review", label: "Review", branch: "4 feat/review", count: "review" },
  { id: "incubator", label: "Incubator", branch: "8 feat/views" },
  { id: "tasks", label: "Tasks", branch: "8 feat/views" },
  { id: "sessions", label: "Sessions", branch: "9 feat/search" },
  { id: "settings", label: "Settings", branch: "3 feat/service-shell" },
];
