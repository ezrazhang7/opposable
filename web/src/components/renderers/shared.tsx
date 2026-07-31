import type { ReactNode } from "react";
import { Spinner } from "../Icons";
import { cx } from "../../lib/ui";

/** Every renderer shares the same skeleton: a thin bar naming the subject,
 *  then a scrollable body. */
export function Frame({ bar, children }: { bar?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {bar && (
        <div className="flex shrink-0 items-center gap-2 border-b border-line bg-raised px-3 py-2 text-[12px]">
          {bar}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <pre
      className={cx(
        "px-3 py-2.5 font-mono text-[12px] leading-[1.55] break-words whitespace-pre-wrap",
        className,
      )}
    >
      {children}
    </pre>
  );
}

export function Running({ label }: { label: string }) {
  return (
    <p className="flex items-center justify-center gap-2 px-4 py-10 text-[13px] text-faint">
      <Spinner size={14} />
      {label}
    </p>
  );
}

export function ExitBadge({ code }: { code: number }) {
  return (
    <span
      className={cx(
        "shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[11px]",
        code === 0 ? "bg-ok-soft text-ok" : "bg-err-soft text-err",
      )}
    >
      exit {code}
    </span>
  );
}
