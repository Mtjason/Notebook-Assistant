// The Review screen (design.html, Review): every proposed change in one place. Pick a
// changeset, tick the operations to apply, see each one's diff and the checks, move or drop a
// capture's atoms, then apply, reject, or later undo.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type AtomView, type ChangesetDetail, type Outcome } from "./api";
import { DiffView } from "./DiffView";
import { MarkdownView } from "./MarkdownView";

interface Props {
  onOpenLink: (target: string) => void;
}

function shortTime(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

function ChecksBar({ detail }: { detail: ChangesetDetail }) {
  if (detail.checks.length === 0) return null;
  return (
    <ul className="checks" aria-label="Checks">
      {detail.checks.map((c) => (
        <li key={c.name} className={c.ok ? "ok" : "fail"} title={c.detail}>
          {c.ok ? "✓" : "✗"} {c.name}
        </li>
      ))}
    </ul>
  );
}

function AtomRow({
  atom,
  notes,
  busy,
  onMove,
}: {
  atom: AtomView;
  notes: string[];
  busy: boolean;
  onMove: (note: string | null) => void;
}) {
  const current = atom.role === "filler" ? "" : (atom.notes[0] ?? "");
  return (
    <li className="atom">
      <span className="atom-role">{atom.role}</span>
      <span className="atom-text" title={atom.text}>
        {atom.text.length > 140 ? `${atom.text.slice(0, 139)}…` : atom.text}
      </span>
      <label>
        <span className="visually-hidden">Lands in</span>
        <select
          value={current}
          disabled={busy}
          onChange={(e) => onMove(e.target.value === "" ? null : e.target.value)}
          aria-label={`Where atom ${atom.id} lands`}
        >
          <option value="">(dropped)</option>
          {notes.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
    </li>
  );
}

function Detail({ id, onOpenLink }: { id: string; onOpenLink: (target: string) => void }) {
  const queries = useQueryClient();
  const detail = useQuery({ queryKey: ["changeset", id], queryFn: () => api.changeset(id) });
  const [unticked, setUnticked] = useState<Set<number>>(new Set());
  const [shown, setShown] = useState(0);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const done = (result: Outcome) => {
    setOutcome(result);
    void queries.invalidateQueries({ queryKey: ["changesets"] });
    void queries.invalidateQueries({ queryKey: ["changeset", id] });
    void queries.invalidateQueries({ queryKey: ["counts"] });
    void queries.invalidateQueries({ queryKey: ["notes"] });
  };
  const failed = (error: Error) => setOutcome({ ok: false, status: "", problems: [error.message] });
  const apply = useMutation({ mutationFn: (ops: number[] | null) => api.apply(id, ops), onSuccess: done, onError: failed });
  const reject = useMutation({ mutationFn: () => api.reject(id), onSuccess: done, onError: failed });
  const revert = useMutation({ mutationFn: () => api.revert(id), onSuccess: done, onError: failed });
  const move = useMutation({
    mutationFn: ({ atom, note }: { atom: string; note: string | null }) => api.moveAtom(id, atom, note),
    onSuccess: (result) => {
      setUnticked(new Set());
      done(result);
    },
    onError: failed,
  });
  const busy = apply.isPending || reject.isPending || revert.isPending || move.isPending;

  if (detail.isPending) return <p className="muted">Loading…</p>;
  if (detail.isError) return <p className="error">{detail.error.message}</p>;
  const cs = detail.data;
  const pending = cs.summary.status === "pending";
  const ticked = cs.operations.filter((op) => !unticked.has(op.index)).map((op) => op.index);
  const op = cs.operations[shown] ?? cs.operations[0];

  return (
    <article className="cs-detail">
      <header>
        <h3>{cs.summary.reason}</h3>
        <p className="muted">
          {cs.summary.id} · {cs.summary.created_by} · {shortTime(cs.summary.created)} ·{" "}
          <span className={`status status-${cs.summary.status}`}>{cs.summary.status}</span>
        </p>
        {cs.error && <p className="error">{cs.error}</p>}
      </header>

      <ChecksBar detail={cs} />

      <h4>Operations</h4>
      <ul className="ops">
        {cs.operations.map((o) => (
          <li key={o.index} className={o.index === op?.index ? "current" : undefined}>
            {pending && (
              <input
                type="checkbox"
                aria-label={`Apply ${o.kind} ${o.path}`}
                checked={!unticked.has(o.index)}
                onChange={(e) => {
                  const next = new Set(unticked);
                  if (e.target.checked) next.delete(o.index);
                  else next.add(o.index);
                  setUnticked(next);
                }}
              />
            )}
            <button type="button" className="op-button" onClick={() => setShown(o.index)}>
              <span className="op-kind">{o.kind}</span> {o.dest ? `${o.path} → ${o.dest}` : o.path}
              {o.label && <span className="muted"> · {o.label}</span>}
            </button>
          </li>
        ))}
      </ul>
      {op && <DiffView before={op.before} after={op.after} />}

      {cs.atoms.length > 0 && (
        <>
          <h4>Split map</h4>
          <p className="muted">
            Move a piece of the capture to another note, or drop it. The plan is checked again
            before it replaces this one.
          </p>
          <ul className="atoms">
            {cs.atoms.map((a) => (
              <AtomRow
                key={a.id}
                atom={a}
                notes={cs.planned_notes}
                busy={busy || !pending}
                onMove={(note) => move.mutate({ atom: a.id, note })}
              />
            ))}
          </ul>
        </>
      )}
      {cs.review && (
        <details className="review-md">
          <summary>Review notes</summary>
          <MarkdownView text={cs.review} onOpenNote={onOpenLink} />
        </details>
      )}

      {outcome && (
        <div className={outcome.ok ? "notice ok" : "notice fail"} role="status">
          {outcome.ok ? `Done: ${outcome.status}.` : "Not done:"}
          {outcome.problems.length > 0 && (
            <ul>
              {outcome.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="actions">
        {pending && (
          <>
            <button
              type="button"
              className="btn primary"
              disabled={busy || ticked.length === 0}
              onClick={() => apply.mutate(ticked.length === cs.operations.length ? null : ticked)}
            >
              Apply {ticked.length === cs.operations.length ? "all" : `${ticked.length} selected`}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => reject.mutate()}>
              Reject
            </button>
          </>
        )}
        {cs.summary.status === "applied" && (
          <button type="button" className="btn" disabled={busy} onClick={() => revert.mutate()}>
            Undo
          </button>
        )}
      </div>
    </article>
  );
}

export function ReviewScreen({ onOpenLink }: Props) {
  const [history, setHistory] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["changesets", history], queryFn: () => api.changesets(history) });
  const chosen = selected ?? list.data?.[0]?.id ?? null;

  return (
    <section className="review">
      <div className="tabs" role="tablist" aria-label="Changesets">
        <button type="button" role="tab" aria-selected={!history} onClick={() => setHistory(false)}>
          Pending
        </button>
        <button type="button" role="tab" aria-selected={history} onClick={() => setHistory(true)}>
          History
        </button>
      </div>
      <div className="review-cols">
        <ul className="cs-list" aria-label={history ? "History" : "Pending changesets"}>
          {list.data?.map((cs) => (
            <li key={cs.id}>
              <button type="button" aria-current={cs.id === chosen} onClick={() => setSelected(cs.id)}>
                <span className="cs-reason">{cs.reason}</span>
                <span className="muted">
                  {shortTime(cs.created)} · {cs.operations} op · {cs.status}
                </span>
              </button>
            </li>
          ))}
          {list.data?.length === 0 && (
            <li className="muted">{history ? "Nothing applied or rejected yet." : "Nothing to review."}</li>
          )}
        </ul>
        {chosen ? <Detail key={chosen} id={chosen} onOpenLink={onOpenLink} /> : null}
      </div>
    </section>
  );
}
