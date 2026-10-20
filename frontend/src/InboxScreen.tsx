// The Inbox screen (design.html, Inbox; Handbook §3 row 1, §12): drop or paste a capture, save it
// to the Inbox as it came, and process a waiting note. Processing runs as a job on this PC whose
// steps arrive live; it proposes a changeset (the planned notes, and the capture filed as a
// source note or logged in the daily note) that opens on the Review screen.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type DragEvent } from "react";
import { api, fileUrl, type InboxItem } from "./api";
import { Steps } from "./Steps";
import { type Jobs, useJobs } from "./useEvents";

interface Props {
  onOpenReview: (changeset: string) => void;
}

const IMAGE = /\.(png|jpe?g|gif|webp)$/i;

function CaptureBox({
  origins,
  defaultOrigin,
  onSaved,
}: {
  origins: string[];
  defaultOrigin: string;
  onSaved: (paths: string[], process: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [origin, setOrigin] = useState(defaultOrigin);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (process: boolean) =>
      api.capture(text, origin, files).then((saved) => ({ saved, process })),
    onSuccess: ({ saved, process }) => {
      setText("");
      setFiles([]);
      setError(null);
      onSaved(saved.paths, process);
    },
    onError: (e: Error) => setError(e.message),
  });
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setFiles((old) => [...old, ...Array.from(event.dataTransfer.files)]);
  };
  const empty = !text.trim() && files.length === 0;

  return (
    <section className="capture" onDragOver={(e) => e.preventDefault()} onDrop={drop} aria-label="Capture">
      <textarea
        aria-label="Capture text"
        placeholder="Paste text, or drop screenshots, files, .eml or .msg emails here"
        value={text}
        rows={4}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="capture-row">
        <label className="btn">
          Add files
          <input
            type="file"
            multiple
            hidden
            onChange={(e) => setFiles((old) => [...old, ...Array.from(e.target.files ?? [])])}
          />
        </label>
        {files.map((f, i) => (
          <button
            key={`${f.name}-${i}`}
            type="button"
            className="chip"
            title="Remove"
            onClick={() => setFiles((old) => old.filter((_, j) => j !== i))}
          >
            {f.name} ×
          </button>
        ))}
        <label className="origin">
          origin{" "}
          <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
            {origins.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn" disabled={empty || save.isPending} onClick={() => save.mutate(false)}>
          Save to Inbox
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={empty || save.isPending}
          onClick={() => save.mutate(true)}
        >
          Save and process
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function ItemPanel({ item, onOpenReview }: { item: InboxItem; onOpenReview: (id: string) => void }) {
  const queries = useQueryClient();
  const job = useJobs()[item.path];
  const [error, setError] = useState<string | null>(null);
  const process = useMutation({
    mutationFn: () => api.processInbox(item.path),
    onSuccess: (started) => queries.setQueryData<Jobs>(["jobs"], (all) => ({ ...all, [item.path]: started })),
    onError: (e: Error) => setError(e.message),
  });
  const running = job?.state === "running";

  return (
    <article className="inbox-item">
      <header>
        <h3>{item.title}</h3>
        <p className="muted">
          {item.kind} · origin {item.origin}
          {item.captured ? ` · captured ${item.captured}` : ""}
        </p>
        {item.gap && <p className="error">Waiting on the handbook: {item.gap}</p>}
      </header>
      <div className="actions">
        <button type="button" className="btn primary" disabled={running || process.isPending} onClick={() => process.mutate()}>
          Process
        </button>
      </div>
      {job && <Steps steps={job.steps} running={running} />}
      {job?.state === "failed" && <p className="error">{job.message}</p>}
      {job?.state === "done" && job.changeset && (
        <div className="notice ok" role="status">
          {job.message}.{" "}
          <button type="button" className="btn" onClick={() => onOpenReview(job.changeset ?? "")}>
            Open in Review
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <section className="panel">
        <h4>As captured</h4>
        <p className="preview">{item.preview || "(no text)"}</p>
        {item.files.map((path, i) =>
          IMAGE.test(path) ? (
            <figure key={path}>
              <img src={fileUrl(path)} alt={`screenshot ${i + 1}: ${path.split("/").pop() ?? path}`} />
              <figcaption>screenshot {i + 1}</figcaption>
            </figure>
          ) : (
            <p key={path} className="muted">
              📎 {path.split("/").pop()}
            </p>
          ),
        )}
      </section>
    </article>
  );
}

export function InboxScreen({ onOpenReview }: Props) {
  const queries = useQueryClient();
  const view = useQuery({ queryKey: ["inbox"], queryFn: api.inbox });
  const [selected, setSelected] = useState<string | null>(null);
  const items = view.data?.items ?? [];
  const current = items.find((i) => i.path === selected) ?? items[0];

  const saved = (paths: string[], process: boolean) => {
    void queries.invalidateQueries({ queryKey: ["inbox"] });
    void queries.invalidateQueries({ queryKey: ["counts"] });
    setSelected(paths[0] ?? null);
    if (process) {
      for (const path of paths) {
        void api
          .processInbox(path)
          .then((started) => queries.setQueryData<Jobs>(["jobs"], (all) => ({ ...all, [path]: started })));
      }
    }
  };

  if (view.isError) return <p className="error">{view.error.message}</p>;
  if (!view.data) return <p className="muted">Loading…</p>;
  return (
    <section className="inbox">
      <CaptureBox origins={view.data.origins} defaultOrigin={view.data.default_origin} onSaved={saved} />
      <div className="review-cols">
        <ul className="cs-list" aria-label="Inbox">
          {items.map((i) => (
            <li key={i.path}>
              <button type="button" aria-current={i.path === current?.path} onClick={() => setSelected(i.path)}>
                <span className="cs-reason">{i.title}</span>
                <span className="muted">
                  {i.kind}
                  {i.files.length ? ` · ${i.files.length} file(s)` : ""}
                </span>
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="muted">The Inbox is empty.</li>}
        </ul>
        {current ? <ItemPanel key={current.path} item={current} onOpenReview={onOpenReview} /> : null}
      </div>
    </section>
  );
}
