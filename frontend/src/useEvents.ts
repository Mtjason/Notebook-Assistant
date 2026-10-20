// Server-sent events from /api/events (architecture.md §2.4): when the service says counts
// changed, the cached counts are refetched. Jobs (digest, sweep) publish here in later branches.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export function useEvents(): void {
  const queries = useQueryClient();
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.addEventListener("counts", () => void queries.invalidateQueries({ queryKey: ["counts"] }));
    return () => source.close();
  }, [queries]);
}
