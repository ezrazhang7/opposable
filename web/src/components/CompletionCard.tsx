import { AlertCircle, CheckCircle, FileIcon, Folder } from "./Icons";
import { Markdown } from "../lib/markdown";
import { fileName, summariseUsage } from "../lib/format";
import { cx } from "../lib/ui";
import type { EventPayloads } from "../lib/api";

type Props = {
  done: EventPayloads["done"];
  onOpenFile: (path: string) => void;
  onOpenFiles: () => void;
};

/** The end of a run: what happened, what it produced, what it cost. */
export function CompletionCard({ done, onOpenFile, onOpenFiles }: Props) {
  const usage = summariseUsage(done.usage ?? {});
  return (
    <section
      aria-label={done.completed ? "Task complete" : "Task stopped"}
      className={cx(
        "rounded-2xl border bg-panel p-4",
        done.completed ? "border-ok/35" : "border-line",
      )}
    >
      <header className="mb-2 flex items-center gap-2">
        {done.completed ? (
          <CheckCircle size={17} className="text-ok" />
        ) : (
          <AlertCircle size={17} className="text-muted" />
        )}
        <h2 className="text-[13.5px] font-semibold">
          {done.completed ? "Task complete" : "Task stopped"}
        </h2>
      </header>

      <Markdown text={done.summary} className="text-[13.5px] leading-relaxed" />

      {done.deliverables?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {done.deliverables.map((path) => (
            <button
              key={path}
              type="button"
              onClick={() => onOpenFile(path)}
              title={path}
              className="flex items-center gap-2 rounded-xl border border-line px-2.5 py-1.5 text-[12.5px] transition-colors hover:border-accent/60 hover:bg-accent-soft"
            >
              <FileIcon size={14} className="text-faint" />
              <span className="font-mono">{fileName(path)}</span>
            </button>
          ))}
        </div>
      )}

      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-2.5 text-[11.5px] text-faint">
        <span>
          {done.iterations} iteration{done.iterations === 1 ? "" : "s"}
        </span>
        {usage && <span>{usage}</span>}
        <button
          type="button"
          onClick={onOpenFiles}
          className="ml-auto flex items-center gap-1.5 text-muted transition-colors hover:text-fg"
        >
          <Folder size={13} />
          View all files in this task
        </button>
      </footer>
    </section>
  );
}
