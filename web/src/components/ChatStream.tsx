import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ActionChip } from "./ActionChip";
import { ArrowDown, Compress } from "./Icons";
import { cx } from "../lib/ui";
import type { ChatItem } from "../lib/useSession";

type Props = {
  items: ChatItem[];
  activeStep?: number | null;
  onSelectStep?: (step: number) => void;
};

const NEAR_BOTTOM_PX = 96;

export function ChatStream({ items, activeStep, onSelectStep }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setPinned(distance < NEAR_BOTTOM_PX);
  };

  // Follow the tail only while the reader is already there; scrolling up to
  // read something must not be yanked back by the next event.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && pinned) el.scrollTop = el.scrollHeight;
  }, [items, pinned]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const jump = () => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setPinned(true);
  };

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scroller} onScroll={onScroll} className="h-full overflow-y-auto px-4 py-5">
        <div className="mx-auto flex max-w-[720px] flex-col gap-3">
          {items.map((item) => {
            switch (item.kind) {
              case "user":
                return (
                  <div key={item.key} className="flex justify-end">
                    <p className="max-w-[85%] rounded-2xl bg-accent px-3.5 py-2.5 text-[13.5px] whitespace-pre-wrap text-accent-fg">
                      {item.text}
                    </p>
                  </div>
                );
              case "assistant":
                return (
                  <p
                    key={item.key}
                    className="max-w-[92%] text-[13.5px] leading-relaxed whitespace-pre-wrap"
                  >
                    {item.text}
                  </p>
                );
              case "tool":
                return (
                  <div key={item.key} className="max-w-full">
                    <ActionChip
                      step={item.step}
                      active={activeStep === item.step.step}
                      onClick={onSelectStep ? () => onSelectStep(item.step.step) : undefined}
                    />
                  </div>
                );
              case "compress":
                return (
                  <p
                    key={item.key}
                    className="flex items-center gap-1.5 text-[12px] text-faint"
                    title="Older observations were spilled to files in the sandbox and can be read back"
                  >
                    <Compress size={13} />
                    Compressed {item.evicted} observation{item.evicted === 1 ? "" : "s"} to disk
                  </p>
                );
              default:
                return null;
            }
          })}
        </div>
      </div>

      <button
        type="button"
        onClick={jump}
        className={cx(
          "absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-xl border border-line bg-panel px-3 py-1.5 text-[12.5px] shadow-overlay transition-opacity",
          pinned ? "pointer-events-none opacity-0" : "opacity-100",
        )}
      >
        <ArrowDown size={14} />
        Jump to latest
      </button>
    </div>
  );
}
