# AGENTS.md — rules for any agent working in this repo

This file governs all AI-agent (and honestly, human) contributions to **opposable**. Read [docs/HOSTED_PRD.md](docs/HOSTED_PRD.md) first, then [docs/FRONTEND_PRD.md](docs/FRONTEND_PRD.md). If a rule here conflicts with a convenient shortcut, the rule wins.

## 0. What you are working on

`opposable` is an open-source, Manus-style **general agent**: an LLM in a loop over a per-task Linux sandbox, with disciplined context engineering. The engine (`opposable/`, ~1k LOC, **zero runtime dependencies**) and the three-zone web UI (`web/` → built into `opposable/web/`) both work today for a single user on localhost.

**The current ambition is to host it on the internet for public use** — strangers sign up and run agents on our infrastructure. That migration is specified end-to-end in `docs/HOSTED_PRD.md` and tracked in `docs/TODO-hosted.md`. Two consequences for every change you make from here on:

- **The threat model changed.** Code that was merely risky on a laptop ("you are responsible for what your agent does") is disqualifying once a stranger can submit the prompt. Assume the person driving the agent is hostile and that the sandbox is already compromised.
- **The single-user local path must keep working.** Self-hosting on a laptop stays a first-class use case. Hosted-only behaviour goes behind the `OPPOSABLE_HOSTED=1` flag, not into the default path.

## 1. Commits

- **Commit frequently.** One logical change = one commit. A commit should be reviewable in under two minutes.
- **Format:** conventional-commit style, lowercase, imperative:
  - `feat: add pause/resume to the Sandbox interface`
  - `fix: keep the SSE cursor monotonic across reconnects`
  - `refactor: extract the worker claim loop from server.py`
  - `docs: record the microVM vendor decision`
  - `chore: bump playwright`
- The subject line describes **what changed and where**, not "update code" or "wip". Body (optional) explains *why* when it isn't obvious.
- Never batch unrelated changes into one commit. If your diff touches the sandbox and the SSE layer for different reasons, that's two commits.

## 2. Modularity — the core law

- **Production-ready from the outset.** No placeholder functions that "will be filled in later," no `// TODO: handle errors`. If the step ships it, the step ships it whole: typed, error-handled, edge-cased for the PRD's requirements.
- **Extensible, not bespoke.** Never write a function usable only for this one call site. Interfaces first: all execution goes through `Sandbox`, all model calls through the provider interface in `providers.py`, all tool dispatch through `ToolRuntime.execute`, all context through `Ledger`. If you find yourself calling `subprocess.run` from a tool branch, stop — you're bypassing the seam, and that seam is what makes the microVM backend a config change instead of a rewrite.
- **Build the interface before picking the vendor.** This is the PRD's §4 rule and it generalises: the abstraction is what keeps the vendor choice reversible.
- **Single-purpose modules.** A file does one thing. `sandbox.py` knows nothing about SSE; `server.py` knows nothing about how a tool is executed; `context.py` knows nothing about HTTP.
- **The Python core stays zero-dependency.** `pyproject.toml` has `dependencies = []` and stdlib-only is a product claim, not an accident. Hosting will force real dependencies (Postgres driver, Starlette/uvicorn, PyJWT) — those land **only** behind an extra (`pip install opposable[hosted]`), never in the base install, and never in `loop.py` / `context.py` / `tools/`. All npm packages live under `web/`.

## 3. Edits — targeted, never destructive

- **If a single-line edit does it, make a single-line edit. Never delete and rewrite a file when a targeted edit would do.**
- Touch only the files the current step requires. No drive-by refactors, no reformatting untouched code, no "while I'm here" cleanups, no dependency additions the plan didn't call for.
- Scrutinize your own diff before committing: if any changed line isn't required by the current step, revert it.
- **`opposable/web/` is build output** (gitignored, shipped as wheel package data). Never hand-edit it and never commit it — edit `web/src/` and run `npm --prefix web run build`.
- **The agent loop is load-bearing and subtle.** `loop.py`, `context.py` and `tools/__init__.py` implement the six principles in the README (byte-stable prompt, mask-don't-remove, restorable spill, plan recitation, errors kept in, no few-shots). Each has a cache or behaviour reason behind it — a "harmless" cleanup like injecting a timestamp into the system prompt, sorting keys differently, or tidying a tool error silently costs ~10× on input tokens or degrades the agent. Changing anything there requires saying, in the commit body, which principle you checked it against.
- **The agent loop is not being rewritten for hosting.** Per PRD §3, the split is an async edge plus synchronous workers. Do not async-ify `loop.py`.

## 4. Planning & execution loop

1. **Research before planning.** Prefer the industry-standard approach; confirm with current docs/web research before committing to a plan (microVM vendor APIs, Supabase Auth + RLS, SSE resumption semantics, `SKIP LOCKED` claim loops). Don't guess at APIs from memory, and don't design around a price or a limit you haven't verified — the PRD flags several figures as unverified for exactly this reason.
2. **Write the plan first** as `/docs/plan-<topic>.md` with numbered steps and acceptance criteria per step; commit it before implementing.
3. **Execute step by step. After every step, stop and check:**
   - Production-ready? (`pytest tests/ -q` green, `npm --prefix web run build` clean, handles the PRD edge cases for that surface)
   - Scope drift? Compare the diff against the plan step. **Do exactly what the plan requires — no more, no less.**
4. **If confused, blocked, or the plan turns out wrong: STOP and ask.** Don't improvise around ambiguity, don't silently substitute your own design decision, don't push through errors with workarounds.
5. Mid-build deviations (step impossible, better standard exists) → stop, propose, wait for a yes, update the plan file in the same commit as the change.
6. Significant architecture choices get a short record in `/docs/decisions/NNN-<slug>.md` (context → options → decision → consequences). The five already-made decisions are in PRD §12 — don't relitigate them without new evidence.

## 5. Quality floor (every step's check)

- `pytest tests/ -q` and `npm --prefix web run build` (which runs `tsc -b`) must pass before every push.
- TypeScript strict; no `any` unless the plan explicitly allows it. Python: type hints on every public function, no bare `except`.
- Frontend: no layout break at ≥768px; the computer panel becomes a slide-over under 1100px; both themes get a visual sweep. Visual work is verified by Playwright screenshots (`npm --prefix web run snap <scene>`, artifacts in `web/e2e/shots/`) reviewed before committing, and the happy path by `npm --prefix web run e2e`.
- New dependencies require justification in the plan first. **Default answer to new dependencies is no** — see the zero-dependency rule in §2.
- **No secrets in the repo, and no secrets in the sandbox.** Env vars via `.env.local` (gitignored), never committed. BYOK user keys live in a secret manager, never in the primary DB, never in logs (scrub at the logger, and assert it in a test), and never inside a sandbox — the one secret prompt injection cannot steal is the one the agent never sees.
- The resource limits, retention windows and egress rules in PRD §4/§8/§11 are requirements with numbers, not aspirations.

### Dev-host quirks (Windows) — do not "fix" these back

- `bash` is not on PATH for spawned processes; Git Bash lives at `C:\Program Files\Git\bin\bash.exe` (`_bash_path()` in `sandbox.py`).
- Inside Git Bash, `python3` is the Microsoft Store alias shim (exits 49); `python` is the real interpreter. Don't assume `python3` in shell commands.
- All file I/O and subprocess decoding must pass `encoding="utf-8"` — the platform default is cp1252 and emoji in model output crash writes otherwise.
- `web/e2e/fixture_server.py` imports `opposable/` at start-up: **restart it after editing any Python**, or UI checks silently verify stale behaviour.
- Playwright's `getByRole(name)` matches substrings and this UI's labels collide (`"Stop"` also matches `"Stopped <task>"`). Use `{ exact: true }` for short button names.

## 6. Security invariants (never regress these)

Once anything is publicly reachable, these are non-negotiable. A diff that weakens one is wrong even if it passes tests:

1. **Nothing from the host environment crosses into a sandbox.** Explicit env allowlist, never `{**os.environ}`.
2. **Nothing client-supplied selects an outbound destination.** `base_url`, `model` and `image` are allowlisted server-side, never passed through — a client-chosen `base_url` receives our `Authorization` header.
3. **Every ID lookup is a scoped fetch** (`WHERE id = $1 AND org_id = $ctx`), never fetch-then-check, and returns **404, never 403**, across tenants.
4. **User-generated content is never served from the app origin** — separate registrable domain, `nosniff`, `Content-Disposition: attachment` outside a tiny preview allowlist.
5. **Egress is default-deny through a proxy we control**, not a blocklist.
6. **`.opposable/` is filtered server-side.** It holds the system prompt and tool traces; client-side hiding is not filtering.

## 7. Priorities when time runs short

For the hosted migration, in order: (1) the Stage 0 ship-blockers in PRD §10 — credential leaks, sandbox isolation, identity and ownership, file origin — because none of the rest matters if the door is open; (2) SSE protocol correctness (resumption without gaps or duplicates); (3) the process split that makes horizontal scale possible; (4) everything else. Pooled billing, teams, and SSO are explicitly v2.

For the product itself, protect the agent loop's context discipline: it is the product thesis, and it is the part that is genuinely hard to get back once eroded.
