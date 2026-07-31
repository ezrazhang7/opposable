import type { Usage } from "./api";

export function compactNumber(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Providers name their token counters differently; the completion card only
 *  needs the two totals a reader cares about, plus cache reads when present. */
export function summariseUsage(usage: Usage): string | null {
  const input = usage.input_tokens ?? usage.prompt_tokens ?? 0;
  const output = usage.output_tokens ?? usage.completion_tokens ?? 0;
  const cached = usage.cache_read_input_tokens ?? 0;
  if (!input && !output && !cached) return null;
  const parts = [`${compactNumber(input)} in`, `${compactNumber(output)} out`];
  if (cached) parts.push(`${compactNumber(cached)} cached`);
  return parts.join(" · ");
}

export function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}
