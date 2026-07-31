import { Frame, Mono, Running } from "./shared";
import { highlight } from "../../lib/highlight";
import { cx } from "../../lib/ui";
import type { Step } from "../../lib/useSession";

/** file_ tools. A write shows the content it just put on disk, gutter-marked
 *  as added lines (the engine gives us the new text, never the old); a read
 *  shows what came back. Both get a path header and light highlighting. */
export function EditorView({ step }: { step: Step }) {
  const path = typeof step.args.path === "string" ? step.args.path : "";
  const isWrite = step.name === "file_write";
  const content = isWrite
    ? typeof step.args.content === "string"
      ? step.args.content
      : ""
    : (step.observation ?? "");

  const bar = (
    <>
      <span className="min-w-0 flex-1 truncate font-mono text-fg" title={path}>
        {path || step.name}
      </span>
      <span className="shrink-0 text-faint">{isWrite ? "written" : "read"}</span>
    </>
  );

  if (step.observation === undefined) {
    return (
      <Frame bar={bar}>
        <Running label={isWrite ? "Writing…" : "Reading…"} />
      </Frame>
    );
  }

  if (step.observation.startsWith("TOOL ERROR")) {
    return (
      <Frame bar={bar}>
        <Mono className="text-err">{step.observation}</Mono>
      </Frame>
    );
  }

  const lines = highlight(content.replace(/\n$/, ""), path);

  return (
    <Frame bar={bar}>
      <div className="font-mono text-[12px] leading-[1.55]">
        {lines.map((tokens, i) => (
          <div key={i} className={cx("flex", isWrite && "bg-ok-soft/35")}>
            <span className="w-10 shrink-0 pr-2 text-right text-faint select-none">{i + 1}</span>
            {isWrite && <span className="w-3 shrink-0 text-ok select-none">+</span>}
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
      {isWrite && (
        <p
          title={step.observation}
          className="truncate border-t border-line px-3 py-2 text-[12px] text-faint"
        >
          {step.observation}
        </p>
      )}
    </Frame>
  );
}
