// The app shell (design.html, UI schematic): top bar, nav rail, main pane, context panel.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import { ChatScreen } from "./ChatScreen";
import { ContextPanel } from "./ContextPanel";
import { DigestScreen } from "./DigestScreen";
import { InboxScreen } from "./InboxScreen";
import { IncubatorScreen } from "./IncubatorScreen";
import { resolveLink } from "./notes";
import { ReviewScreen } from "./ReviewScreen";
import { SCREENS, type ScreenId } from "./screens";
import { SearchPalette } from "./SearchPalette";
import { SessionsScreen } from "./SessionsScreen";
import { SettingsScreen } from "./SettingsScreen";
import { TasksScreen } from "./TasksScreen";
import { useEvents } from "./useEvents";

export function App() {
  useEvents();
  const [screen, setScreen] = useState<ScreenId>("chat");
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const counts = useQuery({ queryKey: ["counts"], queryFn: api.counts, refetchInterval: 60_000 });
  const notes = useQuery({ queryKey: ["notes"], queryFn: api.notes });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearching(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function openLink(target: string) {
    const note = resolveLink(notes.data ?? [], target);
    if (note) setSelected(note.path);
  }

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">
          notebook-<b>assistant</b>
        </span>
        <button type="button" className="search-button" onClick={() => setSearching(true)}>
          Search notes <kbd>Ctrl K</kbd>
        </button>
        <span className="badge" title="This PC">
          {status.data?.machine ?? "…"}
        </span>
      </header>
      <nav className="navrail" aria-label="Screens">
        {SCREENS.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-current={s.id === screen ? "page" : undefined}
            onClick={() => setScreen(s.id)}
          >
            <span>{s.label}</span>
            {s.count && counts.data && <span className="count">{counts.data[s.count]}</span>}
          </button>
        ))}
      </nav>
      <main className="main">
        {status.isError ? (
          <p className="error">The service isn't answering: {status.error.message}</p>
        ) : screen === "settings" ? (
          <SettingsScreen
            status={status.data}
            onOpenReview={(id) => {
              setFocus(id);
              setScreen("review");
            }}
          />
        ) : screen === "inbox" ? (
          <InboxScreen
            onOpenReview={(id) => {
              setFocus(id);
              setScreen("review");
            }}
          />
        ) : screen === "chat" ? (
          <ChatScreen
            notes={notes.data ?? []}
            onOpenLink={openLink}
            onOpenReview={(id) => {
              setFocus(id);
              setScreen("review");
            }}
          />
        ) : screen === "sessions" ? (
          <SessionsScreen onOpenPath={setSelected} />
        ) : screen === "tasks" ? (
          <TasksScreen />
        ) : screen === "incubator" ? (
          <IncubatorScreen
            onOpenReview={(id) => {
              setFocus(id);
              setScreen("review");
            }}
          />
        ) : screen === "digest" ? (
          <DigestScreen onOpenLink={openLink} />
        ) : (
          <ReviewScreen key={focus ?? "list"} onOpenLink={openLink} focus={focus} />
        )}
      </main>
      <ContextPanel
        path={selected}
        vault={status.data?.vault}
        onOpenPath={setSelected}
        onOpenLink={openLink}
      />
      {searching && (
        <SearchPalette
          notes={notes.data ?? []}
          onPick={(note) => {
            setSelected(note.path);
            setSearching(false);
          }}
          onClose={() => setSearching(false)}
        />
      )}
    </div>
  );
}
