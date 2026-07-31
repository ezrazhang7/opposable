import { useCallback, useState } from "react";

export type Settings = {
  /** Models offered by the composer's picker; the first is the default. */
  models: string[];
  model: string;
  baseUrl: string;
  sandbox: "local" | "docker";
  maxIterations: number;
  budgetTokens: number;
};

/** Mirrors the CLI's defaults so the UI and `opposable run` behave alike. */
export const DEFAULT_SETTINGS: Settings = {
  models: ["claude-sonnet-4-6"],
  model: "claude-sonnet-4-6",
  baseUrl: "",
  sandbox: "local",
  maxIterations: 60,
  budgetTokens: 60_000,
};

const KEY = "opposable.settings";

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const saved = JSON.parse(raw) as Partial<Settings>;
    const merged = { ...DEFAULT_SETTINGS, ...saved };
    // A model removed from the list must not stay selected.
    if (!merged.models.includes(merged.model)) merged.model = merged.models[0] ?? "";
    return merged;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function useSettings(): [Settings, (patch: Partial<Settings>) => void] {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      localStorage.setItem(KEY, JSON.stringify(next));
      return next;
    });
  }, []);
  return [settings, update];
}

/** The per-task overrides a create request carries. */
export function taskParams(settings: Settings) {
  return {
    model: settings.model || undefined,
    base_url: settings.baseUrl || undefined,
    sandbox: settings.sandbox,
    max_iterations: settings.maxIterations,
    budget_tokens: settings.budgetTokens,
  };
}
