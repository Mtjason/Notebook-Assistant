// The Tasks screen (design.html, Tasks; Handbook §17): the §17.5 views, filtered by kind. Changing
// a task's status is still a change, so it takes a one-line confirm (InlineConfirm) that applies a
// single-operation changeset. A question or learn task is done only with the knowledge note it
// produced (§17.1), so marking one done asks for it.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { api, type NoteSummary, type TaskRow } from "./api";

const KINDS = ["all", "action", "question", "learn"] as const;

function InlineConfirm({
  task,
  statuses,
  knowledge,
  onDone,
}: {
  task: TaskRow;
  statuses: string[];
  knowledge: NoteSummary[];
  onDone: () => void;
}) {
  const queries = useQueryClient();
  const [status, setStatus] = useState(task.status === "done" ? "todo" : "done");
  const [produced, setProduced] = useState("");
  const needsProduced = status === "done" && (task.kind === "learn" || task.kind === "question");
  const change = useMutation({
    mutationFn: () => api.setStatus(task.path, status, needsProduced && produced ? [produced] : null),
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["tasks"] });
      void queries.invalidateQueries({ queryKey: ["counts"] });
      onDone();
    },
  });
  return (
    <div className="confirm" role="dialog" aria-label={`Change ${task.title}`}>
      <p>
        {task.title}: status {task.status} →{" "}
        <select aria-label="New status" value={status} onChange={(e) => setStatus(e.target.value)}>
          {statuses.filter((s) => s !== task.status).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </p>
      {needsProduced && (
        <label>
          Produced (Handbook §17.1){" "}
          <select aria-label="Produced" value={produced} onChange={(e) => setProduced(e.target.value)}>
            <option value="">choose the knowledge note…</option>
            {knowledge.map((n) => (
              <option key={n.path} value={n.title}>
                {n.title}
              </option>
            ))}
          </select>
        </label>
      )}
      {change.isError && <p className="error">{change.error.message}</p>}
      <div className="actions">
        <button
          type="button"
          className="btn primary"
          disabled={change.isPending || (needsProduced && !produced)}
          onClick={() => change.mutate()}
        >
          Apply
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function Row({
  task,
  open,
  onOpen,
  children,
}: {
  task: TaskRow;
  open: boolean;
  onOpen: () => void;
  children?: ReactNode;
}) {
  const facts = [task.kind, task.priority, task.due && `due ${task.due}`, task.waiting_on && `waiting on ${task.waiting_on}`];
  return (
    <li className="task-row">
      <button type="button" className="tick" aria-label={`Change status of ${task.title}`} aria-expanded={open} onClick={onOpen}>
        {task.status === "done" ? "☑" : "☐"}
      </button>
      <span className="task-title">{task.title}</span>
      <span className="muted">
        {facts.filter(Boolean).join(" · ")}
        {task.produced.length > 0 && ` · produced ${task.produced.join(", ")}`}
      </span>
      {children && <div className="task-confirm">{children}</div>}
    </li>
  );
}

export function TasksScreen() {
  const view = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const notes = useQuery({ queryKey: ["notes"], queryFn: api.notes });
  const [name, setName] = useState<string | null>(null);
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");
  const [open, setOpen] = useState<string | null>(null);

  if (view.isError) return <p className="error">{view.error.message}</p>;
  if (!view.data) return <p className="muted">Loading…</p>;
  const current = view.data.views.find((v) => v.name === name) ?? view.data.views[0];
  const knowledge = (notes.data ?? []).filter((n) => n.type === "knowledge");
  const shown = (current?.groups ?? [])
    .map((g) => ({ ...g, tasks: g.tasks.filter((t) => kind === "all" || t.kind === kind) }))
    .filter((g) => g.tasks.length > 0);

  return (
    <section className="tasks">
      <div className="tabs" role="tablist" aria-label="Task views">
        {view.data.views.map((v) => (
          <button key={v.name} type="button" role="tab" aria-selected={v.name === current?.name} onClick={() => setName(v.name)}>
            {v.name} {v.groups.reduce((n, g) => n + g.tasks.length, 0)}
          </button>
        ))}
      </div>
      <div className="row-filters" role="group" aria-label="Kind">
        {KINDS.map((k) => (
          <button key={k} type="button" className={k === kind ? "chip on" : "chip"} aria-pressed={k === kind} onClick={() => setKind(k)}>
            {k}
          </button>
        ))}
      </div>
      {shown.length === 0 && <p className="muted">Nothing in this view.</p>}
      {shown.map((group) => (
        <div key={group.label} className="task-group">
          <h4>{group.label}</h4>
          <ul>
            {group.tasks.map((task) => (
              <Row key={task.path} task={task} open={open === task.path} onOpen={() => setOpen(open === task.path ? null : task.path)}>
                {open === task.path && (
                  <InlineConfirm task={task} statuses={view.data.statuses} knowledge={knowledge} onDone={() => setOpen(null)} />
                )}
              </Row>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
