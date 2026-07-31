# opposable Hosted — PRD for the multi-user product

**Status:** proposal · **Date:** 2026-07-31 · **Supersedes nothing** — [FRONTEND_PRD.md](FRONTEND_PRD.md) ships the UI this builds on.

**Goal:** turn the single-user local agent into a hosted product where strangers sign up and run agents on our infrastructure.

**The honest framing.** The agent loop, the UI, and the replay story are done. What hosting adds is the layer nobody open-sources: identity, per-account quotas, a credit meter, sandbox scheduling and recycling, egress policy, and abuse response. Every open-source Manus clone stops exactly where this document starts — OpenHands documents upstream as *"not appropriate for multi-tenant deployments — no built-in authentication, isolation, or scalability"* and sells the multi-tenant server separately. That layer is the moat and it is roughly 80% of the remaining work.

---

## 1. Non-goals for v1

- Teams/orgs beyond a stub `orgs` table (schema supports it; no UI).
- SSO/SAML. The auth choice keeps it a config change, not a migration.
- Mobile apps, on-prem/VPC delivery, data residency.
- Marketplace, agent-to-agent, scheduled tasks.
- Live-streaming a shared session. Share links are **frozen replays** (§7).

---

## 2. Where we actually are

Verified against the code, not assumed. Each of these is disqualifying for public hosting on its own.

| # | Finding | Location |
|---|---|---|
| 1 | `LocalSandbox` — the **default** — runs model-generated `bash -lc` on the host with `env={**os.environ}`. A task can `echo $ANTHROPIC_API_KEY`. | `sandbox.py:73-82`, `server.py:135-138` |
| 2 | `DockerSandbox` runs with **no** `--memory`, `--cpus`, `--pids-limit`, `--network`, `--cap-drop`, `--user`, `--read-only`, `--security-opt`. Fork bomb takes the host; `169.254.169.254` is reachable. | `sandbox.py:106-115` |
| 3 | `POST /api/tasks` accepts a client-supplied **`base_url`**, and `OpenAICompatProvider` sends `Authorization: Bearer <our key>` to it. Any user exfiltrates the platform key by pointing it at their own server. | `server.py` create params, `providers.py:144-150` |
| 4 | Task IDs are `uuid4().hex[:8]` — 32 bits. Enumerable, and **~50% chance of a collision at ~65k tasks**, which silently corrupts one task with another. | `server.py:149` |
| 5 | `Last-Event-ID` is never read; every SSE reconnect replays the **entire** history. After a deploy, N clients × full history hits at once. | `server.py:385-394` |
| 6 | Task files are served **on the app origin** with a guessed MIME type and no `Content-Disposition`. An agent that writes `report.html` gets stored XSS against every viewer. | `server.py:449-461` |
| 7 | `.opposable/` internal files are returned to the client with an `internal: true` flag and hidden **client-side only**. | `server.py:430-447` |
| 8 | One OS thread per SSE connection; `daemon_threads=True` kills in-flight work with no drain path. `_emit` reopens the events file per event while holding the lock. Subscriber queues and the task cache are unbounded. | `server.py:103-111, 488-498` |

Two properties are worth *preserving* deliberately: the server binds `127.0.0.1` and there are **no CORS headers anywhere** — the SPA and API are same-origin by construction, which is what makes §5's auth design cheap. And the SSE wire already emits `id: {seq}` with a per-task monotonic `seq`, so the resumption cursor exists; it just isn't honoured.

---

## 3. Target architecture

```
Browser (EventSource; cookie auth; resumes with Last-Event-ID)
   │  HTTP/2 + TLS
   ▼
L7 proxy — no sticky sessions; SSE route: buffering off, gzip off, long read timeout
   │
   ├──────────────┬──────────────┐        stateless, N replicas
   ▼              ▼              ▼
API pods (async: Starlette + uvicorn)
   │  POST /tasks    → insert row + enqueue
   │  GET  /events   → replay WHERE seq > cursor, then tail the bus
   │  POST /stop     → write control row + publish   (no in-process Agent)
   │  GET  /files/*  → 302 to a short-TTL presigned URL on a separate domain
   │
   ├── Postgres (users, tasks, events, files, shares, credits) ── durable
   ├── Redis (bus, quotas, budget reservations) ─────────────── ephemeral
   └── Object storage (artifacts, sealed logs)
   ▲
   │  claim → run → emit
Worker pods (SYNCHRONOUS — the agent loop is not rewritten)
   │  polls control rows each iteration → stop / inbox
   │  SIGTERM → stop_requested → checkpoint → exit → another worker resumes
   ▼
Per-task sandbox — managed microVM, scrubbed env, default-deny egress
```

**The pivotal decision: do not async-ify the agent loop.** It is intrinsically blocking (`subprocess.run`, `urlopen(timeout=300)`); rewriting it to async only pushes it back into an executor. Split an async I/O edge from synchronous worker processes, with a durable event log as the only contract between them.

Corollary trap: if the agent stays in-process behind `run_in_threadpool`, it consumes Starlette's **default AnyIO limiter of 40 threads**, shared with every other sync path — 40 concurrent tasks and unrelated endpoints deadlock. Separate processes, not a bigger limiter.

**What unlocks horizontal scale** is not the framework. It is that `stop` and `messages` currently mutate a live `Agent` object in the same process. Converting both to database rows polled at the existing `loop.py:165` gate is ~15 lines and removes the only real coupling.

---

## 4. Isolation — buy it

**Decision: a pluggable sandbox backend with `pause`/`resume`/`snapshot`, pointed at a managed Firecracker sandbox. Never `LocalSandbox`, and never bare `docker run`.**

SWE-agent extracted exactly this abstraction (SWE-ReX) after hard-coding Docker made parallelism brittle; it now targets Local, Docker, Modal, Fargate and Daytona behind one interface. Our `Sandbox` class is already close. **Build the interface before picking the vendor** — it is what makes the vendor choice reversible, which matters because the most attractive option is also the least verified.

| Option | Isolation | ~$/hr (2vCPU/4GiB) | Idle billing | Resume | Persistence |
|---|---|---|---|---|---|
| **Fly Sprites** ⚠️ | Firecracker | ~$0.32 | **none — idle free**, ~$0.02/GB-mo | ~300 ms | 100 GB NVMe survives hibernate |
| **E2B Pro** | Firecracker | $0.166 + $150/mo | full wall-clock | ~1 s | pause keeps FS **+ memory**, indefinite |
| **Modal** | gVisor | ~$0.24 | yes | sub-second | FS + memory snapshots; **24 h cap** |
| **Fargate** | Firecracker | **$0.079** ARM | n/a | seconds | **none — build S3 archive yourself** |
| **Cloudflare Containers** | per-instance VM | ~$0.18 CPU-pegged | **active CPU only** | 1–3 s | **fresh disk on wake — disqualifying** |

⚠️ **Fly Sprites pricing is attested only by third-party blogs, one of them a competitor's, for a product ~7 months old. Prototype the resume path and confirm rates with Fly before designing around it.** E2B is the more proven fallback but bills wall-clock — and an agent spends most of its wall-clock *waiting on the LLM*, so a sandbox that is 10% CPU-busy pays full freight. E2B also has an [open bug where files stop persisting after repeated resumes](https://github.com/e2b-dev/E2B/issues/884); treat memory snapshots as an optimisation and archive the filesystem independently.

**Because idle dominates, optimise the idle model before the hourly rate.** Design the loop to checkpoint and pause *between steps* rather than hold a live sandbox — cheaper, and it sidesteps every vendor session cap.

**Lifecycle** (portable across every backend, exposed in the API so the existing status badges can show it):

```
running → idle (5–15 min) → paused → archived (7 d) → deleted (30 d)
```

Store an immutable per-task manifest (base image digest, env, workdir archive pointer). Resume = restore the archive into a fresh sandbox from the same digest; use native checkpoint/restore as a fast path for recent tasks. Exclude `node_modules`, `.venv` and build caches from archives — usually 10–100× the archive size and fully reconstructible.

**Resource limits** (values, not vibes): 2 vCPU · 4 GiB with **swap disabled** · **`--pids-limit=512`** · 10 GiB disk quota · 50 MB/s device I/O · 120 s default command timeout (600 s opt-in) · 30 min active wall clock then force-pause · 5–10 Mbit/s sustained egress.

---

## 5. Auth

**Decision: Supabase Auth. Opaque, DB-backed sessions in a `__Host-` cookie. Same-origin.**

We are migrating to Postgres regardless; Supabase bundles Postgres + Auth + RLS + object storage at $25/mo covering 100k MAU, and RLS policies key off `auth.uid()` natively — which matters in a stdlib codebase with hand-rolled SQL and **no ORM to centralise a tenant filter**. Python-side cost is JWKS verification with PyJWT.

Runner-up: **WorkOS AuthKit**, free to 1M MAU with a cookie-first sealed-session model. Pick it if we'd rather not couple auth to the database vendor. Auth0 is the most expensive at every tier with a ~4× jump for orgs. Keycloak's $0 is fictional for a solo operator — an internet-facing IdP you patch forever.

| | 100 MAU | 1k | 10k | +SSO later |
|---|---|---|---|---|
| Supabase | $0 / $25 Pro | $25 | $25 | $0.015/SSO-MAU |
| WorkOS | $0 | $0 | $0 | $125/mo per connection |
| Clerk | $0 / $25 | $25 | $25 | 1 included, +$75/mo each |
| Auth0 ⚠️ | $0 / $35 | ~$70–240 | ~$228 | paid tier + B2B SKU |

⚠️ Auth0 figures are aggregator-sourced; verify. Clerk bills *retained* users (MRU), not MAU, so an MAU model overestimates it.

### The SSE authentication decision

`EventSource` cannot set headers, and an agent run outlives any access token. Both facts are unavoidable, so:

> **Same-origin `__Host-` cookie (`HttpOnly; Secure; SameSite=Lax`) + native `EventSource`. Authorize at connect. Re-validate the *session row* — not the JWT — on the heartbeat we already send every 10 s.**

- **No token in the query string.** It lands in access logs, browser history, `Referer`, and the error tracker. If we are ever forced cross-origin, use a single-use 30-second audience-scoped *ticket*, never the session token.
- **No fetch+ReadableStream for v1.** It buys `Authorization` headers and costs automatic reconnect, `Last-Event-ID` handling, and wire parsing. The canonical library `@microsoft/fetch-event-source` is **v2.0.1, last published ~2021**.
- **Bind to the session, not the token.** Every 6th ping (~60 s), re-read the session row; on revoke/expire emit a typed `event: auth_expired` and close. The client must call `close()` **before** refreshing or the browser reconnects straight into a login redirect loop.
- **Today's actual bug:** auth is checked once at connect, so a user who logs out or is removed keeps receiving live output indefinitely. With hour-long runs that is a real window. This layer is what closes it — and it is cheap because `useSession.ts` already dedupes by `seq`.
- **`SameSite=Lax`, not `Strict`** — `Strict` breaks the OAuth callback. Layer `Sec-Fetch-Site: same-origin` checks on mutating requests as the primary CSRF defence, with an `Origin` check as fallback.

---

## 6. Data model

```sql
orgs(id uuid pk, slug citext unique, name, created_at)
users(id uuid pk, email citext unique, created_at)
memberships(org_id, user_id, role check(owner|admin|member|viewer), pk(org_id,user_id))

sessions(id uuid pk, user_id, token_hash bytea unique, expires_at, revoked_at)
  -- store sha256(secret); the secret itself is never persisted

tasks(id uuid pk, org_id, created_by, status, prompt, storage_prefix, created_at, updated_at)
events(task_id, seq bigint, org_id, kind, payload jsonb, created_at, pk(task_id,seq))
files(id uuid pk, task_id, org_id, rel_path, size_bytes, content_hash,
      storage_key, is_internal, unique(task_id, rel_path))
shares(id uuid pk, task_id, org_id, token_hash bytea unique, expires_at, revoked_at,
       frozen_at_seq bigint, include_files bool, password_hash, view_count)
share_files(share_id, file_id, pk(share_id,file_id))
legacy_task_ids(old_id text pk, task_id uuid)   -- 8-hex ids must not 404
credits(org_id, balance_micros bigint, updated_at)
ledger(id, org_id, task_id, kind, amount_micros, created_at)
```

- **`org_id` is denormalised onto every child table** so each RLS policy is a single-table predicate with `org_id` leading the index. Missing that composite index is the documented #1 RLS performance killer — two orders of magnitude.
- **`(task_id, seq)` stays the events PK**, preserving the cursor the SSE client already relies on. `events.jsonl` line N *is* `seq = N`, so the durable log and the wire protocol share one cursor.
- **RLS as backstop, application filtering as the primary path.** Connect as a non-owner, non-`BYPASSRLS` role; `ALTER TABLE … FORCE ROW LEVEL SECURITY`. Use `SET LOCAL app.org_id` inside a transaction — **plain `SET` leaks the previous request's tenant through the connection pool.**
- **`storage_key` is opaque.** A filesystem path must never be the authorization boundary.

**Migration:** dual-write to Postgres with a reconciliation job → flip reads → backfill from every `events.jsonl` and populate `legacy_task_ids` → move workdirs to object storage (this is the step that unblocks horizontal scaling) → `NOT NULL` + `FORCE RLS`, drop the jsonl write path.

---

## 7. Object authorization, files, and share links

- Every endpoint taking an ID does a **scoped fetch** (`WHERE id = $1 AND org_id = $ctx`), never fetch-then-check. Return **404, never 403**, for cross-tenant — a 403 confirms the ID exists and turns a blind scan into an oracle.
- Widen task IDs to full `uuid4()`/128-bit. Unpredictable IDs are anti-enumeration, *not* authorization (OWASP API1:2023).
- **Serve task files from a separate registrable domain** (not a subdomain — this is why `googleusercontent.com` exists), with `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` outside a small preview allowlist, and `Content-Security-Policy: default-src 'none'; sandbox`. Never `text/html` or `image/svg+xml` inline on the app origin. If the session cookie is `Domain=`-scoped to a parent domain, this is doubly load-bearing.
- Filter `.opposable/` **server-side**. It holds the system prompt and tool traces.
- **Share links:** `secrets.token_urlsafe(32)`, store only `sha256`, DB row (not a stateless signed URL) so revocation is instant. `frozen_at_seq` at creation — otherwise `POST /resume` silently publishes new content to an already-shared link. Build the replay from a **projection**: strip env vars, system prompt, internal files; `include_files` opt-in per file. Run a secret scanner at share-creation time. `Referrer-Policy: no-referrer` + `rel="noopener noreferrer"` + `X-Robots-Tag: noindex` — a leaked `Referer` is the #1 real-world share-link failure.

---

## 8. Egress, abuse, and cost

**Egress is the control that matters most**, because abuse arrives long before anyone attempts a VM escape. Note the pattern in real incidents: nobody broke out of a Firecracker VM. What broke was cross-tenant API authorization (Lovable leaking other users' source, DB credentials and chat histories), auth design (Base44's open redirect + stored XSS, disclosed 2025-07-09), and sharing semantics — Manus's own docs concede Collaboration exposes the sandbox and *"may cause unexpected data leakage."* **Build the authz boundary as if the sandbox is already compromised.**

**Ship-blocking controls:**

1. Default-**deny** egress through an allowlist proxy we control. Not a blocklist — the vm2 escape wave shows blocklists lose to novel primitives.
2. Block link-local **and its IPv4-mapped IPv6 form**, plus all RFC1918 and our own VPC. Re-resolve DNS **after every redirect** or DNS rebinding walks through.
3. IMDSv2 enforced, IMDSv1 off, hop limit 1; sandbox host role has **zero** permissions. (Hop-limit 1 only covers bridge networking — remove link-local routes from the sandbox netns as well.)
4. Sandboxes in a **separate cloud account** with no network path to the control plane.
5. Outbound SMTP (25/465/587) blocked permanently. Every major cloud does this and never lifts it for free tiers.
6. **No secrets in the sandbox, ever.** LLM calls go through our gateway. This is also the only durable prompt-injection defence: the one secret injection cannot steal is one the agent never sees.
7. Remove client-controlled `base_url`, or allowlist it (finding #3).
8. Per-user concurrency caps, wall-clock kill, egress volume caps, and auto-suspend on sustained-100%-CPU or high-egress signatures — mining and exfil each have an obvious shape.
9. `abuse@` monitored, structured audit log of every command/URL/file retained ≥30 days.

**Prompt injection is not solvable at the model layer** — OpenAI's CSO called it unsolved and the NCSC concurs. Design the blast radius instead. Both 2026 CVEs in this space were *denylist and allowlist bypasses* (CVE-2026-2256 obfuscated past a dangerous-command denylist; CVE-2026-22708 poisoned env vars so allowlisted `git branch` carried the payload). Containment, not filtering.

### Cost control: BYOK first

**Decision: BYOK at launch; pooled credits as a paid-only upgrade.**

It transfers the runaway tail to the user, and it is free KYC — a working provider key means someone already passed a card-verified signup at a provider with its own fraud stack.

Per-task cost at ~30 turns with prompt caching on: **~$0.44 Haiku 4.5 · ~$1.32 Sonnet 5 · ~$2.20 Opus 5**. A stuck Opus loop at ~1M context burns **~$24/hour — ~$480 overnight.** That is the scenario, and it needs one well-meaning user, not an attacker. Default to Sonnet 5; make Opus explicit opt-in. *(Model prices: Opus 5 $5/$25, Sonnet 5 $3/$15, Haiku 4.5 $1/$5 per Mtok — verify live before building a pricing page.)*

BYOK keys go in a secret manager with a reference in Postgres — never the primary DB, never logs (scrub at the logger, assert in tests), never the sandbox. **BYOK does not exempt us from the provider's usage policy:** Anthropic's applies to anyone submitting inputs *"including via any authorized resellers or passthrough access."* Our AUP must be at least as strict and actually enforced.

Pooled tier guards: per-task hard cap $2 (Sonnet) / $5 (Opus, paid), per-user daily $10, 2 concurrent free / 5 paid, kill at 60 turns or 25 min, org circuit breaker at 3× the rolling 7-day median hourly. Enforce with **atomic Redis reservation at the gateway** — per-call checks in application code never catch an agent making 500 sequential calls.

**Free tier = a rate, not a balance.** $0.25 one-time, non-renewing. A monthly-refilling free tier is an abuse subscription; Manus's 300-credits/day refresh is the right shape. Signup ladder: Turnstile + email verify + disposable-domain blocklist → tiny credit; card-on-file to go further. Counterintuitively this *helps* revenue — requiring a card cuts signups ~22% but roughly triples paying customers (~4–6% → ~30% per ChartMogul's Jan-2026 cohort of 200 B2B products).

Rate-limit on **money and device fingerprint**, not IP. Residential proxy networks rotate millions of IPs; Cloudflare, GreyNoise and an FBI/IC3 PSA (March 2026) all say the same thing — score behaviour, not origin.

---

## 9. Unit economics

- Tokens dominate: sandbox compute is ~$0.03–0.05/vCPU-hr against $1–3 of tokens per task — roughly **50–100× in favour of tokens.** Optimise token controls first.
- Agentic runs are **1M–3.5M tokens per coding-class task including retries, with up to 30× variance across runs of the same task.** Any flat price is a bet against that variance.
- AI products run **50–60% gross margins vs 80–90% for classic SaaS**, with inference COGS rising as a share of spend.
- Everyone converged on a usage meter (Manus credits, Devin ACUs at ~$2.25/ACU ≈ 15 min, Replit effort units) — and Replit's is the market's loudest source of customer anger precisely because *the platform decides how much effort a request takes and prices it after the fact*; reports cite $180/mo → ~$1,000 in a week.

**The differentiator, and it is nearly free for us:** pair the meter with a **pre-run estimate, a hard per-task cap, and a mid-run kill with partial billing** — surfaced as a live credit burn-down in the computer panel we already built. Stop already works.

---

## 10. Staged plan

Each stage ships independently and leaves the system working.

**Stage 0 — ship-blockers.** Default sandbox to isolated; `LocalSandbox` becomes dev-only and loudly warned. Scrub the sandbox environment. Remove/allowlist client `base_url`. Widen task IDs. Add auth + ownership. Serve user files off a separate domain. Filter `.opposable/` server-side. *No public exposure before all of these.*

**Stage 1 — protocol correctness, still one process.** Honour `Last-Event-ID` (header + query fallback); 204 for a terminal task with no missed events; emit `retry:`; hold the events file open and move fan-out outside the lock; bound subscriber queues and the task cache; nginx with `proxy_buffering off`, gzip off, HTTP/2; SIGTERM → checkpoint. *Exit: a client disconnects mid-task and reconnects with zero duplicates and zero gaps.*

**Stage 2 — split the process.** Postgres (dual-write → flip → backfill). Starlette + uvicorn edge; **agent loop untouched**. Worker extracted with a `SELECT … FOR UPDATE SKIP LOCKED` claim loop. `stop`/`messages` become control rows. Fan-out via Postgres `LISTEN/NOTIFY` (notify `task_id`, reader `SELECT`s — payloads cap at 8000 bytes). Artifacts to object storage; `/files/{p}` becomes a presigned redirect. *Exit: API and worker deploy independently.*

**Stage 3 — scale out.** N API pods, no sticky sessions — verify by killing a pod mid-stream. M workers with lease + heartbeat recovery. `LISTEN/NOTIFY` → Redis Streams (per-task, `MAXLEN ~10000`, Postgres backstop) when pod count or replay load justifies it. Deliberately recycle SSE connections every 10–15 min so the reconnect path is exercised constantly rather than only during incidents. Separate `terminationGracePeriodSeconds`: seconds for API, ~300 s for workers — worst-case drain is the 300 s `urlopen` timeout, and note k8s grace periods **over 10 minutes are buggy** (kubernetes#94435).

**Stage 4 — durability.** Managed sandbox behind the pluggable backend; at this point surviving a deploy is free because the task isn't in the deploy. Revisit Temporal only for multi-hour runs or approval gates — `loop.py` is essentially all non-determinism, so adopting it now means a rewrite plus a cluster plus versioning discipline forever.

---

## 11. Legal minimum

ToS + AUP accepted by affirmative click at registration (posting alone is unenforceable), with an explicit suspension right and the provider's prohibited-use list flowed down. Privacy policy with a retention schedule — **and backup retention must match it**, which is exactly the gap regulators look for. DMCA designated agent ($6, US Copyright Office, expires every 3 years) or there is no §512 safe harbour. Monitored `abuse@`. DSAR workflow (one calendar month, extendable by two if you say why). Tech E&O / cyber insurance before there is revenue worth suing for — §230 covers speech and §512 covers copyright; neither covers "your box DDoSed us."

Retention: commands/URLs/spend 30–90 d · transcripts 30 d default · security events 12 mo · billing 7 y. Scrub secrets on write, not on read.

---

## 12. Open questions

1. **Verify Fly Sprites pricing and the resume path with a prototype** before designing the lifecycle around it — the newest claim here and the one carrying the most weight.
2. BYOK-only at launch, or BYOK + a paid pooled tier from day one? Affects whether the credit ledger is v1 or v2.
3. Supabase vs WorkOS — coupling auth to the database vendor is the real trade, not the price.
4. Do we run our own egress proxy or buy a platform whose egress policy is good enough? Nothing in §8's list comes free with any vendor.
5. What is the free tier *for*? If it exists to convert, the card-on-file data argues for making it tiny and gating the rest.
