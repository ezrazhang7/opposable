"""opposable CLI.

    opposable run "build me a fastapi todo app and test it"
    opposable run --sandbox docker --model claude-sonnet-4-6 "..."
    opposable resume .opposable-ab12cd34   # pick a task back up
"""

from __future__ import annotations

import argparse
import os
import sys

from .loop import Agent
from .providers import AnthropicProvider, OpenAICompatProvider
from .sandbox import DockerSandbox, LocalSandbox

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _printer(kind: str, payload: dict) -> None:
    if kind == "assistant" and payload["text"].strip():
        print(f"{CYAN}∴ {payload['text'].strip()}{RESET}")
    elif kind == "tool":
        args = str(payload["args"])
        if len(args) > 160:
            args = args[:160] + "…"
        print(f"{BOLD}→ {payload['name']}{RESET} {DIM}{args}{RESET}")
    elif kind == "observation":
        first = payload["text"].strip().splitlines()[:3]
        for line in first:
            print(f"{DIM}  {line[:200]}{RESET}")
    elif kind == "compress":
        print(f"{YELLOW}⇣ compressed {payload['evicted']} observations to disk{RESET}")


def build_provider(args: argparse.Namespace):
    if args.base_url or os.environ.get("OPPOSABLE_BASE_URL"):
        return OpenAICompatProvider(
            model=args.model,
            base_url=args.base_url or os.environ["OPPOSABLE_BASE_URL"],
        )
    return AnthropicProvider(model=args.model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opposable", description="general agent, open thumb")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run a task from scratch")
    run.add_argument("task")
    resume = sub.add_parser("resume", help="resume a previous task directory")
    resume.add_argument("workdir")
    resume.add_argument("task", nargs="?", default="Continue the task. Re-read todo.md and finish remaining steps.")

    for p in (run, resume):
        p.add_argument("--model", default=os.environ.get("OPPOSABLE_MODEL", "claude-sonnet-4-6"))
        p.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint (vLLM/Ollama/etc.)")
        p.add_argument("--sandbox", choices=["local", "docker"], default="local")
        p.add_argument("--image", default="ubuntu:24.04", help="docker image for --sandbox docker")
        p.add_argument("--max-iterations", type=int, default=60)
        p.add_argument("--budget-tokens", type=int, default=60_000)

    args = parser.parse_args(argv)

    if args.cmd == "resume":
        sandbox = LocalSandbox(root=args.workdir)
    elif args.sandbox == "docker":
        sandbox = DockerSandbox(image=args.image)
    else:
        sandbox = LocalSandbox()

    agent = Agent(
        provider=build_provider(args),
        sandbox=sandbox,
        max_iterations=args.max_iterations,
        budget_tokens=args.budget_tokens,
        state_dir=f"{sandbox.workdir}/.opposable/state" if args.sandbox != "docker" else None,
        on_event=_printer,
    )
    if args.cmd == "resume":
        agent.load_state()

    print(f"{DIM}sandbox: {sandbox.workdir}{RESET}")
    try:
        result = agent.run(args.task)
    except KeyboardInterrupt:
        agent.save_state()
        print(f"\n{YELLOW}interrupted — state saved, resume with:{RESET} opposable resume {sandbox.workdir}")
        return 130

    print()
    status = "✓ complete" if result.completed else "✗ stopped"
    print(f"{BOLD}{status}{RESET} after {result.iterations} iterations")
    print(result.summary)
    for d in result.deliverables:
        print(f"  deliverable: {d}")
    return 0 if result.completed else 1


if __name__ == "__main__":
    sys.exit(main())
