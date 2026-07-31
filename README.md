# opposable

**An open-source Manus-style general agent. One loop, one sandbox, disciplined context.**

The manus is the hand. The opposable thumb is what made it useful.

Manus (now Meta) proved that a "virtual computer agent" is mostly not a model — it's an LLM in a loop over a per-task Linux sandbox, plus ruthless context engineering. Their own engineering blog spelled out the principles. `opposable` is a from-scratch, zero-dependency implementation of that architecture you can run on your laptop, point at any model, and read in an afternoon.

```bash
pip install -e .
cp .env.example .env.local   # then put your ANTHROPIC_API_KEY in it
opposable run "scrape the top 10 HN stories, analyze the themes, write a report to report.md"
```

`opposable` loads `.env.local` and `.env` automatically (searched from the current directory upward), so you set your key once instead of exporting it in every terminal. Real environment variables always win, then `.env.local` (personal, gitignored), then `.env`. See [.env.example](.env.example) for all supported variables — including `OPPOSABLE_MODEL` and `OPPOSABLE_BASE_URL` for OpenAI-compatible endpoints.

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

## Web UI

```bash
npm --prefix web install && npm --prefix web run build   # once; Node is build-time only
opposable serve                                          # http://127.0.0.1:8734
```

Three zones, Manus-style: a rail of every session, the chat stream, and
**opposable's computer** — the panel showing the tool it is using right now,
with a terminal / editor / reader / checklist renderer per tool prefix and the
verbatim observation one click away. Tool calls appear in the chat as action
chips; clicking one pins the panel to that step. The footer scrubs the whole
timeline, so any past session can be replayed step by step. Finishing a task
gives you a summary card with its deliverables, openable and downloadable from
a files drawer over the sandbox workdir.

The Python core stays zero-dependency — `server.py` is stdlib `ThreadingHTTPServer`
plus SSE, and every npm package lives under `web/`. During frontend work,
`npm --prefix web run dev` serves the SPA on :5173 and proxies `/api` to the
Python server.

The build lands in **`opposable/web/`** — inside the Python package, so the
assets travel in a wheel and `pip install opposable` gets a working UI rather
than an API with a placeholder page. That directory is gitignored build output:
run the frontend build before `pip wheel`/`python -m build`, and in CI before
packaging. Node is never needed at runtime.

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

The UI has its own end-to-end check — create a task, watch it stream, see it
complete, replay it — driven by headless Chromium against the same scripted
model:

```bash
npm --prefix web run e2e
```

## Safety

A general agent with a shell is a chainsaw. Defaults are conservative — `LocalSandbox` confines the working directory but shares your host; use `--sandbox docker` for anything you wouldn't run by hand. You are responsible for what your agent does.

MIT.
