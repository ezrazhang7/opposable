"""Tests for the web bridge: REST + SSE against a scripted model and a real
LocalSandbox — no API key, no browser, no npm.
"""

import http.client
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opposable.loop import Agent
from opposable.providers import ModelTurn, ScriptedProvider, ToolCall
from opposable.sandbox import LocalSandbox
from opposable.server import OpposableServer, TaskManager


def turn(*calls: ToolCall, text: str = "") -> ModelTurn:
    raw = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in calls
    ]
    return ModelTurn(text=text, tool_calls=list(calls), raw_content=raw, stop_reason="tool_use")


class SlowProvider(ScriptedProvider):
    """Adds a small delay per turn so a stop request can land mid-run."""

    def complete(self, *args, **kwargs):
        time.sleep(0.05)
        return super().complete(*args, **kwargs)


def start_server(tmp_path, turns, slow=False):
    cls = SlowProvider if slow else ScriptedProvider
    manager = TaskManager(
        base_dir=str(tmp_path), provider_factory=lambda params: cls(list(turns))
    )
    httpd = OpposableServer(("127.0.0.1", 0), manager)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    payload = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


def sse_events(port, task_id, until_kinds=("done",), timeout=30):
    """Read the SSE stream, returning (kind, payload) pairs until a terminal
    kind or eof arrives."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", f"/api/tasks/{task_id}/events")
    resp = conn.getresponse()
    events, kind, deadline = [], None, time.time() + timeout
    while time.time() < deadline:
        line = resp.readline().decode("utf-8").rstrip("\n")
        if line.startswith(": "):
            continue
        if line.startswith("event: "):
            kind = line[len("event: "):]
        elif line.startswith("data: "):
            if kind == "eof":
                conn.close()
                return events
            events.append((kind, json.loads(line[len("data: "):])))
            if kind in until_kinds:
                conn.close()
                return events
    conn.close()
    raise AssertionError(f"terminal event not seen; got kinds {[k for k, _ in events]}")


SCRIPT = [
    turn(ToolCall("t1", "plan_update", {"plan": "- [ ] write file\n- [ ] done"})),
    turn(ToolCall("t2", "file_write", {"path": "report.md", "content": "# findings\n" + "x" * 900})),
    turn(ToolCall("t3", "shell_exec", {"command": "echo server-test-ok"})),
    turn(
        ToolCall("t4", "plan_update", {"plan": "- [x] write file\n- [x] done"}),
        ToolCall("t5", "task_complete", {"summary": "wrote report", "deliverables": ["report.md"]}),
    ),
]

LONG_TASK = "Write a report file and verify it with the shell, then declare completion. " * 2


def test_create_stream_complete_and_files(tmp_path):
    httpd, port = start_server(tmp_path, SCRIPT)
    status, meta = request(port, "POST", "/api/tasks", {"task": LONG_TASK, "model": "scripted"})
    assert status == 201 and meta["status"] == "running"
    task_id = meta["id"]

    events = sse_events(port, task_id)
    kinds = [k for k, _ in events]
    assert kinds[0] == "status" and events[0][1]["state"] == "running"
    assert "plan" in kinds and "tool" in kinds and "observation" in kinds
    # plan events carry the full todo.md
    plans = [p["plan"] for k, p in events if k == "plan"]
    assert plans[-1] == "- [x] write file\n- [x] done"
    # tool + observation events carry step indices and full (untruncated) text
    obs = [p for k, p in events if k == "observation" and p["name"] == "shell_exec"][0]
    assert "server-test-ok" in obs["text"] and obs["step"] >= 1
    done = [p for k, p in events if k == "done"][0]
    assert done["completed"] and done["deliverables"] == ["report.md"]

    # a fresh subscriber replays full history then gets eof (task finished)
    replay = sse_events(port, task_id)
    assert [k for k, _ in replay] == kinds

    # REST surface
    status, listing = request(port, "GET", "/api/tasks")
    assert status == 200 and listing[0]["id"] == task_id and listing[0]["status"] == "complete"
    status, detail = request(port, "GET", f"/api/tasks/{task_id}")
    assert status == 200 and len(detail["events"]) == len(kinds)

    status, files = request(port, "GET", f"/api/tasks/{task_id}/files")
    paths = [f["path"] for f in files["files"]]
    assert "report.md" in paths and "todo.md" in paths
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/api/tasks/{task_id}/files/report.md")
    resp = conn.getresponse()
    assert resp.status == 200 and b"# findings" in resp.read()
    conn.close()

    # path traversal is refused
    status, _ = request(port, "GET", f"/api/tasks/{task_id}/files/../../secrets.txt")
    assert status == 404
    httpd.shutdown()


def test_stop_mid_task(tmp_path):
    many = [turn(ToolCall(f"t{i}", "shell_exec", {"command": "echo tick"})) for i in range(100)]
    httpd, port = start_server(tmp_path, many, slow=True)
    _, meta = request(port, "POST", "/api/tasks", {"task": LONG_TASK * 2})
    task_id = meta["id"]

    events = sse_events(port, task_id, until_kinds=("observation",))
    assert events[-1][0] == "observation"
    status, _ = request(port, "POST", f"/api/tasks/{task_id}/stop")
    assert status == 202

    tail = sse_events(port, task_id, until_kinds=("done",))
    done = [p for k, p in tail if k == "done"][0]
    assert not done["completed"] and "stopped" in done["summary"]
    deadline = time.time() + 10
    while httpd.manager.get(task_id).status == "running" and time.time() < deadline:
        time.sleep(0.05)
    assert httpd.manager.get(task_id).status == "stopped"
    # stopping again is a conflict
    status, _ = request(port, "POST", f"/api/tasks/{task_id}/stop")
    assert status == 409
    httpd.shutdown()


def test_history_survives_restart_and_resume(tmp_path):
    httpd, port = start_server(tmp_path, SCRIPT)
    _, meta = request(port, "POST", "/api/tasks", {"task": LONG_TASK})
    task_id = meta["id"]
    sse_events(port, task_id)
    httpd.shutdown()

    # a brand-new manager (server restart) finds the task and its history on disk
    resumed_script = [turn(ToolCall("r1", "task_complete", {"summary": "resumed and finished"}))]
    manager2 = TaskManager(
        base_dir=str(tmp_path), provider_factory=lambda params: ScriptedProvider(list(resumed_script))
    )
    httpd2 = OpposableServer(("127.0.0.1", 0), manager2)
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    port2 = httpd2.server_address[1]

    status, detail = request(port2, "GET", f"/api/tasks/{task_id}")
    assert status == 200 and detail["status"] == "complete"
    assert any(e["kind"] == "done" for e in detail["events"])

    # resume runs a fresh worker on the persisted ledger
    status, _ = request(port2, "POST", f"/api/tasks/{task_id}/resume")
    assert status == 202
    # History replay contains the first run's done event, so read until eof
    # (sent once the resumed worker finishes) and take the last done.
    tail = sse_events(port2, task_id, until_kinds=())
    assert [p for k, p in tail if k == "done"][-1]["summary"] == "resumed and finished"
    httpd2.shutdown()


def test_follow_up_message_reaches_the_model(tmp_path):
    """Guidance dropped in the inbox is drained into the ledger next iteration."""
    provider = ScriptedProvider(
        [
            turn(ToolCall("t1", "shell_exec", {"command": "echo one"})),
            turn(ToolCall("t2", "task_complete", {"summary": "done"})),
        ]
    )
    agent = Agent(provider, LocalSandbox(root=tmp_path / "ws"))
    agent.inbox.append("also include a second section")
    result = agent.run("short task")
    assert result.completed
    rendered = json.dumps(provider.seen[0]["messages"])
    assert "also include a second section" in rendered


def test_follow_up_is_recorded_as_a_user_event(tmp_path):
    """Guidance sent mid-run shows up in the transcript, not just the ledger."""
    many = [turn(ToolCall(f"t{i}", "shell_exec", {"command": "echo tick"})) for i in range(100)]
    httpd, port = start_server(tmp_path, many, slow=True)
    _, meta = request(port, "POST", "/api/tasks", {"task": LONG_TASK * 2})
    task_id = meta["id"]
    sse_events(port, task_id, until_kinds=("observation",))

    status, _ = request(
        port, "POST", f"/api/tasks/{task_id}/messages", {"text": "also chart the result"}
    )
    assert status == 202
    request(port, "POST", f"/api/tasks/{task_id}/stop")
    events = sse_events(port, task_id, until_kinds=("done",))
    assert ("user", {"text": "also chart the result"}) in events

    # ...and it survives a reload, because it is in events.jsonl
    _, detail = request(port, "GET", f"/api/tasks/{task_id}")
    assert any(e["kind"] == "user" for e in detail["events"])
    httpd.shutdown()


def test_validation_errors(tmp_path):
    httpd, port = start_server(tmp_path, SCRIPT)
    status, body = request(port, "POST", "/api/tasks", {"task": "   "})
    assert status == 400 and "required" in body["error"]
    status, _ = request(port, "GET", "/api/tasks/nope99")
    assert status == 404
    status, _ = request(port, "POST", "/api/tasks/nope99/stop")
    assert status == 404
    httpd.shutdown()
