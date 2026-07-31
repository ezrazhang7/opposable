import { AlertCircle, Check, Spinner } from "./Icons";
import { cx } from "../lib/ui";
import { KIND_ICON, isFailure, toolArg, toolKind, toolVerb, truncate } from "../lib/tools";
import type { Step } from "../lib/useSession";

type Props = {
  step: Step;
  active?: boolean;
  onClick?: () => void;
};

/** The compact "what opposable is doing" chip in the chat stream: icon, verb,
 *  truncated argument, and a spinner that resolves to a check — or, when the
 *  tool failed, an amber tint and a TOOL ERROR badge that stays put. */
export function ActionChip({ step, active, onClick }: Props) {
  const kind = toolKind(step.name);
  const Icon = KIND_ICON[kind];
  const running = step.observation === undefined;
  const failed = isFailure(step.observation);
  const arg = toolArg(step.name, step.args);

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      aria-current={active ? "true" : undefined}
      title={arg || toolVerb(step.name)}
      className={cx(
        "flex max-w-full items-center gap-2 rounded-xl border px-2.5 py-1.5 text-left text-[12.5px] transition-colors",
        onClick && "cursor-pointer",
        failed
          ? "border-warn/40 bg-warn-soft text-fg"
          : "border-line bg-panel text-muted hover:border-line-strong",
        active && !failed && "border-accent/60 bg-accent-soft",
        running && "pulse",
      )}
    >
      <Icon className={cx("shrink-0", failed ? "text-warn" : "text-faint")} />
      <span className="shrink-0 font-medium text-fg">{toolVerb(step.name)}</span>
      {arg && (
        <span className="truncate font-mono text-[11.5px] text-muted">{truncate(arg, 72)}</span>
      )}
      {failed && (
        <span className="shrink-0 rounded-md bg-warn/15 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-warn uppercase">
          Tool error
        </span>
      )}
      <span className="ml-auto shrink-0 pl-1 text-faint">
        {running ? (
          <Spinner size={13} />
        ) : failed ? (
          <AlertCircle size={13} className="text-warn" />
        ) : (
          <Check size={13} className="text-ok" />
        )}
      </span>
    </button>
  );
}
