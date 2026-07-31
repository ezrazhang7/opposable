import { Logo, Moon, PanelLeft, Plus, Search, Settings, Sun } from "./Icons";
import { IconButton } from "./IconButton";
import { cx } from "../lib/ui";
import type { Theme } from "../lib/theme";

type Props = {
  collapsed: boolean;
  onToggleCollapse: () => void;
  theme: Theme;
  onToggleTheme: () => void;
};

/** Left rail: identity, new-task, filter, session list, and the two global
 *  toggles pinned to the bottom. Sessions arrive in step 3. */
export function Sidebar({ collapsed, onToggleCollapse, theme, onToggleTheme }: Props) {
  return (
    <nav
      aria-label="Sessions"
      className={cx(
        "flex h-full shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-200",
        collapsed ? "w-14" : "w-[260px]",
      )}
    >
      <div
        className={cx(
          "flex h-14 items-center gap-2 px-3",
          collapsed && "justify-center px-0",
        )}
      >
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <Logo size={18} />
        </span>
        {!collapsed && (
          <>
            <span className="flex-1 truncate text-[15px] font-semibold tracking-tight">
              opposable
            </span>
            <IconButton label="Collapse sidebar" onClick={onToggleCollapse}>
              <PanelLeft />
            </IconButton>
          </>
        )}
      </div>

      <div className={cx("px-3 pb-3", collapsed && "px-2")}>
        <button
          type="button"
          className={cx(
            "flex h-9 w-full items-center gap-2 rounded-xl bg-accent px-3 text-[13px] font-medium text-accent-fg",
            "transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-panel focus-visible:outline-none",
            collapsed && "justify-center px-0",
          )}
          title="New task"
        >
          <Plus />
          {!collapsed && <span>New task</span>}
        </button>
      </div>

      {!collapsed && (
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-faint" />
            <input
              type="search"
              placeholder="Search tasks"
              className="h-8 w-full rounded-xl border border-line bg-bg pr-2 pl-8 text-[13px] placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {!collapsed && (
          <p className="px-1 py-6 text-center text-[13px] text-faint">No tasks yet.</p>
        )}
      </div>

      <div
        className={cx(
          "flex items-center gap-1 border-t border-line px-3 py-2",
          collapsed && "flex-col px-2",
        )}
      >
        {collapsed && (
          <IconButton label="Expand sidebar" onClick={onToggleCollapse}>
            <PanelLeft />
          </IconButton>
        )}
        <IconButton
          label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          onClick={onToggleTheme}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </IconButton>
        <IconButton label="Settings">
          <Settings />
        </IconButton>
      </div>
    </nav>
  );
}
