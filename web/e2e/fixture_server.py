"""Deterministic backend for the frontend's visual checks.

Runs the real ``opposable`` web bridge — real sandbox, real tool execution,
real SSE — but swaps the model for a scripted one, so every screenshot and the
end-to-end run are reproducible offline and cost nothing.

    python web/e2e/fixture_server.py [--port 8734] [--delay 0.35] [--keep]

The script a task uses is chosen by its ``model`` field: "demo" (default),
"error", or "long".
"""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from opposable.providers import ModelTurn, ScriptedProvider, ToolCall  # noqa: E402
from opposable.server import OpposableServer, TaskManager  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / ".fixtures"

PAGE = """<!doctype html>
<html><head><title>Voyager Program — mission facts</title></head>
<body>
<h1>Voyager Program</h1>
<p>Voyager 1 and Voyager 2 launched in 1977 to study the outer planets.
Both spacecraft carry the Golden Record and remain in contact with the
Deep Space Network more than four decades later.</p>
<ul>
  <li>Voyager 1 launched 1977-09-05; crossed the heliopause in August 2012.</li>
  <li>Voyager 2 launched 1977-08-20; crossed the heliopause in November 2018.</li>
  <li>Voyager 2 remains the only spacecraft to have visited Uranus and Neptune.</li>
</ul>
<p>Power comes from radioisotope thermoelectric generators, declining by about
four watts per year; instruments are shut down one by one to extend the mission
into the 2030s.</p>
</body></html>
"""

REPORT = """# Voyager Program — briefing

## What they are
Two probes launched in 1977 on a rare outer-planet alignment.

## Where they are now
Both are in interstellar space: Voyager 1 crossed the heliopause in
August 2012, Voyager 2 in November 2018.

## Why they still matter
They carry the only in-situ instruments beyond the heliopause, and they are
the only spacecraft to have flown past Uranus and Neptune.

## Power budget
RTG output declines ~4 W/year, so instruments are retired one at a time to
keep the mission alive into the 2030s.
"""

PLAN_1 = """# Voyager briefing

- [ ] Fetch the mission overview page
- [ ] Save raw notes to notes.md
- [ ] Check the notes landed on disk
- [ ] Write report.md
- [ ] Verify the deliverable
"""

PLAN_2 = """# Voyager briefing

- [x] Fetch the mission overview page
- [x] Save raw notes to notes.md
- [x] Check the notes landed on disk
- [ ] Write report.md
- [ ] Verify the deliverable
"""

PLAN_3 = """# Voyager briefing

- [x] Fetch the mission overview page
- [x] Save raw notes to notes.md
- [x] Check the notes landed on disk
- [x] Write report.md
- [x] Verify the deliverable
"""

NOTES = """# raw notes

- 1977 launches, outer-planet grand tour
- heliopause crossings: V1 2012-08, V2 2018-11
- V2 only visit to Uranus + Neptune
- RTG decline ~4 W/yr
"""


def turn(*calls: ToolCall, text: str = "") -> ModelTurn:
    raw = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in calls
    ]
    return ModelTurn(
        text=text,
        tool_calls=list(calls),
        raw_content=raw,
        stop_reason="tool_use",
        usage={"input_tokens": 1840, "output_tokens": 260, "cache_read_input_tokens": 9600},
    )


def demo_script(page_url: str) -> list[ModelTurn]:
    return [
        turn(
            ToolCall("c1", "plan_update", {"plan": PLAN_1}),
            text="I'll pull the mission overview, take notes, then write the briefing.",
        ),
        turn(
            ToolCall("c2", "web_fetch", {"url": page_url}),
            text="Fetching the overview page.",
        ),
        turn(ToolCall("c3", "file_write", {"path": "notes.md", "content": NOTES})),
        turn(
            ToolCall("c4", "file_read", {"path": "notes-typo.md"}),
            text="Let me confirm the notes are on disk.",
        ),
        turn(
            ToolCall("c5", "shell_exec", {"command": "ls -la && wc -l notes.md"}),
            text="Wrong filename — checking what actually exists.",
        ),
        turn(ToolCall("c6", "plan_update", {"plan": PLAN_2})),
        turn(
            ToolCall("c7", "file_write", {"path": "report.md", "content": REPORT}),
            text="Notes are in place. Writing the briefing now.",
        ),
        turn(ToolCall("c8", "shell_exec", {"command": "head -12 report.md"})),
        turn(ToolCall("c9", "plan_update", {"plan": PLAN_3})),
        turn(
            ToolCall(
                "c10",
                "task_complete",
                {
                    "summary": (
                        "Wrote a five-section briefing on the Voyager program from the "
                        "mission overview page, with raw notes kept alongside it.\n\n"
                        "The report covers what the probes are, where they are now, why "
                        "they still matter, and the RTG power budget that bounds the "
                        "remaining mission."
                    ),
                    "deliverables": ["report.md", "notes.md"],
                },
            ),
            text="Done — the briefing is written and verified.",
        ),
    ]


def error_script(page_url: str) -> list[ModelTurn]:
    return [
        turn(ToolCall("e1", "plan_update", {"plan": PLAN_1})),
        turn(ToolCall("e2", "web_fetch", {"url": page_url.replace("/voyager", "/missing")})),
        turn(ToolCall("e3", "shell_exec", {"command": "cat no-such-file.txt"})),
        turn(
            ToolCall("e4", "task_complete", {"summary": "Gave up after two failures."}),
            text="Both attempts failed; stopping here.",
        ),
    ]


def long_script(page_url: str) -> list[ModelTurn]:
    """Enough turns that a stop request can land mid-run."""
    turns = [turn(ToolCall("l0", "plan_update", {"plan": PLAN_1}))]
    for i in range(1, 60):
        turns.append(
            turn(
                ToolCall(f"l{i}", "shell_exec", {"command": f"echo step {i} of a long crawl"}),
                text=f"Working through item {i}.",
            )
        )
    turns.append(turn(ToolCall("lz", "task_complete", {"summary": "finished the crawl"})))
    return turns


SCRIPTS = {"demo": demo_script, "error": error_script, "long": long_script}


class PacedProvider(ScriptedProvider):
    """A scripted provider that pretends to think, so live UI is observable."""

    def __init__(self, turns, delay: float):
        super().__init__(turns)
        self.delay = delay

    def complete(self, *args, **kwargs):
        time.sleep(self.delay)
        return super().complete(*args, **kwargs)


class PageHandler(BaseHTTPRequestHandler):
    """A one-page website for web_fetch to read, so the fixture stays offline."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.rstrip("/") != "/voyager":
            self.send_error(404, "not found")
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8734)
    ap.add_argument("--page-port", type=int, default=8901)
    ap.add_argument("--delay", type=float, default=0.35, help="seconds per model turn")
    ap.add_argument("--dir", default=str(FIXTURE_DIR))
    ap.add_argument("--keep", action="store_true", help="keep tasks from a previous run")
    args = ap.parse_args()

    base = Path(args.dir)
    if base.exists() and not args.keep:
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    site = ThreadingHTTPServer(("127.0.0.1", args.page_port), PageHandler)
    site.daemon_threads = True
    threading.Thread(target=site.serve_forever, daemon=True).start()
    page_url = f"http://127.0.0.1:{args.page_port}/voyager"

    def factory(params):
        script = SCRIPTS.get(params.get("model") or "demo", demo_script)
        return PacedProvider(script(page_url), args.delay)

    httpd = OpposableServer(("127.0.0.1", args.port), TaskManager(base_dir=str(base), provider_factory=factory))
    print(f"fixture server on http://127.0.0.1:{args.port} (tasks in {base}, delay {args.delay}s)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
