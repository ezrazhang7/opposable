# opposable

**An open-source Manus-style general agent. One loop, one sandbox, disciplined context.**

The manus is the hand. The opposable thumb is what made it useful.

Manus (now Meta) proved that a "virtual computer agent" is mostly not a model — it's an LLM in a loop over a per-task Linux sandbox, plus ruthless context engineering. Their own engineering blog spelled out the principles. `opposable` is a from-scratch, zero-dependency implementation of that architecture you can run on your laptop, point at any model, and read in an afternoon.

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
opposable run "scrape the top 10 HN stories, analyze the themes, write a report to report.md"
```

Or against any OpenAI-compatible endpoint (vLLM, Ollama, OpenAI):

```bash
opposable run --base-url http://localhost:11434/v1 --model qwen2.5-coder "..."
```

Or in a real per-task container (root inside, contained outside):

```bash
opposable run --sandbox docker "install ffmpeg and transcode ./input.mov to webm"
```

Interrupted? State is persisted every iteration:

```bash
opposable resume .opposable-ab12cd34
```

## Architecture

```
┌────────────────────────────────────────────────────┐
│  Agent loop (loop.py)                              │
│  byte-stable system prompt · state-machine masking │
│        │                              ▲            │
│        ▼ action (tool call)           │ observation│
│  ┌───────────────┐   spill/restore  ┌────────────┐ │
│  │  ToolRuntime   │◄───────────────►│   Ledger    │ │
│  │ shell · files  │                 │ append-only │ │
│  │ web · plan     │                 │ restorable  │ │
│  └───────┬───────┘                  │ compression │ │
│          ▼                          └────────────┘ │
│  ┌──────────────────────────┐                      │
│  │ Sandbox: local | docker  │  ← filesystem =      │
│  │ (per-task, persistent)   │    external memory   │
│  └──────────────────────────┘                      │
└────────────────────────────────────────────────────┘
```

No planner/executor/critic committee. A single loop with disciplined context beats a bureaucracy of sub-agents at this scale — the plan lives in `todo.md`, not in an org chart.

## The six principles (and where they live)

Every design decision here traces to a production lesson published by the Manus team:

1. **Design around the KV-cache.** The system prompt is byte-identical every iteration (no timestamps, no mutable state), the ledger is append-only, and serialization is deterministic (`sort_keys=True` everywhere). Identical prefixes → cache hits → ~10x cheaper input tokens. → `loop.py`, `context.py`
2. **Mask, don't remove.** All tools are defined once, up front, and never change mid-run. The loop's state machine constrains the action space via `tool_choice` (force `plan_update` on turn one, `any` thereafter) instead of adding/removing tool definitions — which would nuke the cache and confuse the model about tools referenced in old turns. Tool names are prefix-grouped (`shell_`, `file_`, `plan_`, `web_`, `task_`) so masking can extend to whole families. → `tools/__init__.py`, `loop.py`
3. **Filesystem as context.** Huge observations are truncated *restorably*: the full text is spilled to `.opposable/spill/`, and the stub in context contains the path. The agent is prompted to treat files as externalized memory. Nothing is irreversibly compressed. → `tools/__init__.py`, `context.py`
4. **Recite the plan.** The agent maintains `todo.md` via `plan_update`; the loop re-injects the current plan at the *tail* of the context every turn, pushing global objectives into recent attention and fighting lost-in-the-middle drift over 50-call tasks. → `context.py::Ledger.render`
5. **Keep the wrong stuff in.** Tool errors and stack traces are appended verbatim, never cleaned up or silently retried. Failure evidence is how the model updates its priors and stops repeating mistakes. → `tools/__init__.py::ToolRuntime.execute`
6. **Don't get few-shotted.** No canned action-observation exemplars in the prompt; behavior is specified by instruction, not by pattern the model will over-imitate on repetitive tasks. → `loop.py::SYSTEM_PROMPT`

## Join / beat / skip vs. Manus

| Capability | Manus | opposable |
|---|---|---|
| Per-task isolated sandbox | cloud VM, root, zero-trust | **join** — Docker backend (root inside, disposable) or local dir |
| Agent loop + context engineering | proprietary, principles published | **join** — full open implementation of all six principles |
| Sleep/wake task persistence | hibernating VMs, 7–21 day retention | **join** — state.json every iteration, `resume` command, no expiry: it's your disk |
| Model | Claude Sonnet + Qwen finetunes | **beat** — bring-your-own: Anthropic native or any OpenAI-compatible endpoint, incl. fully local |
| Transparency / auditability | closed | **beat** — every event in the ledger is inspectable; the whole engine is ~1k LOC |
| Cost | $39–199/mo + credits | **beat** — your API bill, nothing else |
| Managed browser automation | CDP browser in VM | **skip (for now)** — `web_fetch` covers research tasks; a Playwright tool slots into the existing runtime cleanly |
| Hosted deploy to public URLs | one click | **skip** — agent can start servers in its sandbox; exposing them is your infra decision |
| Wide Research / fan-out subagents | fleet of parallel sandboxes | **skip (for now)** — the `Agent` class is embeddable; parallel fan-out is a for-loop away |

## Extending

Add a tool = append one schema to `TOOL_SCHEMAS` + one branch in `ToolRuntime.execute`. Keep the name prefix-grouped. Never remove tools mid-run; mask instead.

Embed the agent:

```python
from opposable.loop import Agent
from opposable.providers import AnthropicProvider
from opposable.sandbox import DockerSandbox

agent = Agent(AnthropicProvider(), DockerSandbox())
result = agent.run("audit this repo's dependencies for known CVEs and write findings.md")
```

## Tests

```bash
pytest tests/ -q
```

The suite runs a scripted model against a **real** sandbox — real shell, real files — proving forced planning, error-in-context adaptation, restorable compression, plan recitation, deterministic rendering, and mid-task resume, all without an API key.

## Safety

A general agent with a shell is a chainsaw. Defaults are conservative — `LocalSandbox` confines the working directory but shares your host; use `--sandbox docker` for anything you wouldn't run by hand. You are responsible for what your agent does.

MIT.
