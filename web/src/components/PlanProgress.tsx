import { useEffect, useRef, useState } from "react";
import { Checklist } from "./Checklist";
import { ChevronDown, ListChecks } from "./Icons";
import { cx } from "../lib/ui";
import { parsePlan } from "../lib/plan";

/** "Task progress 3/7" in the panel footer, expanding to the checklist. */
export function PlanProgress({ plan }: { plan: string | null }) {
  const parsed = parsePlan(plan);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!parsed.total) {
    return <span className="text-[12px] text-faint">No plan yet</span>;
  }

  const pct = Math.round((parsed.done / parsed.total) * 100);

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cx(
          "flex items-center gap-2 rounded-xl border px-2.5 py-1 text-[12px] transition-colors",
          "focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
          open ? "border-accent/60 bg-accent-soft" : "border-line hover:border-line-strong",
        )}
      >
        <ListChecks size={14} className="text-faint" />
        <span className="text-muted">Task progress</span>
        <span className="font-mono text-fg">
          {parsed.done}/{parsed.total}
        </span>
        <span className="h-1 w-10 overflow-hidden rounded-full bg-line">
          <span
            className={cx("block h-full rounded-full", pct === 100 ? "bg-ok" : "bg-accent")}
            style={{ width: `${pct}%` }}
          />
        </span>
        <ChevronDown size={13} className={cx("text-faint transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 bottom-full z-10 mb-2 max-h-[55vh] w-[330px] overflow-auto rounded-2xl border border-line bg-panel p-3 shadow-overlay">
          <Checklist plan={parsed} />
        </div>
      )}
    </div>
  );
}
