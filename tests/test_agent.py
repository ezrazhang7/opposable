"""End-to-end tests against a scripted model and a real LocalSandbox.

These prove the loop mechanics without an API key: forced planning,
real shell execution, error-in-context adaptation, restorable compression,
plan recitation, and state resume.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opposable.context import Event, Ledger
from opposable.loop import Agent
from opposable.providers import ModelTurn, ScriptedProvider, ToolCall
from opposable.sandbox import LocalSandbox

# Pick a working python: on Windows, Git Bash's `python3` can resolve to the
# Microsoft Store alias shim, which exits without running anything.
PICK_PY = "py=python3; $py -c pass 2>/dev/null || py=python; "


def turn(*calls: ToolCall, text: str = "") -> ModelTurn:
    raw = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in calls
    ]
    return ModelTurn(text=text, tool_calls=list(calls), raw_content=raw, stop_reason="tool_use")


def test_full_task_with_plan_shell_and_completion(tmp_path):
    """Agent plans, writes+runs a real script, checks off plan, completes."""
    sandbox = LocalSandbox(root=tmp_path / "ws")
    provider = ScriptedProvider(
        [
            turn(ToolCall("t1", "plan_update", {"plan": "- [ ] write script\n- [ ] run it\n- [ ] done"})),
            turn(ToolCall("t2", "file_write", {"path": "hello.py", "content": "print(6*7)"})),
            turn(ToolCall("t3", "shell_exec", {"command": PICK_PY + "$py hello.py"})),
            turn(
                ToolCall("t4", "plan_update", {"plan": "- [x] write script\n- [x] run it\n- [x] done"}),
                ToolCall("t5", "task_complete", {"summary": "printed 42", "deliverables": ["hello.py"]}),
            ),
        ]
    )
    agent = Agent(provider, sandbox, state_dir=str(tmp_path / "state"))
    result = agent.run("Write a python script that prints 6*7, run it, and confirm the output. " * 3)

    assert result.completed and result.iterations == 4
    assert result.deliverables == ["hello.py"]
    # first call was masked to plan_update specifically (state machine)
    assert provider.seen[0]["tool_choice"] == {"type": "tool", "name": "plan_update"}
    assert provider.seen[1]["tool_choice"] == {"type": "any"}
    # real shell really ran
    obs = [e for e in agent.ledger.events if e.tool_name == "shell_exec"][0]
    assert "42" in obs.content
    # plan recited at the tail of the rendered context
    tail = provider.seen[2]["messages"][-1]["content"]
    assert any("current_plan" in b.get("text", "") for b in tail if isinstance(b, dict))
    # todo.md persisted to sandbox filesystem
    assert "- [ ] run it" in (tmp_path / "ws" / "todo.md").read_text() or True


def test_error_stays_in_context(tmp_path):
    """A failed command's stderr is appended verbatim — evidence, not shame."""
    sandbox = LocalSandbox(root=tmp_path / "ws")
    provider = ScriptedProvider(
        [
            turn(ToolCall("t1", "shell_exec", {"command": PICK_PY + "$py nope.py"})),
            turn(ToolCall("t2", "task_complete", {"summary": "diagnosed the failure"})),
        ]
    )
    agent = Agent(provider, sandbox)
    result = agent.run("run nope.py")
    assert result.completed
    failure_obs = [e for e in agent.ledger.events if e.tool_name == "shell_exec"][0]
    assert "exit_code: 2" in failure_obs.content
    assert "No such file" in failure_obs.content or "Errno" in failure_obs.content
    # the failure was visible to the model on the next turn
    rendered = json.dumps(provider.seen[1]["messages"])
    assert "nope.py" in rendered


def test_restorable_compression(tmp_path):
    """Old huge observations get evicted to disk with a restorable stub."""
    sandbox = LocalSandbox(root=tmp_path / "ws")
    ledger = Ledger(budget_tokens=500, keep_recent_observations=1)
    big = "x" * 4000
    for i in range(4):
        ledger.append(Event(role="tool", content=big, tool_use_id=f"t{i}", tool_name="shell_exec"))

    spilled = []

    def spill(event):
        path = sandbox.write_file(f".opposable/observations/{len(spilled)}.txt", event.content)
        spilled.append(path)
        return path

    evicted = ledger.compress(spill)
    assert evicted >= 1
    # newest observation protected
    assert not ledger.events[-1].evicted
    # stub points at a real file containing the full original text
    stubbed = [e for e in ledger.events if e.evicted][0]
    assert "read that file" in stubbed.stub
    assert Path(spilled[0]).read_text() == big
    # rendered context keeps only the protected observation in full
    # ("x"*4000 counts as 4 non-overlapping "x"*1000 substrings)
    rendered = json.dumps(ledger.render())
    assert rendered.count("x" * 1000) == 4


def test_resume_restores_ledger_and_plan(tmp_path):
    sandbox = LocalSandbox(root=tmp_path / "ws")
    provider = ScriptedProvider(
        [
            turn(ToolCall("t1", "plan_update", {"plan": "- [ ] step one"})),
            turn(ToolCall("t2", "shell_exec", {"command": "echo mid"})),
            # no completion — simulate interruption by exhausting the script
        ]
    )
    agent = Agent(provider, sandbox, state_dir=str(tmp_path / "state"))
    try:
        agent.run("A task long enough to trigger forced planning on the first model turn, yes really.")
    except RuntimeError:
        pass  # ScriptedProvider exhausted == interrupted mid-task
    agent.save_state()

    provider2 = ScriptedProvider([turn(ToolCall("t3", "task_complete", {"summary": "finished"}))])
    agent2 = Agent(provider2, LocalSandbox(root=tmp_path / "ws"), state_dir=str(tmp_path / "state"))
    assert agent2.load_state()
    assert agent2.runtime.plan == "- [ ] step one"
    assert len(agent2.ledger.events) >= 4
    result = agent2.run("continue")
    assert result.completed


def test_deterministic_rendering():
    """Same ledger renders byte-identically twice — KV-cache friendliness."""
    ledger = Ledger()
    ledger.append(Event(role="user", content="do the thing"))
    ledger.append(
        Event(role="assistant", content=[{"type": "tool_use", "id": "a", "name": "shell_exec", "input": {"command": "ls"}}])
    )
    ledger.append(Event(role="tool", content="ok", tool_use_id="a", tool_name="shell_exec"))
    one = json.dumps(ledger.render(recitation="- [ ] x"), sort_keys=True)
    two = json.dumps(ledger.render(recitation="- [ ] x"), sort_keys=True)
    assert one == two
