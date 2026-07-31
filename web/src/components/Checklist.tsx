import { Check, Square } from "./Icons";
import { cx } from "../lib/ui";
import type { Plan } from "../lib/plan";

/** The plan, rendered the way the model wrote it. Shared by the progress
 *  popover and the computer panel's plan_ renderer. */
export function Checklist({ plan, className }: { plan: Plan; className?: string }) {
  if (!plan.lines.length) {
    return <p className={cx("text-[12.5px] text-faint", className)}>No plan yet.</p>;
  }
  return (
    <ul className={cx("space-y-1", className)}>
      {plan.lines.map((line, i) => {
        if (line.kind === "heading") {
          return (
            <li key={i} className="pt-1.5 pb-0.5 text-[12px] font-semibold text-muted">
              {line.text}
            </li>
          );
        }
        if (line.kind === "text") {
          return (
            <li key={i} className="text-[12.5px] text-faint">
              {line.text}
            </li>
          );
        }
        return (
          <li
            key={i}
            className="flex items-start gap-2 text-[12.5px]"
            style={{ paddingLeft: line.depth * 14 }}
          >
            <span className="mt-0.5 shrink-0">
              {line.done ? (
                <Check size={13} className="text-ok" aria-label="done" />
              ) : (
                <Square size={13} className="text-faint" aria-label="not done" />
              )}
            </span>
            <span className={cx("min-w-0", line.done ? "text-muted line-through" : "text-fg")}>
              {line.text}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
