"""Web bridge: the agent engine exposed over REST + SSE, stdlib only.

The frontend (web/) is a static SPA; this server is its entire backend:

    POST /api/tasks                  start a task -> {id}
    GET  /api/tasks                  list all sessions (live + on disk)
    GET  /api/tasks/{id}             metadata + full event history
    GET  /api/tasks/{id}/events      SSE live stream (history replayed first)
    POST /api/tasks/{id}/stop        cooperative stop
    POST /api/tasks/{id}/messages    follow-up guidance while running (user event)
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

import hashlib
import hmac
import json
import mimetypes
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import auth, config, quotas, secrets_store
from .audit import AuditLog
from .auth import Identity
from .loop import Agent, RunResult
from .providers import AnthropicProvider, OpenAICompatProvider, Provider
from .sandbox import DockerSandbox, LocalSandbox
from .store import Store

# Inside the package, so `pip install opposable` carries the UI with it.
# Vite writes here (web/vite.config.ts) and pyproject ships it as package data.
WEB_DIST = Path(__file__).resolve().parent / "web"

PLACEHOLDER_PAGE = """<!doctype html><meta charset="utf-8">
<title>opposable</title>
<body style="font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center;color:#57534e">
<h1 style="color:#1c1917">opposable</h1>
<p>API is up. The web UI has not been built yet:</p>
<pre style="text-align:left;background:#f5f5f4;padding:1em;border-radius:12px">npm --prefix web install
npm --prefix web run build</pre>
<p>then reload this page.</p></div>
"""

RESUME_TASK = "Continue the task. Re-read todo.md and finish remaining steps."


#: Extensions we will render in a browser tab, mapped to the type we will
#: claim they are. Everything else downloads. Note what is absent: .html and
#: .svg are never inline, because both execute script.
PREVIEWABLE_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8",
    ".json": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Sent with the SPA. 'unsafe-inline' for styles only: the build inlines a
#: few dynamic style attributes. Scripts get no such exemption.
SPA_CSP = (
    "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    "img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "connect-src 'self'; form-action 'self'"
)


def _is_internal(rel: str) -> bool:
    return rel.startswith(".opposable/") or rel == ".opposable"


def _hide_internals() -> bool:
    """Single-operator installs may inspect their own agent's traces; a
    multi-tenant one may not, and that is not a UI decision."""
    return config.auth_enabled()


def _signed_file_url(origin: str, task_id: str, rel: str) -> str:
    expires = str(int(time.time()) + config.FILE_URL_TTL_SECONDS)
    encoded = "/".join(quote(part, safe="") for part in rel.split("/"))
    signature = _file_signature(task_id, rel, expires)
    return f"{origin}/files/{task_id}/{encoded}?exp={expires}&sig={signature}"


def _file_signature(task_id: str, rel: str, expires: str) -> str:
    # The path is inside the signed message, so a valid signature for one file
    # is not a valid signature for another.
    message = f"{task_id}\n{rel}\n{expires}".encode("utf-8")
    return hmac.new(config.file_signing_key(), message, hashlib.sha256).hexdigest()


def _verify_file_signature(task_id: str, rel: str, expires: str, signature: str) -> bool:
    key = config.file_signing_key()
    if not key or not signature:
        return False
    try:
        if int(expires) < time.time():
            return False
    except ValueError:
        return False
    return hmac.compare_digest(_file_signature(task_id, rel, expires), signature)


def _check_params(params: dict) -> None:
    """Every client-supplied value that picks a destination or an image is
    allowlisted. `base_url` in particular decides who receives our
    ``Authorization: Bearer`` header (HOSTED_PRD §2 finding 3)."""
    config.check_param("model", params.get("model"), config.allowed_models())
    config.check_param("base_url", params.get("base_url"), config.allowed_base_urls())
    config.check_param("image", params.get("image"), config.allowed_images())
    sandbox = params.get("sandbox")
    if sandbox not in (None, "", "local", "docker"):
        raise config.ConfigError(f"sandbox {sandbox!r} is not permitted")


def default_provider_factory(params: dict) -> Provider:
    model = params.get("model") or os.environ.get("OPPOSABLE_MODEL", "claude-sonnet-4-6")
    base_url = params.get("base_url") or os.environ.get("OPPOSABLE_BASE_URL")
    # Resolved by the manager from the org's secret reference; never client
    # settable, never written to meta.json, never inside a sandbox.
    api_key = params.get("_api_key")
    if base_url:
        return OpenAICompatProvider(model=model, base_url=base_url, api_key=api_key)
    return AnthropicProvider(model=model, api_key=api_key)


# Task ids are hex and nothing else. Beyond hygiene: the id is interpolated
# into a directory name, so ".opposable-../../etc" would have walked out of
# the base directory entirely.
TASK_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")


@dataclass
class TaskHandle:
    id: str
    task: str
    created: float
    workdir: str
    state_dir: Path
    org_id: str = auth.LOCAL_ORG
    created_by: str = auth.LOCAL_USER
    on_trial: bool = False
    started_at: float = 0.0
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
            "org_id": self.org_id,
            "created_by": self.created_by,
            "model": self.params.get("model"),
            "sandbox": self.params.get("sandbox", "local"),
        }


class TrialExhausted(RuntimeError):
    """The pooled trial is spent and no BYOK key is configured."""


class TaskManager:
    """Owns every task: registry of live handles + lazy loading from disk."""

    #: How often the wall-clock watchdog sweeps.
    WATCHDOG_INTERVAL = 5

    def __init__(self, base_dir: str | None = None, provider_factory=None, store: Store | None = None):
        self.base_dir = Path(base_dir or Path.cwd())
        self.provider_factory = provider_factory or default_provider_factory
        self.tasks: dict[str, TaskHandle] = {}
        self.lock = threading.Lock()
        self.store = store or (Store(self.base_dir / ".opposable-identity.db")
                               if config.auth_enabled() else None)
        self.secrets = secrets_store.build(self.base_dir)
        self.audit = AuditLog(self.base_dir / ".opposable-audit.jsonl")
        self.egress_meter = quotas.EgressMeter()
        self._watchdog: threading.Thread | None = None

    # ----------------------------------------------------------- credentials

    def resolve_credentials(self, identity: Identity) -> tuple[str | None, bool]:
        """Pick the key this task runs on. Returns ``(api_key, on_trial)``.

        ``None`` means "the process's own environment key" — which is the
        local operator's key locally, and the platform's trial key in hosted
        mode. Those are the only two cases, and the trial one is capped.
        """
        if not self.store or identity.is_local:
            return None, False
        org = self.store.org(identity.org_id) or {}
        ref = org.get("byok_ref")
        if ref:
            key = self.secrets.get(ref)
            if not key:
                raise TrialExhausted("your stored provider key could not be read; re-enter it")
            return key, False
        if org.get("trial_tasks_used", 0) >= config.TRIAL_TASKS:
            raise TrialExhausted(
                "your free trial is used up — add your own provider key to continue"
            )
        if org.get("trial_micros_used", 0) >= config.TRIAL_MICROS:
            raise TrialExhausted(
                "your free trial budget is used up — add your own provider key to continue"
            )
        return None, True

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
        # Outside the lock: auditing must never be able to stall the agent.
        self._observe(handle, kind, payload)

    def _observe(self, handle: TaskHandle, kind: str, payload: dict) -> None:
        """Audit what the agent did, and meter what it pulled in.

        The event stream already carries every tool call and its result, so
        this rides on it rather than threading a second channel through the
        loop.
        """
        if kind == "tool":
            self.audit.record(
                f"tool.{payload.get('name', '?')}",
                org_id=handle.org_id,
                user_id=handle.created_by,
                task_id=handle.id,
                args=json.dumps(payload.get("args", {}), sort_keys=True),
            )
        elif kind == "observation" and payload.get("name") == "web_fetch":
            total = self.egress_meter.record(handle.org_id, len(payload.get("text", "")))
            self._enforce_egress(handle, total)

    def _enforce_egress(self, handle: TaskHandle, total: int) -> None:
        plan = (self.store.org(handle.org_id) or {}).get("plan") if self.store else None
        if quotas.should_suspend_for_egress(total, plan):
            # Suspended, not throttled: exfiltration that is merely slowed
            # down still completes.
            self.audit.record(
                "abuse.suspend", org_id=handle.org_id, user_id=handle.created_by,
                task_id=handle.id, reason="egress", bytes=total,
            )
            if self.store:
                self.store.suspend_user(handle.created_by, "sustained high egress")
            self.stop(handle)
        elif total > quotas.limits_for(plan).egress_bytes_per_hour:
            self.audit.record(
                "quota.egress", org_id=handle.org_id, task_id=handle.id, bytes=total
            )
            self.stop(handle)

    def stop(self, handle: TaskHandle) -> None:
        if handle.agent:
            handle.agent.stop_requested = True

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
        kind = params.get("sandbox") or "local"
        config.check_sandbox(kind)
        if kind == "docker":
            sandbox = DockerSandbox(image=params.get("image", "ubuntu:24.04"))
        else:
            sandbox = LocalSandbox(root=handle.workdir)
        # Immutable per-task manifest: restoring means "the same box again",
        # not "whatever the default happens to be by then" (HOSTED_PRD §4).
        manifest_path = handle.state_dir / "manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps({**sandbox.manifest(), "created": handle.created}, sort_keys=True),
                encoding="utf-8",
            )
        return Agent(
            provider=self.provider_factory(params),
            sandbox=sandbox,
            max_iterations=int(params.get("max_iterations", 60)),
            budget_tokens=int(params.get("budget_tokens", 60_000)),
            state_dir=str(handle.state_dir),
            on_event=lambda kind, payload: self._emit(handle, kind, payload),
        )

    def create(self, task: str, params: dict, identity: Identity = auth.LOCAL_IDENTITY) -> TaskHandle:
        self._check_quotas(identity)
        api_key, on_trial = self.resolve_credentials(identity)
        if api_key:
            params = {**params, "_api_key": api_key}
        # Full 128 bits. The old uuid4().hex[:8] was 32 bits: enumerable, and
        # at ~65k tasks a coin flip to collide -- which silently corrupts one
        # task with another's events rather than failing loudly.
        task_id = uuid.uuid4().hex
        workdir = self.base_dir / f".opposable-{task_id}"
        state_dir = workdir / ".opposable" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        handle = TaskHandle(
            id=task_id,
            task=task,
            created=time.time(),
            workdir=str(workdir),
            state_dir=state_dir,
            org_id=identity.org_id,
            created_by=identity.user_id,
            on_trial=on_trial,
            params=params,
        )
        with self.lock:
            self.tasks[task_id] = handle
        handle.agent = self._build_agent(handle)
        self._write_meta(handle)
        self._start_worker(handle, task, resumed=False)
        return handle

    def add_message(self, handle: TaskHandle, text: str) -> None:
        """Queue follow-up guidance for the next iteration, and put it in the
        transcript: the model will see it as a user turn, so the UI must too."""
        if not handle.agent:
            raise ValueError("task has no agent")
        handle.agent.inbox.append(text)
        self._emit(handle, "user", {"text": text})

    def resume(self, handle: TaskHandle, message: str | None = None) -> None:
        if handle.status == "running":
            raise ValueError("task is already running")
        prompt = message or RESUME_TASK
        handle.agent = self._build_agent(handle)
        if handle.agent.load_state():
            # Agent.run() ignores its task argument when the ledger already has
            # history, so the resume prompt must travel via the inbox instead.
            handle.agent.inbox.append(prompt)
        # Emitted before the worker starts so the transcript reads in order:
        # the guidance, then the run it kicked off.
        self._emit(handle, "user", {"text": prompt})
        handle.status = "running"
        self._write_meta(handle)
        self._start_worker(handle, prompt, resumed=True)

    def _check_quotas(self, identity: Identity) -> None:
        if not self.store or identity.is_local:
            return
        plan = (self.store.org(identity.org_id) or {}).get("plan")
        with self.lock:
            running = sum(
                1 for h in self.tasks.values()
                if h.org_id == identity.org_id and h.status == "running"
            )
        quotas.check_concurrency(running, plan)
        quotas.check_egress(self.egress_meter.total(identity.org_id), plan)

    def _ensure_watchdog(self) -> None:
        """One thread watches every running task's wall clock.

        A run that never ends is the ordinary failure here, not the exotic
        one: a model looping costs real money and holds a sandbox open, and
        the cooperative stop flag already exists to end it.
        """
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watch, daemon=True, name="wall-clock")
        self._watchdog.start()

    def _watch(self) -> None:
        while True:
            time.sleep(self.WATCHDOG_INTERVAL)
            with self.lock:
                handles = [h for h in self.tasks.values() if h.status == "running"]
            for handle in handles:
                plan = (self.store.org(handle.org_id) or {}).get("plan") if self.store else None
                if quotas.overran_wall_clock(handle.started_at, plan):
                    self.audit.record(
                        "quota.wall_clock", org_id=handle.org_id, task_id=handle.id,
                        seconds=int(time.time() - handle.started_at),
                    )
                    self.stop(handle)

    def _charge_trial(self, handle: TaskHandle) -> None:
        if not (handle.on_trial and self.store and handle.agent):
            return
        micros = config.estimate_micros(handle.params.get("model"), handle.agent.usage)
        self.store.record_trial_use(handle.org_id, micros)

    def _start_worker(self, handle: TaskHandle, task: str, resumed: bool) -> None:
        handle.started_at = time.time()
        self._ensure_watchdog()
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
                # Scrubbed: a provider error can quote the request, and the
                # request carries the key.
                self._emit(
                    handle, "status",
                    {
                        "state": "error",
                        "detail": secrets_store.scrub(f"{type(exc).__name__}: {exc}"),
                    },
                )
            else:
                # "complete" is already conveyed by the done event; the status
                # kind only carries running / stopped / error (see PRD table).
                if handle.status != "complete":
                    self._emit(handle, "status", {"state": handle.status})
            self._charge_trial(handle)
            self._write_meta(handle)

        handle.thread = threading.Thread(target=work, daemon=True, name=f"task-{handle.id}")
        handle.thread.start()

    # ------------------------------------------------------------- discovery

    def _load_from_disk(self, task_id: str) -> TaskHandle | None:
        if not TASK_ID_RE.match(task_id):
            return None
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
            org_id=meta.get("org_id", auth.LOCAL_ORG),
            created_by=meta.get("created_by", auth.LOCAL_USER),
            params={"model": meta.get("model"), "sandbox": meta.get("sandbox", "local")},
        )
        events_path = state_dir / "events.jsonl"
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    handle.history.append(json.loads(line))
        return handle

    def get(self, task_id: str, org_id: str | None = None) -> TaskHandle | None:
        """Scoped fetch. ``org_id`` is part of the lookup, not a check applied
        afterwards, and a miss is indistinguishable from "no such task" —
        callers turn both into 404, never 403. A 403 confirms the id exists
        and turns a blind scan into an oracle (HOSTED_PRD §7)."""
        with self.lock:
            handle = self.tasks.get(task_id)
        if handle is None:
            handle = self._load_from_disk(task_id)
            if handle:
                with self.lock:
                    self.tasks.setdefault(task_id, handle)
                    handle = self.tasks[task_id]
        if handle and org_id is not None and handle.org_id != org_id:
            return None
        return handle

    def list(self, org_id: str | None = None) -> list[dict]:
        ids = {p.name.removeprefix(".opposable-") for p in self.base_dir.glob(".opposable-*") if p.is_dir()}
        with self.lock:
            ids.update(self.tasks.keys())
        handles = [h for h in (self.get(i, org_id) for i in sorted(ids)) if h]
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

    def _task_or_404(self, task_id: str, identity: Identity) -> TaskHandle | None:
        handle = self.manager.get(task_id, identity.org_id)
        if not handle:
            # Deliberately identical to the not-found case: another tenant's
            # task must not be distinguishable from one that does not exist.
            self._error(404, "no such task")
        return handle

    # -------------------------------------------------------------- identity

    def _identity(self) -> Identity | None:
        if not config.auth_enabled():
            return auth.LOCAL_IDENTITY
        secret = auth.session_from_cookies(self.headers.get("Cookie"))
        return auth.identity_for(self.manager.store, secret)

    def _require_identity(self) -> Identity | None:
        identity = self._identity()
        if identity is None:
            self._error(401, "authentication required")
        return identity

    def _check_csrf(self) -> bool:
        if not config.auth_enabled():
            return True
        try:
            auth.check_csrf(
                self.headers.get("Sec-Fetch-Site"),
                self.headers.get("Origin"),
                config.app_origin(),
            )
        except auth.AuthError as exc:
            self._error(403, str(exc))
            return False
        return True

    # ----------------------------------------------------------------- routes

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        try:
            if self._on_files_host():
                # The files host serves signed user content and nothing else:
                # no SPA, no API, no session.
                if parts[:1] == ["files"]:
                    return self._serve_signed_file(parts)
                return self._error(404, "not found")
            if parts[:2] == ["api", "auth"]:
                return self._auth_get(parts[2:])
            if parts[:2] == ["api", "tasks"]:
                identity = self._require_identity()
                if not identity:
                    return
                if len(parts) == 2:
                    return self._json(200, self.manager.list(identity.org_id))
                handle = self._task_or_404(parts[2], identity)
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
        if not self._check_csrf():
            return
        if parts[:2] == ["api", "auth"]:
            return self._auth_post(parts[2:], self._body())
        if parts[:2] != ["api", "tasks"]:
            return self._error(404, "unknown endpoint")
        identity = self._require_identity()
        if not identity:
            return
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
            # Identity gates before parameter validation: an unverified
            # account's input should not be processed at all.
            if config.hosted() and not identity.email_verified:
                return self._error(403, "verify your email address before running tasks")
            try:
                _check_params(params)
                # A 400 rather than a 500 from deep inside the worker: asking
                # for a development backend in hosted mode is a bad request.
                config.check_sandbox(params.get("sandbox") or "local")
            except config.ConfigError as exc:
                return self._error(400, str(exc))
            try:
                handle = self.manager.create(task, params, identity)
            except quotas.QuotaExceeded as exc:
                self.manager.audit.record(
                    "quota.refused", org_id=identity.org_id, user_id=identity.user_id,
                    reason=str(exc),
                )
                return self._error(429, str(exc))
            except TrialExhausted as exc:
                return self._error(402, str(exc))
            except Exception as exc:  # noqa: BLE001 — e.g. missing API key
                return self._error(500, secrets_store.scrub(f"{type(exc).__name__}: {exc}"))
            return self._json(201, handle.meta())

        handle = self._task_or_404(parts[2], identity)
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
            self.manager.add_message(handle, text)
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

    # ------------------------------------------------------------------- auth

    def _json_with_cookie(self, status: int, body: dict, cookie: str) -> None:
        data = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _auth_get(self, rest: list[str]) -> None:
        if not config.auth_enabled():
            return self._error(404, "authentication is not enabled")
        if rest == ["me"]:
            identity = self._require_identity()
            if not identity:
                return
            return self._json(200, {
                "user_id": identity.user_id,
                "org_id": identity.org_id,
                "email": identity.email,
                "email_verified": identity.email_verified,
            })
        if rest == ["keys"]:
            identity = self._require_identity()
            if not identity:
                return
            org = self.manager.store.org(identity.org_id) or {}
            # Never the key, not even masked: there is no use for it here that
            # is worth the risk of a logged response body.
            return self._json(200, {
                "configured": bool(org.get("byok_ref")),
                "provider": org.get("byok_provider"),
                "trial_tasks_remaining": max(
                    0, config.TRIAL_TASKS - int(org.get("trial_tasks_used", 0))
                ),
                "trial_micros_remaining": max(
                    0, config.TRIAL_MICROS - int(org.get("trial_micros_used", 0))
                ),
            })
        if rest == ["verify"]:
            query = parse_qs(urlsplit(self.path).query)
            token = (query.get("token") or [""])[0]
            user_id = self.manager.store.consume_verification(token)
            if not user_id:
                return self._error(400, "verification link is invalid or expired")
            return self._json(200, {"verified": True})
        return self._error(404, "unknown endpoint")

    def _auth_post(self, rest: list[str], body: dict) -> None:
        if not config.auth_enabled():
            return self._error(404, "authentication is not enabled")
        db = self.manager.store
        if rest == ["register"]:
            try:
                user = auth.register(
                    db,
                    body.get("email", ""),
                    body.get("password", ""),
                    terms_version=(
                        config.terms_version() if body.get("accept_terms") else None
                    ),
                    turnstile_token=body.get("turnstile_token"),
                    remote_ip=self.client_address[0],
                )
            except auth.AuthError as exc:
                return self._error(400, str(exc))
            self.manager.audit.record(
                "auth.register", org_id=user["org_id"], user_id=user["id"],
                terms_version=config.terms_version(),
            )
            secret = db.create_verification(user["id"])
            auth.send_verification(
                user["email"], auth.verification_link(config.app_origin() or "", secret)
            )
            return self._json(201, {"user_id": user["id"], "email": user["email"]})

        if rest == ["login"]:
            try:
                secret, identity = auth.login(db, body.get("email", ""), body.get("password", ""))
            except auth.AuthError as exc:
                self.manager.audit.record(
                    "auth.login_failed", user_id=body.get("email", ""), reason=str(exc)
                )
                return self._error(401, str(exc))
            self.manager.audit.record(
                "auth.login", org_id=identity.org_id, user_id=identity.user_id
            )
            return self._json_with_cookie(
                200,
                {"user_id": identity.user_id, "org_id": identity.org_id, "email": identity.email},
                auth.cookie_header(secret),
            )

        if rest == ["keys"]:
            identity = self._require_identity()
            if not identity:
                return
            provider = body.get("provider", "anthropic")
            key = (body.get("key") or "").strip()
            if provider not in ("anthropic", "openai"):
                return self._error(400, "unknown provider")
            if not key:
                # Clearing drops the value from the secret manager as well as
                # the reference; an orphaned secret is still a secret.
                org = db.org(identity.org_id) or {}
                if org.get("byok_ref"):
                    self.manager.secrets.delete(org["byok_ref"])
                db.set_byok(identity.org_id, None, None)
                return self._json(200, {"configured": False})
            ref = f"byok/{identity.org_id}"
            self.manager.secrets.put(ref, key)
            db.set_byok(identity.org_id, ref, provider)
            # The reference goes in the database; the key does not.
            return self._json(200, {"configured": True, "provider": provider})

        if rest == ["logout"]:
            secret = auth.session_from_cookies(self.headers.get("Cookie"))
            if secret:
                db.revoke_session(secret)
            return self._json_with_cookie(200, {"ok": True}, auth.clear_cookie_header())

        return self._error(404, "unknown endpoint")

    # -------------------------------------------------------------------- sse

    #: Seconds between SSE comment heartbeats.
    HEARTBEAT_SECONDS = 10

    #: Re-read the session row every sixth 10 s heartbeat. Authorizing only at
    #: connect means a user who logs out — or is suspended — keeps receiving
    #: live output until the task ends, and tasks here run for an hour.
    REAUTH_EVERY_PINGS = 6

    def _sse(self, handle: TaskHandle) -> None:
        secret = auth.session_from_cookies(self.headers.get("Cookie"))
        snapshot, q = self.manager.subscribe(handle)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        pings = 0
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
                    event = q.get(timeout=self.HEARTBEAT_SECONDS)
                except queue.Empty:
                    pings += 1
                    if pings % self.REAUTH_EVERY_PINGS == 0 and not self._session_still_valid(
                        secret, handle
                    ):
                        # A typed event, not a silent close: the client must
                        # know to stop and re-authenticate rather than
                        # reconnect straight into a login redirect loop.
                        self.wfile.write(b"event: auth_expired\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._send_event(event)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        finally:
            self.manager.unsubscribe(handle, q)

    def _session_still_valid(self, secret: str | None, handle: TaskHandle) -> bool:
        if not config.auth_enabled():
            return True
        identity = auth.identity_for(self.manager.store, secret)
        # Ownership is re-checked too: a membership can be removed without the
        # session itself being revoked.
        return identity is not None and identity.org_id == handle.org_id

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
            internal = _is_internal(rel)
            # Filtered here, not flagged for the client to hide. .opposable/
            # holds the system prompt and every tool trace; the operator of a
            # single-user install may look at their own, a tenant may not.
            if internal and _hide_internals():
                continue
            files.append(
                {
                    "path": rel,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                    "internal": internal,
                }
            )
        self._json(200, {"files": files})

    def _send_file_content(self, handle: TaskHandle, rel: str) -> None:
        if _is_internal(rel) and _hide_internals():
            return self._error(404, f"no file {rel}")
        origin = config.files_origin()
        if origin and not self._on_files_host():
            # Never serve user content from the app origin. The redirect is
            # short-lived and signed because the files host is a different
            # site and therefore has no session cookie.
            return self._redirect(_signed_file_url(origin, handle.id, rel))
        target = self._workdir_path(handle, rel)
        if not target or not target.is_file():
            return self._error(404, f"no file {rel}")
        self._send_user_content(target)

    def _send_user_content(self, target: Path) -> None:
        """Serve a file the agent produced, on the assumption that it is
        hostile — because a prompt-injected agent writing report.html is
        exactly how stored XSS arrives."""
        data = target.read_bytes()
        suffix = target.suffix.lower()
        inline = suffix in PREVIEWABLE_TYPES
        mime = PREVIEWABLE_TYPES.get(suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Disposition",
            f'{"inline" if inline else "attachment"}; filename="{target.name}"',
        )
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        # A leaked Referer is the most common real-world share-link failure.
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _on_files_host(self) -> bool:
        origin = config.files_origin()
        if not origin:
            return False
        host = (self.headers.get("Host") or "").lower()
        return bool(host) and host == origin.split("//")[-1].lower()

    def _serve_signed_file(self, parts: list[str]) -> None:
        """The files-host route. No cookie, no session — the signature is the
        entire authorization, which is why it is short-lived and covers the
        task id and path together."""
        if len(parts) < 3:
            return self._error(404, "not found")
        task_id, rel = parts[1], "/".join(parts[2:])
        query = parse_qs(urlsplit(self.path).query)
        expires = (query.get("exp") or ["0"])[0]
        signature = (query.get("sig") or [""])[0]
        if not _verify_file_signature(task_id, rel, expires, signature):
            return self._error(403, "link is invalid or has expired")
        handle = self.manager.get(task_id)
        if not handle or (_is_internal(rel) and _hide_internals()):
            return self._error(404, "not found")
        target = self._workdir_path(handle, rel)
        if not target or not target.is_file():
            return self._error(404, "not found")
        self._send_user_content(target)

    # ----------------------------------------------------------------- static

    def _static(self, path: str) -> None:
        if not WEB_DIST.exists():
            data = PLACEHOLDER_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._send_app_security_headers()
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
        self._send_app_security_headers()
        if rel.startswith("assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(data)

    def _send_app_security_headers(self) -> None:
        self.send_header("Content-Security-Policy", SPA_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")


class OpposableServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, manager: TaskManager):
        super().__init__(addr, Handler)
        self.manager = manager


def serve(port: int = 8734, base_dir: str | None = None, provider_factory=None) -> OpposableServer:
    problems = config.preflight()
    if problems:
        raise config.PreflightError(
            "refusing to start in hosted mode:\n  - " + "\n  - ".join(problems)
        )
    manager = TaskManager(base_dir=base_dir, provider_factory=provider_factory)
    return OpposableServer(("127.0.0.1", port), manager)
