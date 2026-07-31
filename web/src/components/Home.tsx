import { useState } from "react";
import { Composer, RailSelect } from "./Composer";
import { cx } from "../lib/ui";
import { CATEGORIES, SUGGESTIONS, type Category } from "../lib/suggestions";
import type { Settings } from "../lib/settings";

type Props = {
  settings: Settings;
  onUpdateSettings: (patch: Partial<Settings>) => void;
  onStart: (task: string) => Promise<void>;
};

export function Home({ settings, onUpdateSettings, onStart }: Props) {
  const [text, setText] = useState("");
  const [category, setCategory] = useState<Category>("Research");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async (task: string) => {
    setPending(true);
    setError(null);
    try {
      await onStart(task);
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center px-6 py-10">
      <div className="w-full max-w-[720px]">
        <h1 className="mb-6 text-center text-[26px] font-semibold tracking-tight">
          What should opposable do?
        </h1>

        <Composer
          value={text}
          onChange={setText}
          onSubmit={() => void start(text)}
          pending={pending}
          autoFocus
          placeholder="Describe a task. opposable will plan it, work in a sandbox, and report back."
          rail={
            <>
              <RailSelect
                label="Model"
                value={settings.model}
                onChange={(model) => onUpdateSettings({ model })}
                options={settings.models.map((m) => ({ value: m, label: m }))}
              />
              <RailSelect
                label="Sandbox"
                value={settings.sandbox}
                onChange={(v) => onUpdateSettings({ sandbox: v as Settings["sandbox"] })}
                options={[
                  { value: "local", label: "Local" },
                  { value: "docker", label: "Docker" },
                ]}
              />
            </>
          }
        />

        {error && (
          <p className="mt-3 rounded-xl border border-line bg-err-soft px-3 py-2 text-[13px] text-err">
            {error}
          </p>
        )}

        <div className="mt-8">
          <div role="tablist" aria-label="Suggestion categories" className="flex justify-center gap-1">
            {CATEGORIES.map((c) => (
              <button
                key={c}
                role="tab"
                type="button"
                aria-selected={c === category}
                onClick={() => setCategory(c)}
                className={cx(
                  "rounded-xl px-3 py-1.5 text-[13px] transition-colors",
                  "focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
                  c === category ? "bg-raised font-medium text-fg" : "text-muted hover:text-fg",
                )}
              >
                {c}
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {SUGGESTIONS[category].map((s) => (
              <button
                key={s.label}
                type="button"
                title={s.task}
                disabled={pending}
                onClick={() => void start(s.task)}
                className={cx(
                  "rounded-xl border border-line bg-panel px-3 py-2 text-[13px] text-muted",
                  "transition-colors hover:border-line-strong hover:text-fg",
                  "focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-50",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
