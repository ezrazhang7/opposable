"""Model providers.

Design constraints that matter for agents specifically:

- The system prompt is passed separately and NEVER varies within a run
  (no timestamps, no mutable state) — a single changed token at position
  zero invalidates the entire KV-cache.
- ``tool_choice`` is threaded through so the loop's state machine can mask
  the action space ("auto" / "any" / a specific tool) without touching the
  tool definitions themselves.
- Providers are dumb transports. All intelligence about context shape
  lives in the ledger and the loop.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    raw_content: list[dict]
    stop_reason: str


class Provider:
    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
        max_tokens: int = 4096,
    ) -> ModelTurn:
        raise NotImplementedError


class AnthropicProvider(Provider):
    """Direct Messages API via stdlib HTTP. No SDK dependency."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("Set ANTHROPIC_API_KEY (or pass api_key).")

    def complete(self, system, messages, tools, tool_choice=None, max_tokens=4096) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        if tool_choice:
            payload["tool_choice"] = tool_choice
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        text_parts, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block["input"]))
        return ModelTurn(
            text="\n".join(text_parts),
            tool_calls=calls,
            raw_content=data.get("content", []),
            stop_reason=data.get("stop_reason", ""),
        )


class OpenAICompatProvider(Provider):
    """Any /v1/chat/completions endpoint: OpenAI, vLLM, Ollama, etc."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def complete(self, system, messages, tools, tool_choice=None, max_tokens=4096) -> ModelTurn:
        oa_messages = [{"role": "system", "content": system}]
        for m in messages:
            oa_messages.append(_to_openai(m))
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": oa_messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ],
        }
        if tool_choice:
            if tool_choice.get("type") == "any":
                payload["tool_choice"] = "required"
            elif tool_choice.get("type") == "tool":
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice["name"]},
                }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        msg = data["choices"][0]["message"]
        calls = [
            ToolCall(tc["id"], tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
            for tc in (msg.get("tool_calls") or [])
        ]
        raw = []
        if msg.get("content"):
            raw.append({"type": "text", "text": msg["content"]})
        for c in calls:
            raw.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
        return ModelTurn(
            text=msg.get("content") or "",
            tool_calls=calls,
            raw_content=raw,
            stop_reason=data["choices"][0].get("finish_reason", ""),
        )


def _to_openai(message: dict) -> dict:
    """Convert an Anthropic-shaped ledger message to OpenAI chat format."""
    content = message["content"]
    if isinstance(content, str):
        return {"role": message["role"], "content": content}
    if message["role"] == "assistant":
        text = "".join(b.get("text", "") for b in content if b["type"] == "text")
        tool_calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {"name": b["name"], "arguments": json.dumps(b["input"], sort_keys=True)},
            }
            for b in content
            if b["type"] == "tool_use"
        ]
        out: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            out["tool_calls"] = tool_calls
        return out
    # user role carrying tool_result blocks
    results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
    if results:
        r = results[0]
        body = r["content"]
        if isinstance(body, list):
            body = "".join(b.get("text", "") for b in body)
        return {"role": "tool", "tool_call_id": r["tool_use_id"], "content": body}
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    return {"role": "user", "content": text}


class ScriptedProvider(Provider):
    """Deterministic fake for tests: replays a fixed sequence of turns."""

    def __init__(self, turns: list[ModelTurn]):
        self.turns = list(turns)
        self.seen: list[dict] = []

    def complete(self, system, messages, tools, tool_choice=None, max_tokens=4096) -> ModelTurn:
        self.seen.append({"system": system, "messages": messages, "tool_choice": tool_choice})
        if not self.turns:
            raise RuntimeError("ScriptedProvider exhausted")
        return self.turns.pop(0)
