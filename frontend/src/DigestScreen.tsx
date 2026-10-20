// The Digest screen (design.html, Digest; Handbook §19): the queue of notes that aren't finished
// knowledge yet, with each item's own buttons. Approve to digest starts right away on this PC
// and shows its steps live; a draft is reviewed side by side with what you wrote and its
// screenshots, then graduated or sent back with feedback. Finished canvases and notes can skip
// straight to Graduate as-is.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, fileUrl, type DigestItem, type Outcome } from "./api";
import { MarkdownView } from "./MarkdownView";
import { Steps } from "./Steps";
import { type Jobs, useJobs } from "./useEvents";

interface Props {
  onOpenLink: (target: string) => void;
}

const STATES = [
  { id: "pending", label: "Needs digestion" },
  { id: "approved", label: "Digesting" },
  { id: "review", label: "Ready to graduate" },
  { id: "graduated", label: "Graduated" },
] as const;

function GraduateAsIs({
  path,
  kinds,
  onDone,
}: {
  path: string;
  kinds: string[];
  onDone: (outcome: Outcome) => void;
}) {
  const canvas = path.endsWith(".canvas");
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState(kinds[0] ?? "");
  const graduate = useMutation({
    mutationFn: () => api.graduateAsIs(path, canvas ? kind : null),
    onSuccess: (outcome) => {
      setOpen(false);
      onDone(outcome);
    },
    onError: (error: Error) => onDone({ ok: false, status: "", problems: [error.message] }),
  });
  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        Graduate as-is
      </button>
    );
  }
  return (
    <div className="confirm" role="dialog" aria-label="Graduate as-is">
      <p>
        {canvas
          ? "Creates a companion note that holds the properties and embeds the canvas; its summary comes only from the canvas's own text cards."
          : "Marks the note finished without changing its text."}
      </p>
      {canvas && (
        <label>
          Companion note's kind{" "}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="actions">
        <button type="button" className="btn primary" disabled={graduate.isPending} onClick={() => graduate.mutate()}>
          Confirm
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ItemPanel({
  item,
  kinds,
  onOpenLink,
}: {
  item: DigestItem;
  kinds: string[];
  onOpenLink: (target: string) => void;
}) {
  const queries = useQueryClient();
  const view = useQuery({ queryKey: ["digest-item", item.path], queryFn: () => api.digestItem(item.path) });
  const job = useJobs()[item.path];
  const [feedback, setFeedback] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const refresh = (result: Outcome) => {
    setOutcome(result);
    void queries.invalidateQueries({ queryKey: ["digest"] });
    void queries.invalidateQueries({ queryKey: ["digest-item", item.path] });
    void queries.invalidateQueries({ queryKey: ["counts"] });
  };
  const failed = (error: Error) => setOutcome({ ok: false, status: "", problems: [error.message] });
  const approve = useMutation({
    mutationFn: () => api.approveToDigest(item.path),
    onSuccess: (started) => queries.setQueryData<Jobs>(["jobs"], (all) => ({ ...all, [item.path]: started })),
    onError: failed,
  });
  const graduate = useMutation({ mutationFn: () => api.graduate(item.path), onSuccess: refresh, onError: failed });
  const sendBack = useMutation({ mutationFn: () => api.sendBack(item.path, feedback), onSuccess: refresh, onError: failed });
  const running = job?.state === "running" || item.state === "approved";

  return (
    <article className="digest-item">
      <header>
        <h3>{item.title}</h3>
        <p className="muted">
          {item.path} · {item.reasons.join(", ") || "no reason given"}
        </p>
        {item.error && <p className="error">Last run: {item.error}</p>}
        {item.feedback && <p className="muted">Your feedback: {item.feedback}</p>}
      </header>

      {job && <Steps steps={job.steps} running={job.state === "running"} />}
      {job?.state === "failed" && <p className="error">{job.message}</p>}

      <div className="actions">
        {item.state === "pending" && (
          <>
            <button type="button" className="btn primary" disabled={running || approve.isPending} onClick={() => approve.mutate()}>
              Approve to digest
            </button>
            <GraduateAsIs path={item.path} kinds={kinds} onDone={refresh} />
          </>
        )}
        {item.state === "review" && (
          <button type="button" className="btn primary" disabled={graduate.isPending} onClick={() => graduate.mutate()}>
            Approve to graduate
          </button>
        )}
      </div>

      {view.data && (
        <div className="side-by-side">
          <section className="panel">
            <h4>What you wrote</h4>
            <MarkdownView text={view.data.original} onOpenNote={onOpenLink} />
            {view.data.screenshots.map((path, i) => (
              <figure key={path}>
                <img src={fileUrl(path)} alt={`screenshot ${i + 1}: ${path.split("/").pop() ?? path}`} />
                <figcaption>screenshot {i + 1}</figcaption>
              </figure>
            ))}
          </section>
          <section className="panel">
            <h4>Draft</h4>
            {view.data.draft ? (
              <MarkdownView text={view.data.draft} onOpenNote={onOpenLink} />
            ) : (
              <p className="muted">No draft yet. Approve to digest writes one.</p>
            )}
          </section>
        </div>
      )}

      {item.state === "review" && (
        <div className="send-back">
          <label>
            Send back with feedback
            <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} rows={3} />
          </label>
          <button type="button" className="btn" disabled={sendBack.isPending} onClick={() => sendBack.mutate()}>
            Send back
          </button>
        </div>
      )}

      {outcome && (
        <div className={outcome.ok ? "notice ok" : "notice fail"} role="status">
          {outcome.ok ? `Done: ${outcome.status}.` : `Not done: ${outcome.problems.join("; ")}`}
        </div>
      )}
    </article>
  );
}

export function DigestScreen({ onOpenLink }: Props) {
  const queue = useQuery({ queryKey: ["digest"], queryFn: api.digest });
  const [state, setState] = useState<string>("pending");
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const reasons = useMemo(() => [...new Set(items.flatMap((i) => i.reasons))].sort(), [items]);
  const shown = items.filter((i) => i.state === state && (!reason || i.reasons.includes(reason)));
  const current = items.find((i) => i.path === selected) ?? shown[0];

  if (queue.isError) return <p className="error">{queue.error.message}</p>;
  return (
    <section className="digest">
      <div className="tabs" role="tablist" aria-label="Digest states">
        {STATES.map((s) => (
          <button key={s.id} type="button" role="tab" aria-selected={s.id === state} onClick={() => setState(s.id)}>
            {s.label} {items.filter((i) => i.state === s.id).length}
          </button>
        ))}
        <select aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">every reason</option>
          {reasons.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div className="review-cols">
        <div>
          <ul className="cs-list" aria-label="Queue">
            {shown.map((i) => (
              <li key={i.path}>
                <button type="button" aria-current={i.path === current?.path} onClick={() => setSelected(i.path)}>
                  <span className="cs-reason">{i.title}</span>
                  <span className="muted">{i.reasons.join(", ") || i.type}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="muted">Nothing here.</li>}
          </ul>
          {state === "pending" && (queue.data?.canvases.length ?? 0) > 0 && (
            <>
              <h4>Finished drawings?</h4>
              <ul className="cs-list" aria-label="Canvases">
                {queue.data?.canvases.map((path) => (
                  <li key={path} className="canvas-item">
                    <span>{path.split("/").pop()}</span>
                    <GraduateAsIs
                      path={path}
                      kinds={queue.data?.kinds ?? []}
                      onDone={() => void queue.refetch()}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        {current ? (
          <ItemPanel key={current.path} item={current} kinds={queue.data?.kinds ?? []} onOpenLink={onOpenLink} />
        ) : null}
      </div>
    </section>
  );
}
