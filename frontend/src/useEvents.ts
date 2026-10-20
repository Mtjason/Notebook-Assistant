// Server-sent events from /api/events (architecture.md §2.4): when the service says counts
// changed, the cached counts are refetched; job events keep each running job's steps in the
// query cache (key ["jobs"], by note path), and a finished job refreshes the screens it touches;
// chat events build the streaming answer (key ["chat-live", session]).
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { ChatEvent, JobView } from "./api";

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
    void queries.invalidateQueries({ queryKey: ["sweep"] });
  }
}

/** A chat answer as it streams in, per session (key ["chat-live", session path]). */
export interface ChatLive {
  text: string;
  tools: string[];
  changesets: string[];
  error: string | null;
  running: boolean;
}

export function onChat(queries: QueryClient, event: ChatEvent): void {
  queries.setQueryData<ChatLive>(["chat-live", event.session], (live) => {
    const now = live ?? { text: "", tools: [], changesets: [], error: null, running: true };
    if (event.type === "token") return { ...now, text: now.text + event.text };
    if (event.type === "tool") return { ...now, tools: [...now.tools, event.text] };
    if (event.type === "changeset") return { ...now, changesets: [...now.changesets, event.text] };
    if (event.type === "error") return { ...now, error: event.text, running: false };
    return { ...now, running: false };
  });
  if (event.type === "done" || event.type === "error") {
    void queries.invalidateQueries({ queryKey: ["transcript", event.session] });
    void queries.invalidateQueries({ queryKey: ["sessions"] });
    void queries.invalidateQueries({ queryKey: ["counts"] });
  }
}

export function useChatLive(session: string | null): ChatLive | undefined {
  const live = useQuery<ChatLive | null>({
    queryKey: ["chat-live", session],
    queryFn: () => null,
    initialData: null,
    staleTime: Infinity,
    enabled: session !== null,
  });
  return live.data ?? undefined;
}

export function useEvents(): void {
  const queries = useQueryClient();
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("counts", () => void queries.invalidateQueries({ queryKey: ["counts"] }));
    source.addEventListener("chat", (event: MessageEvent<string>) => {
      onChat(queries, JSON.parse(event.data) as ChatEvent);
    });
    source.addEventListener("job", (event: MessageEvent<string>) => {
      onJob(queries, JSON.parse(event.data) as JobView);
    });
    return () => source.close();
  }, [queries]);
}
