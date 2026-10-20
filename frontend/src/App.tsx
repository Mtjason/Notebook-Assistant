// The app shell (design.html, UI schematic): top bar, nav rail, main pane, context panel.
// Screens arrive branch by branch; the shell, search palette and note preview work now.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type ServiceStatus } from "./api";
import { ContextPanel } from "./ContextPanel";
import { resolveLink } from "./notes";
import { ReviewScreen } from "./ReviewScreen";
import { SCREENS, type Screen, type ScreenId } from "./screens";
import { SearchPalette } from "./SearchPalette";
import { useEvents } from "./useEvents";

function SettingsScreen({ status }: { status: ServiceStatus | undefined }) {
  if (!status) return <p className="muted">Loading…</p>;
  const rows: [string, string][] = [
    ["Machine", `${status.machine} (${status.machine_id})`],
    ["Profile", `${status.profile} · file changes: ${status.watch}`],
    ["Vault", status.vault],
    ["Version", `${status.version} · handbook ${status.handbook_version}`],
  ];
  return (
    <section>
      <h2>This PC</h2>
      <p className="muted">From this PC's config.yaml, never synced (architecture.md §4.1.1).</p>
      <dl className="facts">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Placeholder({ screen }: { screen: Screen }) {
  return (
    <section>
      <h2>{screen.label}</h2>
      <p className="muted">
        This screen arrives with branch {screen.branch}. Its design is in docs/design.html.
      </p>
    </section>
  );
}

export function App() {
  useEvents();
  const [screen, setScreen] = useState<ScreenId>("chat");
  const [selected, setSelected] = useState<string | null>(null);
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

  const active = SCREENS.find((s) => s.id === screen);
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
          <SettingsScreen status={status.data} />
        ) : screen === "review" ? (
          <ReviewScreen onOpenLink={openLink} />
        ) : (
          active && <Placeholder screen={active} />
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
