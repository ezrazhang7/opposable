import { useState } from "react";
import { Composer } from "./Composer";
import { Play, StopFill } from "./Icons";
import { cx } from "../lib/ui";
import { api, type TaskStatus } from "../lib/api";

export type ControlAction = "message" | "stop" | "resume";

type Props = {
  taskId: string;
  status: TaskStatus;
  /** Called once the server accepts an action. A resume needs the caller to
   *  reopen the event stream; a message and a stop arrive on the open one. */
  onChanged: (action: ControlAction) => void;
};

/** The bottom of the chat column: send guidance to a running task, stop it,
 *  or pick a finished one back up. */
export function TaskControls({ taskId, status, onChanged }: Props) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = status === "running";

  const run = async (action: ControlAction, fn: () => Promise<unknown>, clear = false) => {
    setPending(true);
    setError(null);
    try {
      await fn();
      if (clear) setText("");
      onChanged(action);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  const submit = () =>
    run(
      running ? "message" : "resume",
      () => (running ? api.sendMessage(taskId, text) : api.resumeTask(taskId, text)),
      true,
    );

  return (
    <div className="shrink-0 border-t border-line px-4 pt-3 pb-4">
      <div className="mx-auto max-w-[720px]">
        {error && (
          <p className="mb-2 rounded-xl border border-line bg-err-soft px-3 py-2 text-[12.5px] text-err">
            {error}
          </p>
        )}
        <Composer
          value={text}
          onChange={setText}
          onSubmit={submit}
          pending={pending}
          minRows={1}
          maxHeight={180}
          submitLabel={running ? "Send guidance" : "Resume with this guidance"}
          placeholder={
            running
              ? "Send guidance while opposable works…"
              : "Add guidance and pick the task back up…"
          }
          rail={
            running ? (
              <button
                type="button"
                disabled={pending}
                onClick={() => run("stop", () => api.stopTask(taskId))}
                className={cx(
                  "flex items-center gap-1.5 rounded-xl border border-err/40 px-2.5 py-1.5 text-[12px] text-err transition-colors",
                  "hover:bg-err-soft focus-visible:ring-2 focus-visible:ring-err focus-visible:outline-none",
                  "disabled:pointer-events-none disabled:opacity-50",
                )}
              >
                <StopFill size={13} />
                Stop
              </button>
            ) : (
              <button
                type="button"
                disabled={pending}
                onClick={() => run("resume", () => api.resumeTask(taskId))}
                className={cx(
                  "flex items-center gap-1.5 rounded-xl border border-line px-2.5 py-1.5 text-[12px] text-muted transition-colors",
                  "hover:border-line-strong hover:text-fg focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
                  "disabled:pointer-events-none disabled:opacity-50",
                )}
              >
                <Play size={13} />
                Resume
              </button>
            )
          }
        />
      </div>
    </div>
  );
}
