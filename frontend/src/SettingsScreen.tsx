// The Settings screen (design.html, Settings): this PC's own settings (its config.yaml, never
// synced), and the maintenance buttons (Handbook §16.6). Each button runs as a job on this PC with
// live steps; its last report lists what it found and opens what it proposed on Review.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type MaintenanceReport, type ServiceStatus } from "./api";
import { Steps } from "./Steps";
import { type Jobs, useJobs } from "./useEvents";

const RUNS = [
  { kind: "changes", label: "Sweep changes", what: "Raw notes anywhere, planned into proposals (uses the model)" },
  { kind: "lint", label: "Lint", what: "Every rule on every note; mechanical fixes as one batch" },
  { kind: "deep", label: "Deep pass", what: "Duplicate candidates and missing links" },
  { kind: "archive", label: "Archive check", what: "Archive candidates, stale tasks, untouched ideas" },
] as const;

function SearchOption({ status }: { status: ServiceStatus }) {
  const [choice, setChoice] = useState(status.search);
  const save = useMutation({ mutationFn: () => api.setSearch(choice) });
  return (
    <p>
      <label>
        Search{" "}
        <select aria-label="Search option" value={choice} onChange={(e) => setChoice(e.target.value)}>
          {status.search_options.map((o) => (
            <option key={o} value={o}>
              {o === "keyword" ? "keyword only" : `keyword + meaning (${o})`}
            </option>
          ))}
        </select>
      </label>{" "}
      <button type="button" className="btn" disabled={choice === status.search || save.isPending} onClick={() => save.mutate()}>
        Save
      </button>{" "}
      <span className="muted">
        {save.isSuccess
          ? "Saved to this PC's config.yaml. Restart the service to apply; a model downloads once (e5-small ~120 MB, bge-m3 ~570 MB)."
          : "Per PC (architecture.md §4.3): meaning search runs a small model on the CPU."}
      </span>
      {save.isError && <span className="error"> {save.error.message}</span>}
    </p>
  );
}

function RebuildIndex() {
  const rebuild = useMutation({ mutationFn: api.rebuildIndex });
  return (
    <p>
      <button type="button" className="btn" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>
        Rebuild index
      </button>{" "}
      <span className="muted">
        {rebuild.data
          ? `Indexed ${rebuild.data.indexed} of ${rebuild.data.total} notes and sessions.`
          : "This PC's search index (a cache; rebuilding loses nothing)."}
      </span>
      {rebuild.isError && <span className="error"> {rebuild.error.message}</span>}
    </p>
  );
}

function ThisPc({ status }: { status: ServiceStatus }) {
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
      <SearchOption status={status} />
      <RebuildIndex />
    </section>
  );
}

function ReportView({ report, onOpenReview }: { report: MaintenanceReport; onOpenReview: (id: string) => void }) {
  return (
    <div className="panel report">
      <h4>
        {RUNS.find((r) => r.kind === report.kind)?.label} · {report.ran_at.replace("T", " ").slice(0, 16)}
      </h4>
      <p>{report.summary}</p>
      {report.changesets.length > 0 && (
        <button type="button" className="btn" onClick={() => onOpenReview(report.changesets[0] ?? "")}>
          Open {report.changesets.length} proposal(s) in Review
        </button>
      )}
      {report.rows.length > 0 && (
        <table className="report-rows">
          <tbody>
            {report.rows.map((row, i) => (
              <tr key={i}>
                <td className="mono">{row.path}</td>
                <td>
                  <span className="chip">{row.label}</span>
                </td>
                <td>{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function SettingsScreen({
  status,
  onOpenReview,
}: {
  status: ServiceStatus | undefined;
  onOpenReview: (id: string) => void;
}) {
  const queries = useQueryClient();
  const reports = useQuery({ queryKey: ["sweep"], queryFn: api.sweepReports });
  const job = useJobs().maintenance;
  const [shown, setShown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (kind: string) => api.runSweep(kind),
    onSuccess: (started, kind) => {
      setShown(kind);
      setError(null);
      queries.setQueryData<Jobs>(["jobs"], (all) => ({ ...all, maintenance: started }));
    },
    onError: (e: Error) => setError(e.message),
  });
  const running = job?.state === "running";
  const report = shown ? reports.data?.[shown] : undefined;

  if (!status) return <p className="muted">Loading…</p>;
  return (
    <div className="settings">
      <ThisPc status={status} />
      <section>
        <h2>Maintenance</h2>
        <p className="muted">
          Nothing runs on its own (Handbook §16.6). Every run only proposes; changes wait on Review.
        </p>
        <div className="run-buttons">
          {RUNS.map((r) => (
            <button
              key={r.kind}
              type="button"
              className="btn"
              title={r.what}
              disabled={running || start.isPending}
              onClick={() => start.mutate(r.kind)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="tabs" role="tablist" aria-label="Last reports">
          {RUNS.filter((r) => reports.data?.[r.kind]).map((r) => (
            <button key={r.kind} type="button" role="tab" aria-selected={shown === r.kind} onClick={() => setShown(r.kind)}>
              {r.label}
            </button>
          ))}
        </div>
        {job && <Steps steps={job.steps} running={running} />}
        {job?.state === "failed" && <p className="error">{job.message}</p>}
        {error && <p className="error">{error}</p>}
        {report && <ReportView report={report} onOpenReview={onOpenReview} />}
      </section>
    </div>
  );
}
