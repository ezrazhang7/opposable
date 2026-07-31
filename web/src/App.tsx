import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ComputerPanel } from "./components/ComputerPanel";
import { IconButton } from "./components/IconButton";
import { PanelRight } from "./components/Icons";
import { StatusIcon, STATUS_LABEL } from "./components/StatusIcon";
import { useTheme } from "./lib/theme";
import { useTasks } from "./lib/useTasks";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { tasks, error } = useTasks();
  const selected = tasks.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="flex h-full overflow-hidden bg-bg text-fg">
      <Sidebar
        collapsed={railCollapsed}
        onToggleCollapse={() => setRailCollapsed((v) => !v)}
        theme={theme}
        onToggleTheme={toggleTheme}
        tasks={tasks}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNewTask={() => setSelectedId(null)}
      />

      <main className="flex min-w-0 flex-1">
        <section className="flex min-w-[420px] flex-1 flex-col">
          <header className="flex h-14 items-center gap-3 border-b border-line px-4">
            {selected ? (
              <>
                <StatusIcon status={selected.status} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium">{selected.title}</p>
                  <p className="truncate text-[11px] text-faint">
                    {STATUS_LABEL[selected.status]}
                    {selected.model ? ` · ${selected.model}` : ""}
                  </p>
                </div>
              </>
            ) : (
              <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-muted">
                No task selected
              </p>
            )}
            {!panelOpen && (
              <IconButton label="Show computer panel" onClick={() => setPanelOpen(true)}>
                <PanelRight />
              </IconButton>
            )}
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {error && (
              <p className="m-4 rounded-xl border border-line bg-err-soft px-3 py-2 text-[13px] text-err">
                Cannot reach the opposable server: {error}
              </p>
            )}
          </div>
        </section>

        {panelOpen && <ComputerPanel onClose={() => setPanelOpen(false)} />}
      </main>
    </div>
  );
}
