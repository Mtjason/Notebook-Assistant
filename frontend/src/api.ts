// The service's JSON (src/notebook_assistant/api/server.py and app/browse.py), typed.

export interface ServiceStatus {
  version: string;
  handbook_version: string;
  machine: string;
  machine_id: string;
  profile: string;
  watch: string;
  vault: string;
}

export interface Counts {
  inbox: number;
  digest: number;
  review: number;
}

export interface NoteSummary {
  path: string;
  title: string;
  type: string | null;
  aliases: string[];
}

export interface NoteDetail {
  path: string;
  title: string;
  props: Record<string, unknown>;
  body: string;
  backlinks: string[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new ApiError(response.status, `${path}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => get<ServiceStatus>("/api/status"),
  counts: () => get<Counts>("/api/counts"),
  notes: () => get<NoteSummary[]>("/api/notes"),
  note: (path: string) =>
    get<NoteDetail>(`/api/notes/${path.split("/").map(encodeURIComponent).join("/")}`),
};

/** The `obsidian://open` link for a note (architecture §2). */
export function obsidianLink(vaultFolder: string, path: string): string {
  const vault = vaultFolder.split(/[\\/]/).filter(Boolean).pop() ?? vaultFolder;
  const file = path.replace(/\.md$/, "");
  return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
}
