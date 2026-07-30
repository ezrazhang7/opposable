"""The action space.

Tool names are deliberately prefix-grouped (``shell_``, ``file_``, ``plan_``,
``web_``, ``task_``) so the loop's state machine can constrain the action
space by *masking* — steering tool_choice — rather than by adding/removing
tool definitions mid-run, which would invalidate the KV-cache and confuse
the model about tools referenced in earlier turns.

The full tool list is defined once, up front, and never changes.
"""

from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any

from ..sandbox import Sandbox

MAX_OBSERVATION_CHARS = 24_000  # hard cap per observation before truncation

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
}


class _TextExtractor(HTMLParser):
    """Strip an HTML page down to its visible text plus link targets."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("http"):
                self._parts.append(f" [{href}] ")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r" ?\n ?", "\n", raw)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def html_to_text(body: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(body)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed HTML falls back to raw
        return body
    return parser.text()


def _looks_like_html(content_type: str, body: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = body.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def _truncate(text: str, sandbox: Sandbox, label: str) -> str:
    """Truncate huge observations restorably: spill full text to a file."""
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    path = sandbox.write_file(
        f".opposable/spill/{label}.txt", text
    )
    head = text[: MAX_OBSERVATION_CHARS // 2]
    tail = text[-2_000:]
    return (
        f"{head}\n\n[... output truncated; full {len(text)} chars saved to "
        f"{path} — read it if needed ...]\n\n{tail}"
    )


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "plan_update",
        "description": (
            "Create or rewrite the task plan (todo.md). Call this FIRST on any "
            "non-trivial task, and again whenever you complete or reprioritize "
            "a step. Use markdown checkboxes. The current plan is recited back "
            "to you every turn — keeping it accurate keeps you on target."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Full todo.md content, markdown checkboxes."}
            },
            "required": ["plan"],
        },
    },
    {
        "name": "shell_exec",
        "description": (
            "Run a bash command in the sandbox. Full access inside the sandbox: "
            "install packages, run interpreters, start servers, manage processes. "
            "Returns exit code, stdout, stderr. Errors are left in your context "
            "on purpose — read them and adapt rather than blindly retrying."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds, default 120."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "file_write",
        "description": "Write a file in the sandbox (creates parent dirs). Prefer this over shell heredocs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "file_read",
        "description": (
            "Read a file from the sandbox. Also how you restore compressed "
            "observations — anything evicted from context lives on disk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a URL and return its text. Large pages are truncated in "
            "context but saved in full to the sandbox filesystem."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "task_complete",
        "description": (
            "Declare the task finished. Provide a summary of what was done and "
            "paths to every deliverable. Only call when the plan is fully checked off."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "deliverables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sandbox paths of output artifacts.",
                },
            },
            "required": ["summary"],
        },
    },
]


class ToolRuntime:
    """Executes tool calls against a sandbox; owns the plan state."""

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self.plan: str | None = None
        self._call_count = 0

    def execute(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Returns (observation_text, task_done)."""
        self._call_count += 1
        label = f"{self._call_count:03d}-{name}"
        try:
            if name == "plan_update":
                self.plan = args["plan"]
                self.sandbox.write_file("todo.md", self.plan)
                return "Plan updated and written to todo.md.", False

            if name == "shell_exec":
                code, out, err = self.sandbox.exec(
                    args["command"], timeout=int(args.get("timeout", 120))
                )
                obs = f"exit_code: {code}\nstdout:\n{out}\nstderr:\n{err}"
                return _truncate(obs, self.sandbox, label), False

            if name == "file_write":
                path = self.sandbox.write_file(args["path"], args["content"])
                return f"Wrote {len(args['content'])} chars to {path}.", False

            if name == "file_read":
                return _truncate(self.sandbox.read_file(args["path"]), self.sandbox, label), False

            if name == "web_fetch":
                req = urllib.request.Request(
                    args["url"], headers={"User-Agent": "opposable/0.1"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    body = resp.read(2_000_000).decode("utf-8", errors="replace")
                if _looks_like_html(content_type, body):
                    # Markup is ~5-10x the tokens of the visible text and gets
                    # re-sent every iteration. Keep the raw HTML restorable on
                    # disk; put only the extracted text in context.
                    raw_path = self.sandbox.write_file(
                        f".opposable/spill/{label}-raw.html", body
                    )
                    body = (
                        f"[HTML stripped to text; raw page saved to {raw_path}]\n\n"
                        + html_to_text(body)
                    )
                return _truncate(body, self.sandbox, label), False

            if name == "task_complete":
                deliverables = args.get("deliverables", [])
                summary = args["summary"]
                text = summary + (
                    "\n\ndeliverables:\n" + "\n".join(deliverables) if deliverables else ""
                )
                return text, True

            return f"Unknown tool: {name}", False
        except Exception as exc:  # noqa: BLE001 — errors belong in context
            # Keep the wrong stuff in: the model sees the failure and adapts.
            return f"TOOL ERROR ({name}): {type(exc).__name__}: {exc}", False


def render_args(args: dict) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)
