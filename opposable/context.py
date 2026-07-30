"""Context ledger: the memory discipline of the agent.

Implements three principles from production agent systems:

1. **Append-only context.** Events are never mutated after being written.
   Serialization is deterministic (sorted keys, stable templates) so that
   identical prefixes stay byte-identical across iterations -> maximal
   KV-cache hit rate on the provider side.

2. **Restorable compression.** When the ledger grows past a token budget,
   old tool observations are evicted from the *rendered* context but the
   full text is written to the sandbox filesystem first. The stub left
   behind contains the path, so the agent can always re-read what it lost.
   Nothing is irreversibly destroyed.

3. **Recitation.** The current plan (todo.md) is re-injected at the tail of
   the context every iteration, pushing global objectives into the model's
   recent attention span and fighting lost-in-the-middle drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Rough chars-per-token heuristic; deliberately conservative.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


@dataclass
class Event:
    """One immutable entry in the ledger."""

    role: str                     # "user" | "assistant" | "tool"
    content: Any                  # provider-native content blocks
    tool_use_id: str | None = None
    tool_name: str | None = None
    evicted: bool = False         # observation compressed out of context
    stub: str | None = None       # restorable pointer left behind
    tokens: int = 0

    def render(self) -> dict:
        """Deterministic provider-message rendering."""
        if self.role == "tool":
            body = self.stub if self.evicted else self.content
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": self.tool_use_id,
                        "content": body,
                    }
                ],
            }
        return {"role": self.role, "content": self.content}


@dataclass
class Ledger:
    """Append-only event log with restorable compression."""

    budget_tokens: int = 60_000
    keep_recent_observations: int = 6   # never evict the newest N observations
    events: list[Event] = field(default_factory=list)

    def append(self, event: Event) -> None:
        if not event.tokens:
            event.tokens = estimate_tokens(
                json.dumps(event.content, sort_keys=True, ensure_ascii=False)
                if not isinstance(event.content, str)
                else event.content
            )
        self.events.append(event)

    def total_tokens(self) -> int:
        return sum(e.tokens if not e.evicted else estimate_tokens(e.stub or "") for e in self.events)

    def observations(self) -> list[Event]:
        return [e for e in self.events if e.role == "tool"]

    def compress(self, spill) -> int:
        """Evict oldest un-evicted observations until under budget.

        ``spill(event) -> str`` must persist the full observation somewhere
        durable (the sandbox filesystem) and return the path. The stub we
        leave in context tells the model exactly how to get the data back.
        Returns number of events evicted.
        """
        evicted = 0
        obs = self.observations()
        protected = set(id(e) for e in obs[-self.keep_recent_observations:])
        for event in obs:
            if self.total_tokens() <= self.budget_tokens:
                break
            if id(event) in protected or event.evicted:
                continue
            path = spill(event)
            event.evicted = True
            event.stub = (
                f"[observation compressed to save context. Full output of "
                f"{event.tool_name or 'tool'} was saved to {path} — "
                f"read that file if you need it again.]"
            )
            evicted += 1
        return evicted

    def render(self, recitation: str | None = None) -> list[dict]:
        """Render provider messages. Optionally append plan recitation."""
        messages = [e.render() for e in self.events]
        if recitation and messages:
            # Recite into the *last* user-role message so we never break the
            # assistant/tool alternation the API requires, and the plan sits
            # at the very end of the prompt where attention is strongest.
            last = messages[-1]
            if last["role"] == "user":
                blocks = last["content"]
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]
                    last["content"] = blocks
                blocks.append(
                    {
                        "type": "text",
                        "text": f"<current_plan>\n{recitation}\n</current_plan>",
                    }
                )
        return messages
