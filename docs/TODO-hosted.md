# opposable Hosted — implementation to-do

**Derived from** [HOSTED_PRD.md](HOSTED_PRD.md) (stages, decisions, open questions) and [FRONTEND_PRD.md](FRONTEND_PRD.md) (the UI this builds on). Working rules in [../AGENTS.md](../AGENTS.md).

**Date:** 2026-07-31 · **Status:** not started

Ordering rule: **Stage 0 gates public reachability.** Nothing is exposed to the internet until every Stage 0 box is ticked. Within Stage 0, group **0a** needs no new infrastructure and closes the worst holes — do it first, today.

Each item is scoped to stand alone and get its own commit. Write the plan file (`docs/plan-<topic>.md`) before starting a group, per AGENTS.md §4.

---

## Spikes — run these in parallel with 0a, they unblock 0b

These are PRD §12's open questions. Each is timeboxed; each produces a `docs/decisions/NNN-*.md` record.

- [ ] **S1 — microVM vendor (blocks 0b, blocks the whole lifecycle design).** Prototype the resume path on Fly Sprites: boot, run a task, pause, resume, confirm the filesystem survived, measure resume latency. **Confirm rates directly with Fly** — current pricing is attested only by third-party blogs (one a competitor's) for a ~7-month-old product. Fall back to E2B Pro if the numbers or the API don't hold up, accepting wall-clock billing. Timebox: 2 days.
- [ ] **S2 — own egress proxy vs. a vendor's policy.** One afternoon confirming whether any candidate platform gives default-deny egress, link-local blocking, post-redirect DNS re-resolution and SMTP blocking out of the box. Expected answer is "own it"; confirm before building.
- [ ] **S3 — free-tier sandbox-hours.** Needs a real cost model, so it waits on S1. Decide the number and confirm non-renewing (a refilling free tier is an abuse subscription).
- [ ] **S4 — does the pooled trial need a card?** ~$1 exposure per signup. Start with Turnstile + email verification + disposable-domain blocklist; revisit the moment abuse appears.
- [ ] **S5 — verify live model prices** before anything user-facing quotes a number (Opus 5 $5/$25, Sonnet 5 $3/$15, Haiku 4.5 $1/$5 per Mtok as of the PRD).

---

## Stage 0 — ship-blockers

*Exit criterion: a hostile user with a valid account can obtain nothing from the host, reach nothing on our network, and see nothing belonging to another user.*

### 0a — stop leaking credentials (no new infra, do first)

- [ ] `sandbox.py:81` — replace `env={**os.environ, …}` with an explicit allowlist: `PATH`, `HOME`, `LANG`, `OPPOSABLE_SANDBOX`, `TERM`. Nothing else crosses into a sandbox, ever.
- [ ] `server.py` create params — drop `base_url` from the client-settable set, or validate it against a server-side allowlist. Today it redirects our `Authorization: Bearer` header to an arbitrary host (`providers.py:144-150`).
- [ ] Same treatment for `model` and `image`: allowlist, don't pass through. Default to Sonnet 5; Opus is explicit opt-in.
- [ ] Test: a task cannot read `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from its shell.
- [ ] Test: a task created with a foreign `base_url` is rejected (or coerced) and no request carries our key off-allowlist.

### 0b — make the sandbox a sandbox

- [ ] Add `pause()` / `resume()` / `snapshot()` to the `Sandbox` interface; keep `exec` / `write_file` / `read_file` as-is. **Do this before S1 lands** — the interface is what keeps the vendor choice reversible.
- [ ] Implement `MicroVMSandbox` against the S1 winner.
- [ ] Gate `LocalSandbox` and `DockerSandbox` to dev-only: refuse to start when `OPPOSABLE_HOSTED=1`.
- [ ] Harden `DockerSandbox` anyway, for self-hosters: `--cap-drop=ALL --security-opt no-new-privileges:true --pids-limit=512 --memory=4g --memory-swap=4g --cpus=2 --read-only --tmpfs /tmp:size=1g --user 1000:1000 --network <isolated>`.
- [ ] Replace `write_file`'s `shlex.quote`-onto-the-command-line with `docker cp` / stdin — it breaks on large files at `ARG_MAX` today.
- [ ] Fix `LocalSandbox._resolve`: absolute paths pass through unchanged, so a model writing `/sandbox/report.md` escapes the sandbox root. Confine or reject.
- [ ] Enforce the resource limits as values: 2 vCPU · 4 GiB, **swap disabled** · `--pids-limit=512` · 10 GiB disk · 50 MB/s device I/O · 120 s default command timeout (600 s opt-in) · 30 min active wall clock then force-pause · 5–10 Mbit/s sustained egress.
- [ ] Egress, default-**deny** through an allowlist proxy we control (not a blocklist):
  - [ ] Block link-local **and its IPv4-mapped IPv6 form**, all RFC1918, and our own VPC.
  - [ ] Re-resolve DNS **after every redirect** (otherwise DNS rebinding walks straight through).
  - [ ] IMDSv2 enforced, IMDSv1 off, hop limit 1 — *and* remove link-local routes from the sandbox netns (hop-limit only covers bridge networking).
  - [ ] Block outbound SMTP (25/465/587) permanently.
  - [ ] Sandboxes in a **separate cloud account** with no network path to the control plane.
- [ ] Implement the lifecycle and expose it in the API so the existing status badges can show it: `running → idle (5–15 min) → paused → archived (7 d) → deleted (30 d)`.
- [ ] Per-task immutable manifest (base image digest, env, workdir archive pointer). Resume = restore the archive into a fresh sandbox from the same digest; native checkpoint/restore as a fast path only.
- [ ] Exclude `node_modules`, `.venv` and build caches from archives — 10–100× the size and fully reconstructible.
- [ ] Checkpoint and pause **between steps** rather than holding a live sandbox. Idle dominates cost; this also sidesteps vendor session caps.

### 0c — identity and ownership

- [ ] Create the Supabase project. Tables per PRD §6: `orgs`, `users`, `memberships`, `sessions`.
- [ ] Session cookie: `__Host-`, `HttpOnly`, `Secure`, `SameSite=Lax` (**not `Strict` — it breaks the OAuth callback**). Opaque token, only `sha256(secret)` stored.
- [ ] `Sec-Fetch-Site: same-origin` check on every mutating request, `Origin` check as fallback. (Preserve the two properties that make this cheap: bind `127.0.0.1` behind the proxy, and **no CORS headers anywhere**.)
- [ ] Add `org_id` to tasks; every handler does a scoped fetch (`WHERE id = $1 AND org_id = $ctx`) and returns **404, not 403**, across tenants.
- [ ] SSE: authorize at connect, then re-validate the **session row** (not the JWT) every ~60 s on the existing 10 s heartbeat; emit typed `event: auth_expired` and close on revoke. This closes today's real bug — auth is checked once at connect, so a logged-out user keeps receiving live output for the rest of an hour-long run.
- [ ] Client: call `EventSource.close()` **before** refreshing, or the browser reconnects into a login-redirect loop. `useSession.ts` already dedupes by `seq`.
- [ ] Widen task IDs from `uuid4().hex[:8]` (32 bits — enumerable, ~50% collision at ~65k tasks) to full `uuid4()`. Add `legacy_task_ids` so existing 8-hex URLs don't 404.
- [ ] Signup ladder: Turnstile + email verify + disposable-domain blocklist → pooled trial; a valid provider key → free tier; card → paid.
- [ ] Rate-limit on **money and device fingerprint, not IP** — residential proxy networks rotate millions of IPs.

### 0d — stop serving user content on our origin

- [ ] Serve `/files/*` from a **separate registrable domain** (not a subdomain), with `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` outside a small preview allowlist, and `Content-Security-Policy: default-src 'none'; sandbox`. Never `text/html` or `image/svg+xml` inline on the app origin.
- [ ] Filter `.opposable/` **server-side** in `_list_files` (`server.py:430-447`) — it currently ships the system prompt and tool traces to the client behind an `internal: true` flag and trusts the UI to hide them.
- [ ] Add a CSP to the SPA itself; it has none today.

### 0e — BYOK (v1 has no billing)

- [ ] BYOK key entry in the settings modal; store in a secret manager with a reference in Postgres — never the primary DB, never logs, never the sandbox.
- [ ] Logger scrubbing for provider keys, asserted in a test.
- [ ] LLM calls route through **our gateway**, so no credential ever enters a sandbox. This is also the only durable prompt-injection defence.
- [ ] Pooled trial on our key: 2–3 tasks, hard-capped ~$1 total, email-verified, no card. Treat the budget as marketing spend.
- [ ] AUP at least as strict as the provider's — Anthropic's policy applies to passthrough access, so BYOK does not exempt us.

### 0f — abuse response

- [ ] Per-user concurrency caps, wall-clock kill, egress volume caps.
- [ ] Auto-suspend on sustained-100%-CPU or high-egress signatures — mining and exfil each have an obvious shape.
- [ ] Structured audit log of every command, URL and file, retained ≥30 days.
- [ ] Monitored `abuse@`, with a documented triage path.

### 0g — the paperwork that gates the door

- [ ] ToS + AUP with the provider's prohibited-use list flowed down, accepted by **affirmative click at registration** (posting alone is unenforceable). Include an explicit suspension right.
- [ ] Privacy policy + retention schedule — **and make backup retention match it**; the mismatch is exactly the gap regulators look for.
- [ ] DMCA designated agent registered ($6, US Copyright Office, renew every 3 years) — without it there is no §512 safe harbour.
- [ ] DSAR workflow (one calendar month, extendable by two with a stated reason).
- [ ] Retention windows implemented, not just documented: commands/URLs/spend 30–90 d · transcripts 30 d default · security events 12 mo · billing 7 y. Scrub secrets on write, not on read.
- [ ] Tech E&O / cyber insurance quoted before there is revenue worth suing for.

---

## Stage 1 — protocol correctness, still one process

*Exit: a client disconnects mid-task and reconnects with zero duplicates and zero gaps.*

- [ ] Honour `Last-Event-ID` (header, with a query-param fallback) — today it's never read, so every reconnect replays the entire history and a deploy means N clients × full history at once. The wire already emits `id: {seq}`; the cursor exists, it just isn't used.
- [ ] Return `204` for a terminal task with no missed events.
- [ ] Emit `retry:` so clients back off on our terms.
- [ ] Hold the events file open instead of reopening per event, and move fan-out outside the lock (`server.py:103-111`).
- [ ] Bound subscriber queues and the task cache — both unbounded today.
- [ ] SIGTERM → checkpoint, with a drain path. `daemon_threads=True` currently kills in-flight work.
- [ ] nginx config: `proxy_buffering off`, gzip off, HTTP/2, long read timeout on the SSE route, **no sticky sessions**.

---

## Stage 2 — split the process

*Exit: API and worker deploy independently.*

- [ ] Postgres migration: dual-write with a reconciliation job → flip reads → backfill from every `events.jsonl` and populate `legacy_task_ids` → move workdirs to object storage → `NOT NULL` + `FORCE RLS`, drop the jsonl write path.
- [ ] Schema per PRD §6, with **`org_id` denormalised onto every child table** and a composite index leading with `org_id` — the missing composite index is the documented #1 RLS performance killer (two orders of magnitude).
- [ ] Keep `(task_id, seq)` as the events PK: `events.jsonl` line N *is* `seq = N`, so the durable log and the wire protocol share one cursor.
- [ ] RLS as backstop, application filtering as the primary path. Non-owner, non-`BYPASSRLS` role; `ALTER TABLE … FORCE ROW LEVEL SECURITY`; **`SET LOCAL app.org_id` inside a transaction — plain `SET` leaks the previous request's tenant through the connection pool.**
- [ ] `storage_key` is opaque. A filesystem path must never be the authorization boundary.
- [ ] Starlette + uvicorn async edge. **Agent loop untouched** — do not async-ify it, and do not leave it in-process behind `run_in_threadpool` (Starlette's default AnyIO limiter is 40 threads, shared with every other sync path; 40 concurrent tasks deadlock unrelated endpoints).
- [ ] Extract the worker with a `SELECT … FOR UPDATE SKIP LOCKED` claim loop.
- [ ] Convert `stop` and `messages` from live-`Agent` mutation to **control rows polled at the existing gate** (`loop.py:165`). ~15 lines, and it removes the only real coupling blocking horizontal scale.
- [ ] Fan-out via Postgres `LISTEN/NOTIFY` (notify `task_id`, reader `SELECT`s — payloads cap at 8000 bytes).
- [ ] Artifacts to object storage; `/files/{p}` becomes a 302 to a short-TTL presigned URL on the separate domain.

---

## Stage 3 — scale out

- [ ] N API pods, no sticky sessions — **verify by killing a pod mid-stream.**
- [ ] M workers with lease + heartbeat recovery.
- [ ] `LISTEN/NOTIFY` → Redis Streams (per-task, `MAXLEN ~10000`, Postgres backstop) when pod count or replay load justifies it.
- [ ] Deliberately recycle SSE connections every 10–15 min so the reconnect path is exercised constantly rather than only during incidents.
- [ ] Separate `terminationGracePeriodSeconds`: seconds for API, ~300 s for workers (worst-case drain is the 300 s `urlopen` timeout). Note k8s grace periods **over 10 minutes are buggy** (kubernetes#94435).

---

## Stage 4 — durability

- [ ] Managed sandbox behind the pluggable backend — at this point surviving a deploy is free, because the task isn't in the deploy.
- [ ] Revisit Temporal **only** for multi-hour runs or approval gates. `loop.py` is essentially all non-determinism, so adopting it now means a rewrite plus a cluster plus versioning discipline forever.

---

## Product surface (parallel track, gated by Stage 0)

- [ ] Pricing on **sandbox-hours, concurrency and retention — never tokens**. Free: ~2 sandbox-hours, 1 concurrent task, 24 h retention, 1 share link. Paid ~$10/mo: ~40 hours, 3 concurrent, 30 d retention, unlimited shares. (Numbers pending S1/S3.)
- [ ] Free tier is **a rate, not a balance** — non-renewing sandbox-hours.
- [ ] Share links: `secrets.token_urlsafe(32)`, store only `sha256`, DB row (not a stateless signed URL) so revocation is instant.
- [ ] `frozen_at_seq` set at creation — otherwise `POST /resume` silently publishes new content to an already-shared link.
- [ ] Build the shared replay from a **projection**: strip env vars, system prompt, internal files; `include_files` opt-in per file.
- [ ] Run a secret scanner at share-creation time.
- [ ] `Referrer-Policy: no-referrer` + `rel="noopener noreferrer"` + `X-Robots-Tag: noindex` — a leaked `Referer` is the #1 real-world share-link failure.
- [ ] Surface sandbox lifecycle state in the existing status badges (`running / idle / paused / archived`).

### Deferred to v2 (do not build now)

Pooled inference, credit ledger and billing · teams/orgs UI · SSO/SAML · mobile apps · on-prem/VPC · data residency · marketplace · agent-to-agent · scheduled tasks · live-streaming a shared session.

When pooled inference does arrive, the differentiator is *legibility*, and it's nearly free for us: a pre-run estimate, a hard per-task cap, and a mid-run kill with partial billing, surfaced as a live burn-down in the computer panel we already built. Stop already works. Enforce budgets by **atomic Redis reservation at the gateway** — per-call checks in application code never catch an agent making 500 sequential calls.
