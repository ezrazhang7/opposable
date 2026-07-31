/** todo.md is the agent's plan of record. It is plain markdown, so the UI
 *  parses exactly what the model wrote — checkboxes, headings, and stray
 *  prose all survive the round trip. */

export type PlanLine =
  | { kind: "item"; text: string; done: boolean; depth: number }
  | { kind: "heading"; text: string }
  | { kind: "text"; text: string };

export type Plan = { lines: PlanLine[]; done: number; total: number };

const ITEM = /^(\s*)(?:[-*+]|\d+\.)\s+\[([ xX])\]\s*(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;

export function parsePlan(markdown: string | null): Plan {
  if (!markdown) return { lines: [], done: 0, total: 0 };
  const lines: PlanLine[] = [];
  let done = 0;
  let total = 0;
  for (const raw of markdown.split("\n")) {
    const item = ITEM.exec(raw);
    if (item) {
      const checked = item[2].toLowerCase() === "x";
      total += 1;
      if (checked) done += 1;
      lines.push({
        kind: "item",
        text: item[3].trim(),
        done: checked,
        depth: Math.min(2, Math.floor(item[1].length / 2)),
      });
      continue;
    }
    const heading = HEADING.exec(raw);
    if (heading) {
      lines.push({ kind: "heading", text: heading[1].trim() });
      continue;
    }
    if (raw.trim()) lines.push({ kind: "text", text: raw.trim() });
  }
  return { lines, done, total };
}
