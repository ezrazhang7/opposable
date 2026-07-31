/** Helpers for driving the fixture backend from a scene: create tasks, wait
 *  for a status, stop one. Scenes stay declarative; the polling lives here. */
import { BASE } from "./shoot";

export type TaskStatus = "running" | "complete" | "stopped" | "error";
export type TaskMeta = { id: string; title: string; status: TaskStatus };

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${res.status} ${text}`);
  return (text ? JSON.parse(text) : {}) as T;
}

export const createTask = (task: string, model = "demo", extra: Record<string, unknown> = {}) =>
  json<TaskMeta>("/api/tasks", {
    method: "POST",
    body: JSON.stringify({ task, model, ...extra }),
  });

export const getTask = (id: string) => json<TaskMeta>(`/api/tasks/${id}`);
export const listTasks = () => json<TaskMeta[]>("/api/tasks");
export const stopTask = (id: string) => json(`/api/tasks/${id}/stop`, { method: "POST" });

export async function waitForStatus(id: string, want: TaskStatus, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { status } = await getTask(id);
    if (status === want) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`task ${id} never reached ${want}`);
}

/** Wait until a task has emitted at least `n` events — used to catch a run
 *  mid-flight for "live" screenshots. */
export async function waitForEvents(id: string, n: number, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const detail = await json<{ events: unknown[] }>(`/api/tasks/${id}`);
    if (detail.events.length >= n) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`task ${id} never reached ${n} events`);
}
