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

// The Review screen (src/notebook_assistant/app/review.py).
export interface ChangesetSummary {
  id: string;
  reason: string;
  created_by: string;
  created: string;
  status: "pending" | "applied" | "rejected" | "reverted" | "failed";
  operations: number;
}

export interface OperationView {
  index: number;
  kind: "create" | "write" | "move" | "delete";
  path: string;
  dest: string | null;
  label: string;
  before: string | null;
  after: string | null;
}

export interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

export interface AtomView {
  id: string;
  role: string;
  notes: string[];
  text: string;
}

export interface ChangesetDetail {
  summary: ChangesetSummary;
  error: string | null;
  review: string;
  operations: OperationView[];
  checks: CheckResult[];
  atoms: AtomView[];
  planned_notes: string[];
}

export interface Outcome {
  ok: boolean;
  status: string;
  problems: string[];
}

// The Digest screen (src/notebook_assistant/domain/digest.py, app/digest.py, api/jobs.py).
export interface DigestItem {
  path: string;
  title: string;
  type: string | null;
  state: string;
  reasons: string[];
  error: string | null;
  feedback: string | null;
  draft: string | null;
  runner: string | null;
}

export interface DigestQueue {
  items: DigestItem[];
  canvases: string[];
  kinds: string[];
}

export interface DigestView {
  item: DigestItem;
  original: string;
  draft: string | null;
  screenshots: string[];
}

export interface JobView {
  id: string;
  kind: string;
  ref: string;
  state: "running" | "done" | "failed";
  steps: string[];
  message: string;
}

/** The header the service requires on every write (no cross-site requests). */
export const CLIENT_HEADER = { "X-Requested-With": "notebook-assistant" };

async function parse<T>(path: string, response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(response.status, `${path}: ${detail}`);
  }
  return (await response.json()) as T;
}

async function get<T>(path: string): Promise<T> {
  return parse<T>(path, await fetch(path));
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: "POST", headers: { ...CLIENT_HEADER } };
  if (body !== undefined) {
    init.headers = { ...CLIENT_HEADER, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  return parse<T>(path, await fetch(path, init));
}

const changeset = (id: string) => `/api/changesets/${encodeURIComponent(id)}`;

/** A vault path as URL path segments (slashes kept, everything else encoded). */
export const pathUrl = (path: string) => path.split("/").map(encodeURIComponent).join("/");

export const api = {
  status: () => get<ServiceStatus>("/api/status"),
  counts: () => get<Counts>("/api/counts"),
  notes: () => get<NoteSummary[]>("/api/notes"),
  note: (path: string) => get<NoteDetail>(`/api/notes/${pathUrl(path)}`),
  changesets: (history: boolean) =>
    get<ChangesetSummary[]>(`/api/changesets${history ? "?status=history" : ""}`),
  changeset: (id: string) => get<ChangesetDetail>(changeset(id)),
  apply: (id: string, ops: number[] | null) => post<Outcome>(`${changeset(id)}/apply`, { ops }),
  reject: (id: string) => post<Outcome>(`${changeset(id)}/reject`),
  revert: (id: string) => post<Outcome>(`${changeset(id)}/revert`),
  moveAtom: (id: string, atom: string, note: string | null) =>
    post<Outcome>(`${changeset(id)}/atoms/${encodeURIComponent(atom)}`, { note }),
  digest: () => get<DigestQueue>("/api/digest"),
  digestItem: (path: string) => get<DigestView>(`/api/digest/item/${pathUrl(path)}`),
  approveToDigest: (path: string) => post<JobView>(`/api/digest/approve/${pathUrl(path)}`),
  graduate: (path: string) => post<Outcome>(`/api/digest/graduate/${pathUrl(path)}`),
  sendBack: (path: string, feedback: string) =>
    post<Outcome>(`/api/digest/send-back/${pathUrl(path)}`, { feedback }),
  graduateAsIs: (path: string, kind: string | null) =>
    post<Outcome>(`/api/graduate/${pathUrl(path)}`, { kind }),
};

/** An image in the vault, as the page loads it. */
export const fileUrl = (path: string) => `/api/files/${pathUrl(path)}`;

/** The `obsidian://open` link for a note (architecture §2). */
export function obsidianLink(vaultFolder: string, path: string): string {
  const vault = vaultFolder.split(/[\\/]/).filter(Boolean).pop() ?? vaultFolder;
  const file = path.replace(/\.md$/, "");
  return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
}
