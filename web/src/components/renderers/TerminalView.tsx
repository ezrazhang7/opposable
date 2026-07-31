import { ExitBadge, Frame, Mono, Running } from "./shared";
import { parseShell } from "../../lib/tools";
import type { Step } from "../../lib/useSession";

/** shell_ tools: the command, an exit-code badge, stdout in mono, and stderr
 *  tinted so a failure reads at a glance without opening the raw output. */
export function TerminalView({ step }: { step: Step }) {
  const command = typeof step.args.command === "string" ? step.args.command : "";

  if (step.observation === undefined) {
    return (
      <Frame bar={<Command text={command} />}>
        <Running label="Running…" />
      </Frame>
    );
  }

  if (step.observation.startsWith("TOOL ERROR")) {
    return (
      <Frame bar={<Command text={command} />}>
        <Mono className="text-err">{step.observation}</Mono>
      </Frame>
    );
  }

  const { code, stdout, stderr } = parseShell(step.observation);
  const empty = !stdout.trim() && !stderr.trim();

  return (
    <Frame
      bar={
        <>
          <Command text={command} />
          {code !== null && <ExitBadge code={code} />}
        </>
      }
    >
      {empty ? (
        <p className="px-3 py-6 text-center text-[12.5px] text-faint">no output</p>
      ) : (
        <>
          {stdout.trim() && <Mono>{stdout.replace(/\n+$/, "")}</Mono>}
          {stderr.trim() && (
            <div className="border-t border-line bg-err-soft/40">
              <p className="px-3 pt-2 text-[10px] font-semibold tracking-wide text-err uppercase">
                stderr
              </p>
              <Mono className="text-err">{stderr.replace(/\n+$/, "")}</Mono>
            </div>
          )}
        </>
      )}
    </Frame>
  );
}

function Command({ text }: { text: string }) {
  return (
    <>
      <span className="shrink-0 font-mono text-faint">$</span>
      <span className="min-w-0 flex-1 truncate font-mono text-fg" title={text}>
        {text}
      </span>
    </>
  );
}
