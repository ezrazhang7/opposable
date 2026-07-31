/** Typed client for the stdlib Python bridge in opposable/server.py. */

export type TaskStatus = "running" | "complete" | "stopped" | "error";

export type TaskMeta = {
  id: string;
  task: string;
  title: string;
  created: number;
  status: TaskStatus;
  workdir: string;
  model: string | null;
  sandbox: string;
};

export type CreateTaskBody = {
  task: string;
  model?: string;
  base_url?: string;
  sandbox?: string;
  max_iterations?: number;
  budget_tokens?: number;
};

export type Usage = Record<string, number>;

export type EventPayloads = {
  /** The task's own follow-up guidance, echoed back so it lands in the
   *  transcript the same way the model receives it. */
  user: { text: string };
  assistant: { text: string };
  tool: { name: string; args: Record<string, unknown>; step: number };
  observation: { name: string; text: string; step: number };
  plan: { plan: string };
  compress: { evicted: number };
  done: {
    completed: boolean;
    summary: string;
    iterations: number;
    deliverables: string[];
    usage: Usage;
  };
  status: { state: TaskStatus; resumed?: boolean; detail?: string };
};

export type EventKind = keyof EventPayloads;
export const EVENT_KINDS: EventKind[] = [
  "user",
  "assistant",
  "tool",
  "observation",
  "plan",
  "compress",
  "done",
  "status",
];

export type AgentEvent = {
  [K in EventKind]: { seq: number; kind: K; payload: EventPayloads[K] };
}[EventKind];

export type TaskDetail = TaskMeta & { events: AgentEvent[] };

export type FileEntry = { path: string; size: number; mtime: number; internal: boolean };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(body.error ?? `${res.status} ${res.statusText}`);
  return body as T;
}

/** What the server will say about a provider key. Never the key itself —
 *  there is no use for it here worth the risk of a logged response body. */
export type KeyStatus = {
  configured: boolean;
  provider: string | null;
  trial_tasks_remaining: number;
  trial_micros_remaining: number;
};

export const api = {
  listTasks: () => call<TaskMeta[]>("/api/tasks"),
  /** Resolves to null on a single-user server, where /api/auth is disabled. */
  getKeyStatus: () => call<KeyStatus>("/api/auth/keys").catch(() => null),
  setProviderKey: (provider: string, key: string) =>
    call<{ configured: boolean }>("/api/auth/keys", {
      method: "POST",
      body: JSON.stringify({ provider, key }),
    }),
  getTask: (id: string) => call<TaskDetail>(`/api/tasks/${id}`),
  createTask: (body: CreateTaskBody) =>
    call<TaskMeta>("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
  stopTask: (id: string) => call<{ ok: boolean }>(`/api/tasks/${id}/stop`, { method: "POST" }),
  sendMessage: (id: string, text: string) =>
    call<{ ok: boolean }>(`/api/tasks/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  resumeTask: (id: string, text?: string) =>
    call<TaskMeta>(`/api/tasks/${id}/resume`, {
      method: "POST",
      body: JSON.stringify(text ? { text } : {}),
    }),
  listFiles: (id: string) => call<{ files: FileEntry[] }>(`/api/tasks/${id}/files`),
  fileUrl: (id: string, path: string) =>
    `/api/tasks/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
};

/** Subscribe to a task's event stream. History is replayed before live events,
 *  and the server closes with an `eof` event once the task is no longer
 *  running — at which point we close too, rather than letting EventSource
 *  reconnect forever. */
export function openEvents(
  id: string,
  handlers: {
    onEvent: (e: AgentEvent) => void;
    onEof?: () => void;
    onError?: () => void;
    onAuthExpired?: () => void;
  },
): () => void {
  const source = new EventSource(`/api/tasks/${id}/events`);
  for (const kind of EVENT_KINDS) {
    source.addEventListener(kind, (ev) => {
      const msg = ev as MessageEvent<string>;
      handlers.onEvent({
        seq: Number(msg.lastEventId),
        kind,
        payload: JSON.parse(msg.data),
      } as AgentEvent);
    });
  }
  source.addEventListener("eof", () => {
    source.close();
    handlers.onEof?.();
  });
  // The server re-reads the session row on its heartbeat, so a logout or a
  // suspension ends the stream mid-run. Close *before* handing back to the
  // caller: EventSource reconnects automatically, and reconnecting into a
  // login redirect is an infinite loop.
  source.addEventListener("auth_expired", () => {
    source.close();
    handlers.onAuthExpired?.();
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) handlers.onError?.();
  };
  return () => source.close();
}
