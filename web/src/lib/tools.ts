import { Check, FileIcon, Globe, ListChecks, Terminal } from "../components/Icons";

/** Tool-name prefix decides the chat chip's wording and the computer panel's
 *  renderer — the engine groups tools by prefix for exactly this reason. */
export type ToolKind = "terminal" | "editor" | "reader" | "checklist" | "completion" | "unknown";

export function toolKind(name: string): ToolKind {
  if (name.startsWith("shell_")) return "terminal";
  if (name.startsWith("file_")) return "editor";
  if (name.startsWith("web_")) return "reader";
  if (name.startsWith("plan_")) return "checklist";
  if (name.startsWith("task_")) return "completion";
  return "unknown";
}

export const KIND_ICON = {
  terminal: Terminal,
  editor: FileIcon,
  reader: Globe,
  checklist: ListChecks,
  completion: Check,
  unknown: Terminal,
} as const;

/** What the panel header says opposable is using. */
export const KIND_LABEL: Record<ToolKind, string> = {
  terminal: "Terminal",
  editor: "Editor",
  reader: "Browser",
  checklist: "Planner",
  completion: "Summary",
  unknown: "Tool",
};

const VERBS: Record<string, string> = {
  shell_exec: "Executing command",
  file_write: "Writing file",
  file_read: "Reading file",
  web_fetch: "Browsing",
  plan_update: "Updating plan",
  task_complete: "Completing task",
};

export function toolVerb(name: string): string {
  return VERBS[name] ?? name;
}

/** The one argument worth showing next to the verb. */
export function toolArg(name: string, args: Record<string, unknown>): string {
  const pick = (k: string) => (typeof args[k] === "string" ? (args[k] as string) : "");
  switch (name) {
    case "shell_exec":
      return pick("command");
    case "file_write":
    case "file_read":
      return pick("path");
    case "web_fetch":
      return pick("url");
    case "plan_update":
      return "todo.md";
    case "task_complete":
      return "";
    default:
      return Object.values(args).filter((v) => typeof v === "string")[0] ?? "";
  }
}

export function truncate(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max - 1) + "…" : flat;
}

/** Split a shell observation back into its three parts. The runtime formats
 *  it as `exit_code: N\nstdout:\n…\nstderr:\n…`; stdout may itself contain the
 *  word "stderr:", so the tail is found from the end. */
export function parseShell(observation: string): {
  code: number | null;
  stdout: string;
  stderr: string;
} {
  const code = exitCode(observation);
  const outAt = observation.indexOf("\nstdout:\n");
  if (outAt === -1) return { code, stdout: observation, stderr: "" };
  const rest = observation.slice(outAt + "\nstdout:\n".length);
  const errAt = rest.lastIndexOf("\nstderr:\n");
  if (errAt === -1) return { code, stdout: rest, stderr: "" };
  return {
    code,
    stdout: rest.slice(0, errAt),
    stderr: rest.slice(errAt + "\nstderr:\n".length),
  };
}

/** shell_exec reports the exit code in the first line of its observation. */
export function exitCode(observation: string): number | null {
  const m = /^exit_code:\s*(-?\d+)/.exec(observation);
  return m ? Number(m[1]) : null;
}

/** Failures stay visible: a raised tool error, or a non-zero exit. */
export function isFailure(observation: string | undefined): boolean {
  if (!observation) return false;
  if (observation.startsWith("TOOL ERROR")) return true;
  const code = exitCode(observation);
  return code !== null && code !== 0;
}
