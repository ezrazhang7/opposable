import { Frame, Mono, Running } from "./shared";
import type { Step } from "../../lib/useSession";

const STRIPPED = /^\[HTML stripped to text; raw page saved to (.+?)\]\n+/;

/** web_ tools: a URL bar over the extracted page text. The engine strips
 *  markup before the model ever sees it and keeps the raw HTML on disk, so
 *  the panel says where that copy lives. */
export function ReaderView({ step }: { step: Step }) {
  const url = typeof step.args.url === "string" ? step.args.url : "";
  const bar = (
    <span className="min-w-0 flex-1 truncate font-mono text-fg" title={url}>
      {url || step.name}
    </span>
  );

  if (step.observation === undefined) {
    return (
      <Frame bar={bar}>
        <Running label="Fetching…" />
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

  const match = STRIPPED.exec(step.observation);
  const rawPath = match?.[1];
  const body = match ? step.observation.slice(match[0].length) : step.observation;

  return (
    <Frame bar={bar}>
      {rawPath && (
        <p
          title={rawPath}
          className="truncate border-b border-line px-3 py-1.5 font-mono text-[11px] text-faint"
        >
          markup stripped · raw page saved to {rawPath}
        </p>
      )}
      <div className="px-4 py-3 text-[13px] leading-relaxed whitespace-pre-wrap">{body}</div>
    </Frame>
  );
}
