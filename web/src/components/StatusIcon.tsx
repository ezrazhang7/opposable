import { AlertCircle, CheckCircle, HalfCircle } from "./Icons";
import type { TaskStatus } from "../lib/api";
import { cx } from "../lib/ui";

export const STATUS_LABEL: Record<TaskStatus, string> = {
  running: "Working",
  complete: "Complete",
  stopped: "Stopped",
  error: "Error",
};

/** Working = pulsing amber dot, complete = green check, stopped = half ring,
 *  error = red alert. Colour is reserved for exactly these four states. */
export function StatusIcon({ status, size = 16 }: { status: TaskStatus; size?: number }) {
  if (status === "running") {
    return (
      <span
        role="img"
        aria-label={STATUS_LABEL.running}
        title={STATUS_LABEL.running}
        className="pulse grid shrink-0 place-items-center"
        style={{ width: size, height: size }}
      >
        <span className="block rounded-full bg-warn" style={{ width: size * 0.55, height: size * 0.55 }} />
      </span>
    );
  }
  const Icon = status === "complete" ? CheckCircle : status === "error" ? AlertCircle : HalfCircle;
  return (
    <Icon
      size={size}
      role="img"
      aria-label={STATUS_LABEL[status]}
      className={cx(
        "shrink-0",
        status === "complete" && "text-ok",
        status === "error" && "text-err",
        status === "stopped" && "text-faint",
      )}
    />
  );
}
