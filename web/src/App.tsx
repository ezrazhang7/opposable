import { useEffect, useState } from "react";

type Health = { ok: boolean; count: number } | { error: string } | null;

/** Scaffold placeholder: proves the bundle mounts and the API is reachable
 *  through both the dev proxy and the Python server's static handler. */
export default function App() {
  const [health, setHealth] = useState<Health>(null);

  useEffect(() => {
    fetch("/api/tasks")
      .then((r) => r.json())
      .then((tasks) => setHealth({ ok: true, count: tasks.length }))
      .catch((e) => setHealth({ error: String(e) }));
  }, []);

  return (
    <div className="grid h-full place-items-center bg-stone-50 text-stone-900 dark:bg-stone-950 dark:text-stone-100">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">opposable</h1>
        <p className="mt-2 font-mono text-sm text-stone-500" data-testid="health">
          {health === null
            ? "checking api…"
            : "ok" in health
              ? `api ok — ${health.count} session(s)`
              : `api unreachable: ${health.error}`}
        </p>
      </div>
    </div>
  );
}
