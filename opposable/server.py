"""Web bridge: the agent engine exposed over REST + SSE, stdlib only.

The frontend (web/) is a static SPA; this server is its entire backend:

    POST /api/tasks                  start a task -> {id}
    GET  /api/tasks                  list all sessions (live + on disk)
    GET  /api/tasks/{id}             metadata + full event history
    GET  /api/tasks/{id}/events      SSE live stream (history replayed first)
    POST /api/tasks/{id}/stop        cooperative stop
    POST /api/tasks/{id}/messages    follow-up guidance while running
    POST /api/tasks/{id}/resume      pick a stopped task back up
    GET  /api/tasks/{id}/files       flat listing of the task workdir
    GET  /api/tasks/{id}/files/{p}   raw file content
    GET  /*                          static SPA from web/dist

One worker thread per running task. Events fan out from the agent's
``on_event`` callback to any number of SSE subscribers, and every event is
appended to ``events.jsonl`` in the task's state dir so history survives a
server restart and powers replay.
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .loop import Agent, RunResult
from .providers import AnthropicProvider, OpenAICompatProvider, Provider
from .sandbox import DockerSandbox, LocalSandbox

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

PLACEHOLDER_PAGE = """<!doctype html><meta charset="utf-8">
<title>opposable</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center;color:#57534e">
<h1 style="color:#1c1917">opposable</h1>
<p>API is up. The web UI has not been built yet:</p>
<pre style="text-align:left;background:#f5f5f4;padding:1em;border-radius:12px">cd web
npm install
npm run build</pre>
<p>then reload this page.</p></div>
"""

RESUME_TASK = "Continue the task. Re-read todo.md and finish remaining steps."


def default_provider_factory(params: dict) -> Provider:
    model = params.get("model") or os.environ.get("OPPOSABLE_MODEL", "claude-sonnet-4-6")
    base_url = params.get("base_url") or os.environ.get("OPPOSABLE_BASE_URL")
    if base_url:
        return OpenAICompatProvider(model=model, base_url=base_url)
    return AnthropicProvider(model=model)


@dataclass
class TaskHandle:
    id: str
    task: str
    created: float
    workdir: str
    state_dir: Path
    status: str = "running"  # running | complete | stopped | error
    agent: Agent | None = None
    thread: threading.Thread | None = None
    history: list[dict] = field(default_factory=list)
    subscribers: list[queue.SimpleQueue] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    params: dict = field(default_factory=dict)

    def meta(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "title": self.task.strip().splitlines()[0][:120] if self.task.strip() else self.id,
            "created": self.created,
            "status": self.status,
            "workdir": self.workdir,
            "model": self.params.get("model"),
            "sandbox": self.params.get("sandbox", "local"),
        }


class TaskManager:
    """Owns every task: registry of live handles + lazy loading from disk."""

    def __init__(self, base_dir: str | None = None, provider_factory=None):
        self.base_dir = Path(base_dir or Path.cwd())
        self.provider_factory = provider_factory or default_provider_factory
        self.tasks: dict[str, TaskHandle] = {}
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- events

    def _emit(self, handle: TaskHandle, kind: str, payload: dict) -> None:
        with handle.lock:
            event = {"seq": len(handle.history) + 1, "kind": kind, "payload": payload}
            handle.history.append(event)
            line = json.dumps(event, sort_keys=True, ensure_ascii=False)
            with (handle.state_dir / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            for q in handle.subscribers:
                q.put(event)

    def subscribe(self, handle: TaskHandle) -> tuple[list[dict], queue.SimpleQueue]:
        """Atomically snapshot history and register for future events."""
        q: queue.SimpleQueue = queue.SimpleQueue()
        with handle.lock:
            snapshot = list(handle.history)
            handle.subscribers.append(q)
        return snapshot, q

    def unsubscribe(self, handle: TaskHandle, q: queue.SimpleQueue) -> None:
        with handle.lock:
            if q in handle.subscribers:
                handle.subscribers.remove(q)

    # ----------------------------------------------------------------- tasks

    def _write_meta(self, handle: TaskHandle) -> None:
        (handle.state_dir / "meta.json").write_text(
            json.dumps(handle.meta(), sort_keys=True), encoding="utf-8"
        )

    def _build_agent(self, handle: TaskHandle) -> Agent:
        params = handle.params
        if params.get("sandbox") == "docker":
            sandbox = DockerSandbox(image=params.get("image", "ubuntu:24.04"))
        else:
            sandbox = LocalSandbox(root=handle.workdir)
        return Agent(
            provider=self.provider_factory(params),
            sandbox=sandbox,
            max_iterations=int(params.get("max_iterations", 60)),
            budget_tokens=int(params.get("budget_tokens", 60_000)),
            state_dir=str(handle.state_dir),
            on_event=lambda kind, payload: self._emit(handle, kind, payload),
        )

    def create(self, task: str, params: dict) -> TaskHandle:
        task_id = uuid.uuid4().hex[:8]
        workdir = self.base_dir / f".opposable-{task_id}"
        state_dir = workdir / ".opposable" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        handle = TaskHandle(
            id=task_id,
            task=task,
            created=time.time(),
            workdir=str(workdir),
            state_dir=state_dir,
            params=params,
        )
        with self.lock:
            self.tasks[task_id] = handle
        handle.agent = self._build_agent(handle)
        self._write_meta(handle)
        self._start_worker(handle, task, resumed=False)
        return handle

    def resume(self, handle: TaskHandle, message: str | None = None) -> None:
        if handle.status == "running":
            raise ValueError("task is already running")
        handle.agent = self._build_agent(handle)
        if handle.agent.load_state():
            # Agent.run() ignores its task argument when the ledger already has
            # history, so the resume prompt must travel via the inbox instead.
            handle.agent.inbox.append(message or RESUME_TASK)
        handle.status = "running"
        self._write_meta(handle)
        self._start_worker(handle, message or RESUME_TASK, resumed=True)

    def _start_worker(self, handle: TaskHandle, task: str, resumed: bool) -> None:
        self._emit(handle, "status", {"state": "running", "resumed": resumed})

        def work() -> None:
            try:
                result: RunResult = handle.agent.run(task)
                if result.completed:
                    handle.status = "complete"
                elif handle.agent.stop_requested:
                    handle.status = "stopped"
                else:
                    handle.status = "stopped"
            except Exception as exc:  # noqa: BLE001 — surface, never swallow
                handle.status = "error"
                self._emit(
                    handle, "status",
                    {"state": "error", "detail": f"{type(exc).__name__}: {exc}"},
                )
            else:
                # "complete" is already conveyed by the done event; the status
                # kind only carries running / stopped / error (see PRD table).
                if handle.status != "complete":
                    self._emit(handle, "status", {"state": handle.status})
            self._write_meta(handle)

        handle.thread = threading.Thread(target=work, daemon=True, name=f"task-{handle.id}")
        handle.thread.start()

    # ------------------------------------------------------------- discovery

    def _load_from_disk(self, task_id: str) -> TaskHandle | None:
        workdir = self.base_dir / f".opposable-{task_id}"
        state_dir = workdir / ".opposable" / "state"
        meta_path = state_dir / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        handle = TaskHandle(
            id=task_id,
            task=meta.get("task", ""),
            created=meta.get("created", meta_path.stat().st_mtime),
            workdir=str(workdir),
            state_dir=state_dir,
            # A "running" status on disk means the server died mid-task.
            status=meta.get("status") if meta.get("status") != "running" else "stopped",
            params={"model": meta.get("model"), "sandbox": meta.get("sandbox", "local")},
        )
        events_path = state_dir / "events.jsonl"
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    handle.history.append(json.loads(line))
        return handle

    def get(self, task_id: str) -> TaskHandle | None:
        with self.lock:
            if task_id in self.tasks:
                return self.tasks[task_id]
        handle = self._load_from_disk(task_id)
        if handle:
            with self.lock:
                self.tasks.setdefault(task_id, handle)
                handle = self.tasks[task_id]
        return handle

    def list(self) -> list[dict]:
        ids = {p.name.removeprefix(".opposable-") for p in self.base_dir.glob(".opposable-*") if p.is_dir()}
        with self.lock:
            ids.update(self.tasks.keys())
        handles = [h for h in (self.get(i) for i in sorted(ids)) if h]
        return [h.meta() for h in sorted(handles, key=lambda h: h.created, reverse=True)]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "opposable"

    @property
    def manager(self) -> TaskManager:
        return self.server.manager  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # quiet by default
        pass

    # ---------------------------------------------------------------- helpers

    def _json(self, status: int, body: dict | list) -> None:
        data = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _task_or_404(self, task_id: str) -> TaskHandle | None:
        handle = self.manager.get(task_id)
        if not handle:
            self._error(404, f"no task {task_id}")
        return handle

    # ----------------------------------------------------------------- routes

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        try:
            if parts[:2] == ["api", "tasks"]:
                if len(parts) == 2:
                    return self._json(200, self.manager.list())
                handle = self._task_or_404(parts[2])
                if not handle:
                    return
                if len(parts) == 3:
                    return self._json(200, {**handle.meta(), "events": handle.history})
                if parts[3] == "events":
                    return self._sse(handle)
                if parts[3] == "files":
                    if len(parts) == 4:
                        return self._list_files(handle)
                    return self._send_file_content(handle, "/".join(parts[4:]))
            if parts[:1] == ["api"]:
                return self._error(404, "unknown endpoint")
            return self._static(path)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
        if parts[:2] != ["api", "tasks"]:
            return self._error(404, "unknown endpoint")
        body = self._body()

        if len(parts) == 2:
            task = (body.get("task") or "").strip()
            if not task:
                return self._error(400, "task text is required")
            params = {
                k: body[k]
                for k in ("model", "base_url", "sandbox", "image", "max_iterations", "budget_tokens")
                if body.get(k) not in (None, "")
            }
            try:
                handle = self.manager.create(task, params)
            except Exception as exc:  # noqa: BLE001 — e.g. missing API key
                return self._error(500, f"{type(exc).__name__}: {exc}")
            return self._json(201, handle.meta())

        handle = self._task_or_404(parts[2])
        if not handle or len(parts) != 4:
            if handle:
                self._error(404, "unknown endpoint")
            return

        if parts[3] == "stop":
            if handle.status != "running" or not handle.agent:
                return self._error(409, "task is not running")
            handle.agent.stop_requested = True
            return self._json(202, {"ok": True})

        if parts[3] == "messages":
            text = (body.get("text") or "").strip()
            if not text:
                return self._error(400, "text is required")
            if handle.status != "running" or not handle.agent:
                return self._error(409, "task is not running — use resume")
            handle.agent.inbox.append(text)
            return self._json(202, {"ok": True})

        if parts[3] == "resume":
            try:
                self.manager.resume(handle, (body.get("text") or "").strip() or None)
            except ValueError as exc:
                return self._error(409, str(exc))
            except Exception as exc:  # noqa: BLE001
                return self._error(500, f"{type(exc).__name__}: {exc}")
            return self._json(202, handle.meta())

        return self._error(404, "unknown endpoint")

    # -------------------------------------------------------------------- sse

    def _sse(self, handle: TaskHandle) -> None:
        snapshot, q = self.manager.subscribe(handle)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in snapshot:
                self._send_event(event)
            # After history replay, a finished task with no live producer gets
            # an explicit eof so the client can close instead of reconnecting.
            while True:
                if handle.status != "running" and q.empty():
                    self.wfile.write(b"event: eof\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                try:
                    event = q.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._send_event(event)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        finally:
            self.manager.unsubscribe(handle, q)

    def _send_event(self, event: dict) -> None:
        data = json.dumps(event["payload"], sort_keys=True, ensure_ascii=False)
        chunk = f"id: {event['seq']}\nevent: {event['kind']}\ndata: {data}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    # ------------------------------------------------------------------ files

    def _workdir_path(self, handle: TaskHandle, rel: str) -> Path | None:
        root = Path(handle.workdir).resolve()
        target = (root / rel).resolve()
        if root not in (target, *target.parents):
            return None
        return target

    def _list_files(self, handle: TaskHandle) -> None:
        root = Path(handle.workdir)
        if not root.exists():
            return self._json(200, {"files": []})
        files = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            files.append(
                {
                    "path": rel,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                    "internal": rel.startswith(".opposable/"),
                }
            )
        self._json(200, {"files": files})

    def _send_file_content(self, handle: TaskHandle, rel: str) -> None:
        target = self._workdir_path(handle, rel)
        if not target or not target.is_file():
            return self._error(404, f"no file {rel}")
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/"):
            mime += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ----------------------------------------------------------------- static

    def _static(self, path: str) -> None:
        if not WEB_DIST.exists():
            data = PLACEHOLDER_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIST / rel).resolve()
        if WEB_DIST.resolve() not in (target, *target.parents) or not target.is_file():
            target = WEB_DIST / "index.html"  # SPA fallback for client routes
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if rel.startswith("assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(data)


class OpposableServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, manager: TaskManager):
        super().__init__(addr, Handler)
        self.manager = manager


def serve(port: int = 8734, base_dir: str | None = None, provider_factory=None) -> OpposableServer:
    manager = TaskManager(base_dir=base_dir, provider_factory=provider_factory)
    return OpposableServer(("127.0.0.1", port), manager)
