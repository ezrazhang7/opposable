import { StatusIcon, STATUS_LABEL } from "./StatusIcon";
import { cx } from "../lib/ui";
import type { TaskStatus } from "../lib/api";

const TONE: Record<TaskStatus, string> = {
  running: "border-warn/40 bg-warn-soft text-warn",
  complete: "border-ok/40 bg-ok-soft text-ok",
  stopped: "border-line bg-raised text-muted",
  error: "border-err/40 bg-err-soft text-err",
};

export function StatusBadge({ status, detail }: { status: TaskStatus; detail?: string }) {
  return (
    <span
      title={detail}
      className={cx(
        "flex shrink-0 items-center gap-1.5 rounded-xl border px-2 py-1 text-[11.5px]",
        TONE[status],
      )}
    >
      <StatusIcon status={status} size={13} />
      {STATUS_LABEL[status]}
    </span>
  );
}
