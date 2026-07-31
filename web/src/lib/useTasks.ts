import { useCallback, useEffect, useState } from "react";
import { api, type TaskMeta } from "./api";

/** The session list. Polled rather than streamed: statuses change at most once
 *  per task, and a 3s poll is cheaper than a second SSE channel. */
export function useTasks(pollMs = 3000) {
  const [tasks, setTasks] = useState<TaskMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setTasks(await api.listTasks());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), pollMs);
    return () => clearInterval(timer);
  }, [refresh, pollMs]);

  return { tasks, error, refresh };
}
