import { useEffect, useState } from "react";
import { IconButton } from "./IconButton";
import { X } from "./Icons";
import { cx } from "../lib/ui";
import { DEFAULT_SETTINGS, type Settings } from "../lib/settings";

type Props = {
  settings: Settings;
  onUpdate: (patch: Partial<Settings>) => void;
  onClose: () => void;
};

/** Defaults for new tasks. They live in localStorage and travel with each
 *  create request, so the server keeps no per-user state. */
export function SettingsModal({ settings, onUpdate, onClose }: Props) {
  const [models, setModels] = useState(settings.models.join(", "));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const commitModels = () => {
    const list = models
      .split(",")
      .map((m) => m.trim())
      .filter(Boolean);
    if (!list.length) {
      setModels(settings.models.join(", "));
      return;
    }
    onUpdate({ models: list, model: list.includes(settings.model) ? settings.model : list[0] });
  };

  return (
    <div className="fixed inset-0 z-40 grid place-items-center p-4" role="dialog" aria-label="Settings">
      <button
        type="button"
        aria-label="Close settings"
        onClick={onClose}
        className="absolute inset-0 bg-stone-900/30 backdrop-blur-[1px]"
      />
      <div className="relative w-full max-w-[520px] rounded-2xl border border-line bg-panel shadow-overlay">
        <header className="flex h-14 items-center gap-3 border-b border-line px-4">
          <h2 className="flex-1 text-[13.5px] font-semibold">Settings</h2>
          <IconButton label="Close settings" onClick={onClose}>
            <X />
          </IconButton>
        </header>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-4">
          <Field
            label="Models"
            hint="Comma-separated. The composer picks from this list; the first is the default."
          >
            <input
              value={models}
              onChange={(e) => setModels(e.target.value)}
              onBlur={commitModels}
              className={inputClass}
            />
          </Field>

          <Field label="Base URL" hint="An OpenAI-compatible endpoint. Empty means the Anthropic API.">
            <input
              value={settings.baseUrl}
              placeholder="http://localhost:11434/v1"
              onChange={(e) => onUpdate({ baseUrl: e.target.value.trim() })}
              className={inputClass}
            />
          </Field>

          <Field label="Sandbox" hint="Where tools run. Docker needs an image on this machine.">
            <select
              value={settings.sandbox}
              onChange={(e) => onUpdate({ sandbox: e.target.value as Settings["sandbox"] })}
              className={inputClass}
            >
              <option value="local">Local</option>
              <option value="docker">Docker</option>
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Max iterations" hint="Hard stop for a single run.">
              <input
                type="number"
                min={1}
                max={500}
                value={settings.maxIterations}
                onChange={(e) => onUpdate({ maxIterations: clamp(e.target.value, 1, 500, 60) })}
                className={inputClass}
              />
            </Field>
            <Field label="Budget tokens" hint="Context size before observations spill to disk.">
              <input
                type="number"
                min={1000}
                step={1000}
                value={settings.budgetTokens}
                onChange={(e) =>
                  onUpdate({ budgetTokens: clamp(e.target.value, 1000, 1_000_000, 60_000) })
                }
                className={inputClass}
              />
            </Field>
          </div>
        </div>

        <footer className="flex items-center gap-3 border-t border-line px-4 py-3">
          <p className="flex-1 text-[11.5px] text-faint">Saved as you type, in this browser.</p>
          <button
            type="button"
            onClick={() => {
              onUpdate(DEFAULT_SETTINGS);
              setModels(DEFAULT_SETTINGS.models.join(", "));
            }}
            className="rounded-xl border border-line px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            Reset to defaults
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-accent px-3 py-1.5 text-[12px] font-medium text-accent-fg transition-colors hover:bg-accent-hover"
          >
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}

const inputClass = cx(
  "h-9 w-full rounded-xl border border-line bg-bg px-2.5 text-[13px]",
  "placeholder:text-faint focus:border-accent focus:outline-none",
);

function clamp(raw: string, min: number, max: number, fallback: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.round(n)));
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium">{label}</span>
      {children}
      <span className="mt-1 block text-[11.5px] text-faint">{hint}</span>
    </label>
  );
}
