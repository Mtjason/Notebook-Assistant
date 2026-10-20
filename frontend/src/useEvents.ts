// Server-sent events from /api/events (architecture.md §2.4): when the service says counts
// changed, the cached counts are refetched; job events keep each running job's steps in the
// query cache (key ["jobs"], by note path), and a finished job refreshes the screens it touches.
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { JobView } from "./api";

export type Jobs = Record<string, JobView>;

/** The jobs known so far, by note path. Never fetched: only events and started jobs fill it,
 *  so a late empty fetch can't wipe a job that already arrived. */
export function useJobs(): Jobs {
  const jobs = useQuery<Jobs>({ queryKey: ["jobs"], queryFn: () => ({}), initialData: {}, staleTime: Infinity });
  return jobs.data;
}

export function onJob(queries: QueryClient, job: JobView): void {
  queries.setQueryData<Jobs>(["jobs"], (jobs) => ({ ...jobs, [job.ref]: job }));
  if (job.state !== "running") {
    void queries.invalidateQueries({ queryKey: ["digest"] });
    void queries.invalidateQueries({ queryKey: ["digest-item", job.ref] });
    void queries.invalidateQueries({ queryKey: ["changesets"] });
    void queries.invalidateQueries({ queryKey: ["inbox"] });
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
