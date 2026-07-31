import { Frame, Running } from "./shared";
import { Checklist } from "../Checklist";
import { parsePlan } from "../../lib/plan";
import type { Step } from "../../lib/useSession";

/** plan_ steps: the todo.md the agent wrote at that moment. */
export function ChecklistView({ step }: { step: Step }) {
  const markdown = typeof step.args.plan === "string" ? step.args.plan : "";
  const plan = parsePlan(markdown);
  const bar = (
    <>
      <span className="min-w-0 flex-1 truncate font-mono text-fg">todo.md</span>
      {plan.total > 0 && (
        <span className="shrink-0 font-mono text-faint">
          {plan.done}/{plan.total}
        </span>
      )}
    </>
  );

  if (step.observation === undefined) {
    return (
      <Frame bar={bar}>
        <Running label="Writing the plan…" />
      </Frame>
    );
  }

  return (
    <Frame bar={bar}>
      <Checklist plan={plan} className="px-4 py-3" />
    </Frame>
  );
}
