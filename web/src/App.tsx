import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ComputerPanel } from "./components/ComputerPanel";
import { IconButton } from "./components/IconButton";
import { PanelRight } from "./components/Icons";
import { useTheme } from "./lib/theme";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);

  return (
    <div className="flex h-full overflow-hidden bg-bg text-fg">
      <Sidebar
        collapsed={railCollapsed}
        onToggleCollapse={() => setRailCollapsed((v) => !v)}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="flex min-w-0 flex-1">
        <section className="flex min-w-[420px] flex-1 flex-col">
          <header className="flex h-14 items-center gap-3 border-b border-line px-4">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-muted">No task selected</p>
            </div>
            {!panelOpen && (
              <IconButton label="Show computer panel" onClick={() => setPanelOpen(true)}>
                <PanelRight />
              </IconButton>
            )}
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto" />
        </section>

        {panelOpen && <ComputerPanel onClose={() => setPanelOpen(false)} />}
      </main>
    </div>
  );
}
