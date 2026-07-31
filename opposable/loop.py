"""The agent loop.

One model, one sandbox, one append-only ledger, and a small state machine.
No planner/executor/critic committee — a single loop with disciplined
context beats a bureaucracy of sub-agents at this scale.

State machine (masking, not removal — tool definitions never change):

    PLAN     -> tool_choice forces plan_update       (first turn of real tasks)
    ACT      -> tool_choice "any" among all tools    (must act, free choice)
    COMPLETE -> reached when task_complete fires

Each iteration:
    1. compress ledger if over budget (restorably — spill to sandbox files)
    2. render messages with the current plan recited at the tail
    3. call the model with a byte-stable system prompt
    4. execute tool calls in the sandbox; append results verbatim,
       including failures ("keep the wrong stuff in")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .context import Event, Ledger
from .providers import ModelTurn, Provider
from .sandbox import Sandbox
from .tools import TOOL_SCHEMAS, ToolRuntime

SYSTEM_PROMPT = """\
You are opposable, an autonomous general agent operating a computer.

You work inside a sandbox: a working directory where you can run shell \
commands, read and write files, and fetch the web. You act by calling tools; \
you never merely describe what you would do.

Operating discipline:
- For any non-trivial task, first call plan_update to write todo.md with \
concrete, checkable steps. Rewrite it as you finish or reorder steps. Your \
current plan is shown to you at the end of every turn; keep it truthful.
- Use the filesystem as your memory. Write intermediate findings, notes, and \
long outputs to files. Anything compressed out of your context has been saved \
to a file whose path is given in the stub — read it back when needed.
- When a command fails, the error stays in your context. Read it, diagnose, \
and change approach. Do not repeat a failed action unchanged.
- Prefer small, verifiable steps. Verify your own work (run the code, check \
the file) before declaring victory.
- Call task_complete only when every step of the plan is checked off, with a \
summary and paths to all deliverables.
"""

PLAN_THRESHOLD_CHARS = 80  # tasks shorter than this may skip forced planning


@dataclass
class RunResult:
    completed: bool
    summary: str
    iterations: int
    deliverables: list[str] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        provider: Provider,
        sandbox: Sandbox,
        max_iterations: int = 60,
        budget_tokens: int = 60_000,
        state_dir: str | None = None,
        on_event=None,
    ):
        self.provider = provider
        self.sandbox = sandbox
        self.max_iterations = max_iterations
        self.ledger = Ledger(budget_tokens=budget_tokens)
        self.runtime = ToolRuntime(sandbox)
        self.state_dir = Path(state_dir) if state_dir else None
        self.on_event = on_event or (lambda kind, payload: None)
        self._spill_count = 0
        self._step = 0  # monotonically increasing tool-call index
        self.usage: dict[str, int] = {}
        # Set from another thread (e.g. the web server) to stop cooperatively;
        # checked once per iteration, state is saved before returning.
        self.stop_requested = False
        # Follow-up guidance appended from another thread; drained into the
        # ledger as user events at the top of each iteration.
        self.inbox: list[str] = []

    # ------------------------------------------------------------------ state

    def _spill(self, event: Event) -> str:
        self._spill_count += 1
        body = event.content
        if isinstance(body, list):
            body = "".join(b.get("text", "") for b in body if isinstance(b, dict))
        return self.sandbox.write_file(
            f".opposable/observations/{self._spill_count:04d}.txt", str(body)
        )

    def save_state(self) -> None:
        if not self.state_dir:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "plan": self.runtime.plan,
            "events": [
                {
                    "role": e.role,
                    "content": e.content,
                    "tool_use_id": e.tool_use_id,
                    "tool_name": e.tool_name,
                    "evicted": e.evicted,
                    "stub": e.stub,
                }
                for e in self.ledger.events
            ],
        }
        (self.state_dir / "state.json").write_text(
            json.dumps(state, sort_keys=True), encoding="utf-8"
        )

    def load_state(self) -> bool:
        if not self.state_dir:
            return False
        path = self.state_dir / "state.json"
        if not path.exists():
            return False
        state = json.loads(path.read_text(encoding="utf-8"))
        self.runtime.plan = state.get("plan")
        for e in state["events"]:
            self.ledger.append(Event(**e))
        return True

    # ------------------------------------------------------------------- loop

    def _finish(self, result: RunResult) -> RunResult:
        self.save_state()
        self.on_event(
            "done",
            {
                "completed": result.completed,
                "summary": result.summary,
                "iterations": result.iterations,
                "deliverables": result.deliverables,
                "usage": dict(self.usage),
            },
        )
        return result

    def run(self, task: str) -> RunResult:
        resumed = bool(self.ledger.events)
        if not resumed:
            self.ledger.append(Event(role="user", content=task))
        force_plan = (
            not resumed
            and self.runtime.plan is None
            and len(task) >= PLAN_THRESHOLD_CHARS
        )

        for iteration in range(1, self.max_iterations + 1):
            if self.stop_requested:
                return self._finish(RunResult(False, "stopped by user", iteration - 1))
            while self.inbox:
                self.ledger.append(Event(role="user", content=self.inbox.pop(0)))

            evicted = self.ledger.compress(self._spill)
            if evicted:
                self.on_event("compress", {"evicted": evicted})

            messages = self.ledger.render(recitation=self.runtime.plan)
            tool_choice = (
                {"type": "tool", "name": "plan_update"}
                if force_plan
                else {"type": "any"}
            )
            force_plan = False

            turn: ModelTurn = self.provider.complete(
                system=SYSTEM_PROMPT,  # byte-stable across every iteration
                messages=messages,
                tools=TOOL_SCHEMAS,    # never mutated mid-run
                tool_choice=tool_choice,
            )
            for key, value in turn.usage.items():
                if isinstance(value, int):
                    self.usage[key] = self.usage.get(key, 0) + value
            self.ledger.append(Event(role="assistant", content=turn.raw_content))
            if turn.text:
                self.on_event("assistant", {"text": turn.text})

            if not turn.tool_calls:
                # Model chose to stop talking instead of acting; treat its
                # text as the outcome.
                return self._finish(RunResult(False, turn.text or "(no action)", iteration))

            done_summary: str | None = None
            deliverables: list[str] = []
            for call in turn.tool_calls:
                self._step += 1
                self.on_event("tool", {"name": call.name, "args": call.args, "step": self._step})
                observation, done = self.runtime.execute(call.name, call.args)
                self.on_event(
                    "observation",
                    {"name": call.name, "text": observation, "step": self._step},
                )
                if call.name == "plan_update" and self.runtime.plan is not None:
                    self.on_event("plan", {"plan": self.runtime.plan})
                self.ledger.append(
                    Event(
                        role="tool",
                        content=observation,
                        tool_use_id=call.id,
                        tool_name=call.name,
                    )
                )
                if done:
                    done_summary = observation
                    deliverables = call.args.get("deliverables", [])

            self.save_state()
            if done_summary is not None:
                return self._finish(RunResult(True, done_summary, iteration, deliverables))
            time.sleep(0)  # yield point for embedding hosts

        return self._finish(RunResult(False, "max iterations reached", self.max_iterations))
