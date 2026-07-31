import { useEffect, useMemo, useState } from "react";
import { Download, FileIcon, Folder, Spinner, X } from "./Icons";
import { IconButton } from "./IconButton";
import { highlight } from "../lib/highlight";
import { api, type FileEntry } from "../lib/api";
import { fileName, formatBytes } from "../lib/format";
import { cx } from "../lib/ui";

const IMAGE = /\.(png|jpe?g|gif|webp|svg|avif)$/i;
const TEXTUAL =
  /\.(md|markdown|txt|json|jsonl|ya?ml|toml|ini|cfg|conf|csv|tsv|log|py|js|jsx|ts|tsx|sh|bash|html|css|sql|rs|go|java|rb|php|c|h|cpp|xml|env|gitignore)$/i;

type Props = {
  taskId: string;
  deliverables: string[];
  initialPath: string | null;
  onClose: () => void;
};

/** "All files in this task": the sandbox workdir, deliverables pinned on top,
 *  with a text or image preview and a download for anything else. */
export function FilesDrawer({ taskId, deliverables, initialPath, onClose }: Props) {
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showInternal, setShowInternal] = useState(false);
  const [selected, setSelected] = useState<string | null>(initialPath);

  useEffect(() => {
    let alive = true;
    api
      .listFiles(taskId)
      .then((r) => alive && setFiles(r.files))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [taskId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const visible = useMemo(
    () => (files ?? []).filter((f) => showInternal || !f.internal),
    [files, showInternal],
  );

  // Multi-tenant servers filter .opposable/ out of the listing entirely, so
  // there is nothing for the toggle to reveal and it should not be offered.
  const hasInternal = useMemo(() => (files ?? []).some((f) => f.internal), [files]);

  const pinned = useMemo(
    () => (files ?? []).filter((f) => deliverables.includes(f.path)),
    [files, deliverables],
  );

  const grouped = useMemo(() => {
    const dirs = new Map<string, FileEntry[]>();
    for (const f of visible) {
      const at = f.path.lastIndexOf("/");
      const dir = at === -1 ? "" : f.path.slice(0, at);
      const list = dirs.get(dir);
      if (list) list.push(f);
      else dirs.set(dir, [f]);
    }
    return [...dirs.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [visible]);

  return (
    <div className="fixed inset-0 z-30 flex justify-end" role="dialog" aria-label="Task files">
      <button
        type="button"
        aria-label="Close files"
        onClick={onClose}
        className="flex-1 bg-stone-900/25 backdrop-blur-[1px]"
      />
      <div className="flex h-full w-full max-w-[900px] flex-col border-l border-line bg-panel shadow-overlay">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4">
          <Folder size={17} className="text-muted" />
          <h2 className="flex-1 text-[13.5px] font-semibold">All files in this task</h2>
          {hasInternal && (
            <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-muted">
              <input
                type="checkbox"
                checked={showInternal}
                onChange={(e) => setShowInternal(e.target.checked)}
                className="accent-accent"
              />
              Show internal files
            </label>
          )}
          <IconButton label="Close files" onClick={onClose}>
            <X />
          </IconButton>
        </header>

        <div className="flex min-h-0 flex-1">
          <nav className="w-[290px] shrink-0 overflow-y-auto border-r border-line p-2">
            {error && <p className="px-2 py-3 text-[12.5px] text-err">{error}</p>}
            {!files && !error && (
              <p className="flex items-center gap-2 px-2 py-3 text-[12.5px] text-faint">
                <Spinner size={13} /> Loading…
              </p>
            )}

            {pinned.length > 0 && (
              <>
                <p className="px-2 pt-1 pb-1 text-[11px] font-semibold tracking-wide text-faint uppercase">
                  Deliverables
                </p>
                {pinned.map((f) => (
                  <FileRow
                    key={`d-${f.path}`}
                    file={f}
                    selected={selected === f.path}
                    onSelect={() => setSelected(f.path)}
                  />
                ))}
              </>
            )}

            {grouped.map(([dir, entries]) => (
              <div key={dir || "."} className="mt-2">
                <p className="truncate px-2 pb-1 font-mono text-[11px] text-faint" title={dir}>
                  {dir || "."}
                </p>
                {entries.map((f) => (
                  <FileRow
                    key={f.path}
                    file={f}
                    selected={selected === f.path}
                    onSelect={() => setSelected(f.path)}
                  />
                ))}
              </div>
            ))}

            {files && visible.length === 0 && (
              <p className="px-2 py-3 text-[12.5px] text-faint">No files yet.</p>
            )}
          </nav>

          <div className="min-w-0 flex-1">
            {selected ? (
              <Preview taskId={taskId} path={selected} />
            ) : (
              <p className="px-4 py-10 text-center text-[13px] text-faint">
                Pick a file to preview it.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function FileRow({
  file,
  selected,
  onSelect,
}: {
  file: FileEntry;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={file.path}
      className={cx(
        "flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-[12.5px] transition-colors",
        selected ? "bg-raised text-fg" : "text-muted hover:bg-raised/70",
      )}
    >
      <FileIcon size={13} className="shrink-0 text-faint" />
      <span className="min-w-0 flex-1 truncate font-mono">{fileName(file.path)}</span>
      <span className="shrink-0 text-[11px] text-faint">{formatBytes(file.size)}</span>
    </button>
  );
}

function Preview({ taskId, path }: { taskId: string; path: string }) {
  const url = api.fileUrl(taskId, path);
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "binary" | "error">("loading");

  useEffect(() => {
    if (IMAGE.test(path)) {
      setState("ready");
      setText(null);
      return;
    }
    if (!TEXTUAL.test(path)) {
      setState("binary");
      return;
    }
    let alive = true;
    setState("loading");
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
      .then((body) => {
        if (!alive) return;
        setText(body);
        setState("ready");
      })
      .catch(() => alive && setState("error"));
    return () => {
      alive = false;
    };
  }, [url, path]);

  const lines = text === null ? [] : highlight(text.replace(/\n$/, ""), path);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-raised px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={path}>
          {path}
        </span>
        <a
          href={url}
          download={fileName(path)}
          className="flex shrink-0 items-center gap-1.5 rounded-xl border border-line px-2 py-1 text-[11.5px] text-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          <Download size={13} />
          Download
        </a>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {state === "loading" && (
          <p className="flex items-center justify-center gap-2 px-4 py-10 text-[13px] text-faint">
            <Spinner size={14} /> Loading…
          </p>
        )}
        {state === "error" && (
          <p className="px-4 py-10 text-center text-[13px] text-err">Could not read this file.</p>
        )}
        {state === "binary" && (
          <p className="px-4 py-10 text-center text-[13px] text-faint">
            No preview for this file type — download it instead.
          </p>
        )}
        {state === "ready" && IMAGE.test(path) && (
          <div className="grid place-items-center p-6">
            <img src={url} alt={path} className="max-h-full max-w-full rounded-xl border border-line" />
          </div>
        )}
        {state === "ready" && text !== null && (
          <div className="font-mono text-[12px] leading-[1.55]">
            {lines.map((tokens, i) => (
              <div key={i} className="flex">
                <span className="w-10 shrink-0 pr-2 text-right text-faint select-none">{i + 1}</span>
                <span className="min-w-0 flex-1 pr-3 break-words whitespace-pre-wrap">
                  {tokens.map((t, j) => (
                    <span key={j} className={t.cls}>
                      {t.text}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
