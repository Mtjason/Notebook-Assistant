// Server-sent events from /api/events (architecture.md §2.4): when the service says counts
// changed, the cached counts are refetched; job events keep each running job's steps in the
// query cache (key ["jobs"], by note path), and a finished job refreshes the Digest screen.
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { JobView } from "./api";

export type Jobs = Record<string, JobView>;

export function onJob(queries: QueryClient, job: JobView): void {
  queries.setQueryData<Jobs>(["jobs"], (jobs) => ({ ...jobs, [job.ref]: job }));
  if (job.state !== "running") {
    void queries.invalidateQueries({ queryKey: ["digest"] });
    void queries.invalidateQueries({ queryKey: ["digest-item", job.ref] });
    void queries.invalidateQueries({ queryKey: ["changesets"] });
  }
}

export function useEvents(): void {
  const queries = useQueryClient();
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("counts", () => void queries.invalidateQueries({ queryKey: ["counts"] }));
    source.addEventListener("job", (event: MessageEvent<string>) => {
      onJob(queries, JSON.parse(event.data) as JobView);
    });
    return () => source.close();
  }, [queries]);
}
