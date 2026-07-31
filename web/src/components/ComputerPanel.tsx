import { PanelRight, Terminal } from "./Icons";
import { IconButton } from "./IconButton";
import { EditorView } from "./renderers/EditorView";
import { ReaderView } from "./renderers/ReaderView";
import { TerminalView } from "./renderers/TerminalView";
import { Frame, Mono } from "./renderers/shared";
import { cx } from "../lib/ui";
import { KIND_ICON, KIND_LABEL, toolArg, toolKind, toolVerb, truncate } from "../lib/tools";
import type { Step } from "../lib/useSession";

type Props = {
  step: Step | null;
  /** True while the panel is pinned to whatever opposable is doing now. */
  live: boolean;
  onGoLive: () => void;
  onClose: () => void;
  raw: boolean;
  onToggleRaw: () => void;
};

/** "opposable's computer": what the agent is doing right now, or the step you
 *  picked out of the chat. The body switches renderer by tool prefix. */
export function ComputerPanel({ step, live, onGoLive, onClose, raw, onToggleRaw }: Props) {
  const kind = step ? toolKind(step.name) : "unknown";
  const Icon = step ? KIND_ICON[kind] : Terminal;
  const subtitle = step ? toolArg(step.name, step.args) || toolVerb(step.name) : "idle";

  return (
    <aside
      aria-label="opposable's computer"
      className="flex h-full w-[44%] min-w-[360px] shrink-0 flex-col border-l border-line bg-panel"
    >
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-raised text-muted">
          <Icon />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px]">
            {step ? (
              <>
                opposable is using <span className="font-semibold">{KIND_LABEL[kind]}</span>
              </>
            ) : (
              <span className="font-medium">opposable's computer</span>
            )}
          </p>
          <p className="truncate font-mono text-[11.5px] text-faint" title={subtitle}>
            {truncate(subtitle, 90)}
          </p>
        </div>
        {step && (
          <button
            type="button"
            onClick={onToggleRaw}
            title="Toggle the verbatim observation the model saw"
            className={cx(
              "shrink-0 rounded-xl border px-2 py-1 text-[11.5px] transition-colors",
              raw
                ? "border-accent/60 bg-accent-soft text-fg"
                : "border-line text-muted hover:border-line-strong",
            )}
          >
            Raw
          </button>
        )}
        <button
          type="button"
          onClick={onGoLive}
          disabled={live}
          title={live ? "Following the newest step" : "Jump back to the newest step"}
          className={cx(
            "flex shrink-0 items-center gap-1.5 rounded-xl border px-2 py-1 text-[11.5px] transition-colors",
            live
              ? "border-ok/40 bg-ok-soft text-ok"
              : "border-line text-muted hover:border-line-strong",
          )}
        >
          <span
            className={cx(
              "block h-1.5 w-1.5 rounded-full border border-current",
              live && "pulse bg-current",
            )}
          />
          Live
        </button>
        <IconButton label="Hide computer panel" onClick={onClose}>
          <PanelRight />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1">
        {!step ? (
          <p className="px-4 py-10 text-center text-[13px] text-faint">
            Nothing running. Tool output appears here.
          </p>
        ) : raw ? (
          <Frame bar={<span className="font-mono text-faint">observation · verbatim</span>}>
            <Mono>{step.observation ?? "(waiting for the tool to return)"}</Mono>
          </Frame>
        ) : (
          <StepBody step={step} />
        )}
      </div>

      <footer className="h-12 shrink-0 border-t border-line px-4" />
    </aside>
  );
}

function StepBody({ step }: { step: Step }) {
  switch (toolKind(step.name)) {
    case "terminal":
      return <TerminalView step={step} />;
    case "editor":
      return <EditorView step={step} />;
    case "reader":
      return <ReaderView step={step} />;
    default:
      return (
        <Frame bar={<span className="font-mono text-faint">{step.name}</span>}>
          <Mono>{step.observation ?? "(waiting for the tool to return)"}</Mono>
        </Frame>
      );
  }
}
