import { useMemo, useState } from "react";
import { Logo, Moon, PanelLeft, Plus, Search, Settings, Sun } from "./Icons";
import { IconButton } from "./IconButton";
import { StatusIcon, STATUS_LABEL } from "./StatusIcon";
import { cx } from "../lib/ui";
import { relativeTime } from "../lib/time";
import type { TaskMeta } from "../lib/api";
import type { Theme } from "../lib/theme";

type Props = {
  collapsed: boolean;
  onToggleCollapse: () => void;
  theme: Theme;
  onToggleTheme: () => void;
  tasks: TaskMeta[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNewTask: () => void;
  onOpenSettings?: () => void;
};

export function Sidebar({
  collapsed,
  onToggleCollapse,
  theme,
  onToggleTheme,
  tasks,
  selectedId,
  onSelect,
  onNewTask,
  onOpenSettings,
}: Props) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) => (t.title + " " + t.task).toLowerCase().includes(q));
  }, [tasks, query]);

  return (
    <nav
      aria-label="Sessions"
      className={cx(
        "flex h-full shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-200",
        collapsed ? "w-14" : "w-[260px]",
      )}
    >
      <div className={cx("flex h-14 items-center gap-2 px-3", collapsed && "justify-center px-0")}>
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
          onClick={onNewTask}
          title="New task"
          className={cx(
            "flex h-9 w-full items-center gap-2 rounded-xl bg-accent px-3 text-[13px] font-medium text-accent-fg",
            "transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-panel focus-visible:outline-none",
            collapsed && "justify-center px-0",
          )}
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
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tasks"
              aria-label="Search tasks"
              className="h-8 w-full rounded-xl border border-line bg-bg pr-2 pl-8 text-[13px] placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      )}

      <ul
        className={cx(
          "min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-2",
          collapsed ? "flex flex-col items-center px-2" : "px-3",
        )}
      >
        {visible.map((task) => (
          <li key={task.id} className={collapsed ? "" : "w-full"}>
            <button
              type="button"
              onClick={() => onSelect(task.id)}
              aria-current={task.id === selectedId ? "true" : undefined}
              title={collapsed ? `${task.title} — ${STATUS_LABEL[task.status]}` : undefined}
              className={cx(
                "flex items-center rounded-xl text-left transition-colors",
                "focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
                collapsed
                  ? "h-9 w-9 justify-center"
                  : "w-full gap-2.5 px-2.5 py-2",
                task.id === selectedId ? "bg-raised" : "hover:bg-raised/70",
              )}
            >
              <StatusIcon status={task.status} />
              {!collapsed && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] leading-tight">{task.title}</span>
                  <span className="block truncate text-[11px] text-faint">
                    {relativeTime(task.created)}
                  </span>
                </span>
              )}
            </button>
          </li>
        ))}
        {!collapsed && visible.length === 0 && (
          <li className="px-1 py-6 text-center text-[13px] text-faint">
            {tasks.length === 0 ? "No tasks yet." : "No matches."}
          </li>
        )}
      </ul>

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
        <IconButton label="Settings" onClick={onOpenSettings}>
          <Settings />
        </IconButton>
      </div>
    </nav>
  );
}
