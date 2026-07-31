import { PanelRight, Terminal } from "./Icons";
import { IconButton } from "./IconButton";

type Props = { onClose: () => void };

/** "opposable's computer": header (tool + subtitle), body (per-tool renderer),
 *  footer (step scrubber + plan progress). Renderers land in steps 6–9. */
export function ComputerPanel({ onClose }: Props) {
  return (
    <aside
      aria-label="opposable's computer"
      className="flex h-full w-[44%] min-w-[360px] shrink-0 flex-col border-l border-line bg-panel"
    >
      <header className="flex h-14 items-center gap-3 border-b border-line px-4">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-raised text-muted">
          <Terminal />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">opposable's computer</p>
          <p className="truncate text-[12px] text-faint">idle</p>
        </div>
        <IconButton label="Hide computer panel" onClick={onClose}>
          <PanelRight />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <p className="px-4 py-10 text-center text-[13px] text-faint">
          Nothing running. Tool output appears here.
        </p>
      </div>

      <footer className="h-12 border-t border-line px-4" />
    </aside>
  );
}
