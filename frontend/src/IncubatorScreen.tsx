// The Incubator screen (design.html, Incubator; Handbook §18): ideas as a board by status. Moving
// a card applies its status change (a one-click change on one note); Promote proposes a new
// project and the idea's promotion as a changeset, opened on Review.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type IdeaCard } from "./api";

// What a card in each column can do next (§18.4 lifecycle).
const MOVES: Record<string, { label: string; to: string }[]> = {
  exploring: [{ label: "Shaping", to: "shaping" }, { label: "Park", to: "parked" }, { label: "Drop", to: "dropped" }],
  shaping: [{ label: "Exploring", to: "exploring" }, { label: "Park", to: "parked" }, { label: "Drop", to: "dropped" }],
  parked: [{ label: "Revive", to: "exploring" }, { label: "Drop", to: "dropped" }],
};

function Card({ card, onOpenReview }: { card: IdeaCard; onOpenReview: (id: string) => void }) {
  const queries = useQueryClient();
  const [title, setTitle] = useState<string | null>(null);
  const done = () => void queries.invalidateQueries({ queryKey: ["incubator"] });
  const move = useMutation({ mutationFn: (to: string) => api.setStatus(card.path, to), onSuccess: done });
  const promote = useMutation({
    mutationFn: (name: string) => api.promote(card.path, name),
    onSuccess: (ref) => onOpenReview(ref.changeset),
  });
  const live = card.status === "exploring" || card.status === "shaping";
  return (
    <article className="idea-card">
      <h4>{card.title}</h4>
      {card.question && <p>{card.question}</p>}
      {card.next_step && <p className="muted">Next: {card.next_step}</p>}
      <p className="muted">updated {card.updated ?? "—"}</p>
      <div className="actions">
        {(MOVES[card.status] ?? []).map((m) => (
          <button key={m.to} type="button" className="btn" disabled={move.isPending} onClick={() => move.mutate(m.to)}>
            {m.label}
          </button>
        ))}
        {live && title === null && (
          <button type="button" className="btn primary" onClick={() => setTitle(`${card.title} project`)}>
            Promote
          </button>
        )}
      </div>
      {title !== null && (
        <div className="confirm" role="dialog" aria-label={`Promote ${card.title}`}>
          <label>
            Project title{" "}
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <div className="actions">
            <button type="button" className="btn primary" disabled={!title.trim() || promote.isPending} onClick={() => promote.mutate(title)}>
              Propose project
            </button>
            <button type="button" className="btn" onClick={() => setTitle(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {(move.isError || promote.isError) && <p className="error">{(move.error ?? promote.error)?.message}</p>}
    </article>
  );
}

export function IncubatorScreen({ onOpenReview }: { onOpenReview: (id: string) => void }) {
  const board = useQuery({ queryKey: ["incubator"], queryFn: api.incubator });
  if (board.isError) return <p className="error">{board.error.message}</p>;
  if (!board.data) return <p className="muted">Loading…</p>;
  return (
    <section className="board" aria-label="Incubator">
      {Object.entries(board.data.columns).map(([status, cards]) => (
        <div key={status} className="column">
          <h3>
            {status} <span className="muted">{cards.length}</span>
          </h3>
          {cards.map((card) => (
            <Card key={card.path} card={card} onOpenReview={onOpenReview} />
          ))}
        </div>
      ))}
    </section>
  );
}
