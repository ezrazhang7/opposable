import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  openEvents,
  type AgentEvent,
  type EventPayloads,
  type TaskMeta,
  type TaskStatus,
} from "./api";

export type Step = {
  step: number;
  seq: number;
  name: string;
  args: Record<string, unknown>;
  observation?: string;
};

export type ChatItem =
  | { key: string; kind: "user"; text: string }
  | { key: string; kind: "assistant"; text: string }
  | { key: string; kind: "tool"; step: Step }
  | { key: string; kind: "compress"; evicted: number }
  | { key: string; kind: "done"; payload: EventPayloads["done"] };

export type Session = {
  events: AgentEvent[];
  items: ChatItem[];
  steps: Step[];
  plan: string | null;
  done: EventPayloads["done"] | null;
  status: TaskStatus;
  /** Why a run ended badly, when the server said. */
  statusDetail: string | null;
  /** Set once the server has closed the stream: the task is not running. */
  ended: boolean;
  error: string | null;
  /** Reopen the stream — used after resuming a task the server had closed. */
  reconnect: () => void;
};

/** Subscribes to one task's event stream. History replays before live events,
 *  so the same code path serves a live run and a replay of a finished one. */
export function useSession(task: TaskMeta | null): Session {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const seen = useRef(new Set<number>());
  const id = task?.id ?? null;
  const reconnect = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    seen.current = new Set();
    setEvents([]);
    setEnded(false);
    setError(null);
    if (!id) return;
    return openEvents(id, {
      onEvent: (e) => {
        // EventSource replays history on reconnect; seq makes that idempotent.
        if (seen.current.has(e.seq)) return;
        seen.current.add(e.seq);
        setEvents((prev) => [...prev, e]);
      },
      onEof: () => setEnded(true),
      onError: () => setError("event stream disconnected"),
    });
  }, [id, nonce]);

  const steps = useMemo(() => {
    const byStep = new Map<number, Step>();
    for (const e of events) {
      if (e.kind === "tool") {
        byStep.set(e.payload.step, {
          step: e.payload.step,
          seq: e.seq,
          name: e.payload.name,
          args: e.payload.args,
        });
      } else if (e.kind === "observation") {
        const found = byStep.get(e.payload.step);
        if (found) byStep.set(e.payload.step, { ...found, observation: e.payload.text });
      }
    }
    return [...byStep.values()].sort((a, b) => a.step - b.step);
  }, [events]);

  const items = useMemo(() => {
    const stepById = new Map(steps.map((s) => [s.step, s]));
    const out: ChatItem[] = [];
    if (task) out.push({ key: "task", kind: "user", text: task.task });
    for (const e of events) {
      switch (e.kind) {
        case "user":
          out.push({ key: `u${e.seq}`, kind: "user", text: e.payload.text });
          break;
        case "assistant":
          if (e.payload.text.trim()) {
            out.push({ key: `a${e.seq}`, kind: "assistant", text: e.payload.text });
          }
          break;
        case "tool": {
          const step = stepById.get(e.payload.step);
          if (step) out.push({ key: `t${e.seq}`, kind: "tool", step });
          break;
        }
        case "compress":
          out.push({ key: `c${e.seq}`, kind: "compress", evicted: e.payload.evicted });
          break;
        case "done":
          out.push({ key: `d${e.seq}`, kind: "done", payload: e.payload });
          break;
        default:
          break;
      }
    }
    return out;
  }, [events, steps, task]);

  const plan = useMemo(() => {
    let latest: string | null = null;
    for (const e of events) if (e.kind === "plan") latest = e.payload.plan;
    return latest;
  }, [events]);

  const done = useMemo(() => {
    let latest: EventPayloads["done"] | null = null;
    for (const e of events) if (e.kind === "done") latest = e.payload;
    return latest;
  }, [events]);

  const status = useMemo<TaskStatus>(() => {
    // The stream beats the polled list, which can be three seconds stale.
    // `done` carries completion; a trailing status event (stopped/error) is
    // emitted after it and correctly wins.
    let latest: TaskStatus | null = null;
    for (const e of events) {
      if (e.kind === "status") latest = e.payload.state;
      else if (e.kind === "done") latest = e.payload.completed ? "complete" : "stopped";
    }
    if (latest === "running" && ended) return task?.status ?? "stopped";
    return latest ?? task?.status ?? "running";
  }, [events, ended, task?.status]);

  const statusDetail = useMemo(() => {
    let latest: string | null = null;
    for (const e of events) if (e.kind === "status") latest = e.payload.detail ?? null;
    return latest;
  }, [events]);

  return {
    events,
    items,
    steps,
    plan,
    done,
    status,
    statusDetail,
    ended,
    error,
    reconnect,
  };
}
