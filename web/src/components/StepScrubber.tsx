import { useEffect } from "react";
import { ChevronLeft, ChevronRight, Pause, Play } from "./Icons";
import { IconButton } from "./IconButton";
import { cx } from "../lib/ui";
import type { Step } from "../lib/useSession";

const AUTOPLAY_MS = 500; // ~2 steps a second

type Props = {
  steps: Step[];
  activeStep: number | null;
  onSelect: (step: number) => void;
  live: boolean;
  onGoLive: () => void;
  /** Autoplay only makes sense once the timeline has stopped growing. */
  replayable: boolean;
  playing: boolean;
  onSetPlaying: (playing: boolean) => void;
};

/** `◀ ▶ ——●—— [Live]`: walk the session's steps, or hand control back to the
 *  live tail. On a finished session the play button replays it. */
export function StepScrubber({
  steps,
  activeStep,
  onSelect,
  live,
  onGoLive,
  replayable,
  playing,
  onSetPlaying,
}: Props) {
  const index = steps.findIndex((s) => s.step === activeStep);
  const last = steps.length - 1;
  const atEnd = index >= last;

  useEffect(() => {
    if (!playing) return;
    if (!steps.length || atEnd) {
      onSetPlaying(false);
      return;
    }
    const timer = setTimeout(() => onSelect(steps[index + 1].step), AUTOPLAY_MS);
    return () => clearTimeout(timer);
  }, [playing, index, atEnd, steps, onSelect, onSetPlaying]);

  const go = (next: number) => {
    const clamped = Math.max(0, Math.min(last, next));
    if (steps[clamped]) onSelect(steps[clamped].step);
  };

  const disabled = steps.length === 0;

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <IconButton
        label="Previous step"
        disabled={disabled || index <= 0}
        onClick={() => go(index - 1)}
      >
        <ChevronLeft />
      </IconButton>
      <IconButton
        label="Next step"
        disabled={disabled || atEnd}
        onClick={() => go(index + 1)}
      >
        <ChevronRight />
      </IconButton>

      <input
        type="range"
        min={0}
        max={Math.max(0, last)}
        value={index < 0 ? 0 : index}
        disabled={disabled}
        aria-label="Step"
        onChange={(e) => go(Number(e.target.value))}
        className="accent-accent min-w-0 flex-1 cursor-pointer disabled:cursor-default disabled:opacity-40"
      />

      <span className="shrink-0 font-mono text-[11.5px] text-faint tabular-nums">
        {disabled ? "0/0" : `${index + 1}/${steps.length}`}
      </span>

      {replayable && (
        <IconButton
          label={playing ? "Pause replay" : "Replay steps"}
          disabled={disabled}
          onClick={() => {
            if (!playing && atEnd) go(0);
            onSetPlaying(!playing);
          }}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </IconButton>
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
    </div>
  );
}
