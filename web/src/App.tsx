import { useEffect, useState } from "react";
import { ChatStream } from "./components/ChatStream";
import { ComputerPanel } from "./components/ComputerPanel";
import { Home } from "./components/Home";
import { IconButton } from "./components/IconButton";
import { PanelRight } from "./components/Icons";
import { Sidebar } from "./components/Sidebar";
import { StatusIcon, STATUS_LABEL } from "./components/StatusIcon";
import { api } from "./lib/api";
import { taskParams, useSettings } from "./lib/settings";
import { useTheme } from "./lib/theme";
import { useSession } from "./lib/useSession";
import { useTasks } from "./lib/useTasks";

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [settings, updateSettings] = useSettings();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [pickedStep, setPickedStep] = useState<number | null>(null);
  const [live, setLive] = useState(true);
  const [raw, setRaw] = useState(false);

  const { tasks, error, refresh } = useTasks();
  const selected = tasks.find((t) => t.id === selectedId) ?? null;
  const session = useSession(selected);

  // A different task means a different timeline: follow its newest step.
  useEffect(() => {
    setPickedStep(null);
    setLive(true);
    setRaw(false);
  }, [selectedId]);

  const newestStep = session.steps.length ? session.steps[session.steps.length - 1].step : null;
  const activeStep = live ? newestStep : pickedStep;
  const shownStep = session.steps.find((s) => s.step === activeStep) ?? null;

  const selectStep = (step: number) => {
    setPickedStep(step);
    setLive(false);
  };

  const startTask = async (task: string) => {
    const created = await api.createTask({ task, ...taskParams(settings) });
    setSelectedId(created.id);
    await refresh();
  };

  const status = selected ? session.status : null;

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
            {selected && status ? (
              <>
                <StatusIcon status={status} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium">{selected.title}</p>
                  <p className="truncate text-[11px] text-faint">
                    {STATUS_LABEL[status]}
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

          {error && (
            <p className="m-4 rounded-xl border border-line bg-err-soft px-3 py-2 text-[13px] text-err">
              Cannot reach the opposable server: {error}
            </p>
          )}

          {selected ? (
            <ChatStream
              items={session.items}
              activeStep={activeStep}
              onSelectStep={selectStep}
            />
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <Home settings={settings} onUpdateSettings={updateSettings} onStart={startTask} />
            </div>
          )}
        </section>

        {panelOpen && (
          <ComputerPanel
            step={shownStep}
            plan={session.plan}
            live={live}
            onGoLive={() => setLive(true)}
            onClose={() => setPanelOpen(false)}
            raw={raw}
            onToggleRaw={() => setRaw((v) => !v)}
          />
        )}
      </main>
    </div>
  );
}
