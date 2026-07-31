# Plan — Stage 0 ship-blockers

**Implements** [TODO-hosted.md](TODO-hosted.md) groups 0a–0g, per [HOSTED_PRD.md](HOSTED_PRD.md) §10.
**Date:** 2026-07-31

**Exit criterion (PRD §10):** a hostile user with a valid account can obtain nothing from the host, reach nothing on our network, and see nothing belonging to another user.

## Framing decisions made before writing code

1. **Stage 0 lands in the current architecture.** The stdlib `ThreadingHTTPServer` stays; Postgres/Starlette are Stage 2. So identity, quotas and the audit log are backed by **stdlib `sqlite3`**, behind a `Store` seam whose schema is PRD §6 verbatim. Stage 2 swaps the driver, not the callers. The zero-dependency law survives Stage 0 intact.
2. **`OPPOSABLE_HOSTED=1` is the switch.** Every hardening either applies always (it is strictly better) or is *enforced* in hosted mode and *available* locally. The local single-user path keeps working with no account and no cookie, per AGENTS.md §0.
3. **Hosted mode fails closed at start-up.** A `preflight()` refuses to boot if any ship-blocker is unconfigured (dev sandbox backend, local secret store, missing files origin, no egress proxy). Misconfiguration must not be silently survivable.
4. **`web_fetch` runs in the server process, not the sandbox.** The PRD's egress section is written about the sandbox's network; the tool as written reaches `169.254.169.254` *from the API host*, which is worse. SSRF guarding lands on the shared fetch path used by both.

## Steps

| # | Step | Acceptance |
|---|---|---|
| 1 | **0a** `sandbox.py`: explicit env allowlist for both backends. | A task's shell cannot see `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`; only `PATH`, `HOME`, `LANG`, `TERM`, `OPPOSABLE_SANDBOX` (+ proxy vars from step 5) cross. Test asserts it against a real `LocalSandbox`. |
| 2 | **0a** `server.py`: allowlist `base_url`, `model`, `image`; drop pass-through. | A create call with a foreign `base_url` is rejected 400; allowlists come from env, empty by default in hosted mode. Test asserts our key never leaves for an unlisted host. |
| 3 | **0b** `Sandbox` gains `pause()`/`resume()`/`snapshot()`/`archive()`/`restore()`; manifest recorded per task. | Interface + `LocalSandbox`/`DockerSandbox` implementations; archive excludes `node_modules`, `.venv`, caches; round-trip test. |
| 4 | **0b** `LocalSandbox._resolve` confinement; `DockerSandbox` hardening flags; `write_file` via stdin. | Absolute path outside root is refused; `docker run` carries the §4 limits; a 2 MB file writes without hitting `ARG_MAX`. |
| 5 | **0b** `egress.py`: SSRF guard + allowlist proxy config; `web_fetch` routed through it; sandbox gets proxy env, dev-only direct. | Link-local (v4 + IPv4-mapped v6), RFC1918, loopback and metadata IPs refused; DNS re-resolved after every redirect; SMTP ports blocked; default-deny allowlist. Tests for each. |
| 6 | **0c** `store.py` (sqlite3, PRD §6 schema) + `auth.py` (opaque sessions, scrypt, `sha256` at rest). | Register → login → `__Host-` cookie → `/api/auth/me`; logout revokes; expired/revoked sessions rejected. |
| 7 | **0c** server integration: cookie auth, `Sec-Fetch-Site` CSRF, `org_id` on tasks, scoped fetch returning **404 not 403**, full `uuid4()` ids + `legacy_task_ids`. | Cross-tenant GET/POST on every task route returns 404. Old 8-hex ids still resolve. Mutating request without `Sec-Fetch-Site: same-origin` is 403. |
| 8 | **0c** SSE: re-validate the session row every ~60 s on the heartbeat; `event: auth_expired` then close. | Revoking a session mid-stream terminates the stream within one heartbeat cycle with the typed event. |
| 9 | **0d** files on a separate origin, `.opposable/` filtered server-side, CSP on the SPA and on file responses. | Hosted mode refuses `/files/*` on the app origin; internal paths are absent from `_list_files` output, not flagged; `nosniff` + `Content-Disposition: attachment` outside the preview allowlist. |
| 10 | **0e** `secrets_store.py` (BYOK), logger scrubbing, gateway isolation test, pooled-trial cap. | Hosted mode refuses the local file store; a key never appears in any log line or in a sandbox env; trial ledger caps at N tasks / $X. |
| 11 | **0f** `quotas.py` + `audit.py`: concurrency cap, wall-clock kill, egress volume cap, auto-suspend, 30 d audit log. | Second concurrent task on a 1-slot plan is 429; a task past its wall clock is force-stopped; every command/URL/file write lands in the audit log. |
| 12 | **0g** `docs/legal/`: ToS, AUP, privacy policy + retention schedule, abuse process. | Drafts exist, retention numbers match PRD §11, registration requires an affirmative click recorded with timestamp + version. |

Each step: `pytest tests/ -q` green, then one commit. Steps 7–9 also run `npm --prefix web run build` and the e2e happy path, since they touch the wire the SPA reads.

## Decisions taken during the build

Recorded because each departs from the plan above in a way a reviewer would otherwise have to reverse-engineer.

1. **Two Docker profiles, not one flag set.** The PRD's hardening list (`--read-only`, `--user 1000:1000`) makes `apt-get install` impossible, and package installation is the README's headline Docker example. `hardened` is the default; `permissive` keeps the resource ceilings, `no-new-privileges` and the network isolation while giving root and a writable filesystem back. Hosted mode uses neither.
2. **Egress policy has two tiers, split on tenancy rather than on a single flag.** Link-local, multicast and the metadata service in all four of its disguises are refused on every deployment. Loopback, RFC1918 and non-standard ports are refused only once there is a second tenant — blocking them on a laptop is theatre, because the agent has a shell on that host and can reach anything `web_fetch` would refuse. This is also what keeps the e2e fixture (a page server on `127.0.0.1:8902`) working.
3. **`legacy_task_ids` was not built.** Tasks live in `.opposable-<id>` directories, so the directory name *is* the mapping and an 8-hex URL resolves without a table. Task ids are now validated as hex, which also closed an unlisted traversal: `.opposable-../../etc` walked out of the base directory.
4. **The theme bootstrap moved out of `index.html`.** It was an inline script, which a CSP without `unsafe-inline` blocks. Weakening `script-src` app-wide to save one request for a twelve-line file was the wrong trade.
5. **Trial spend is charged after the run, not reserved before it.** Acceptable at three tasks and ~$1. It is explicitly *not* the model for pooled inference in v2, where the reservation has to be atomic and at the gateway — a per-call check never catches an agent making 500 sequential calls.

## Known blocked-on-you (work around, don't stall)

These need an account, a purchase, or a signature. Everything on our side is built up to the seam and hosted mode refuses to boot without them, so nothing ships half-secured.

- **microVM vendor (S1)** — `MicroVMSandbox` needs a Fly/E2B account. The interface, manifest, archive/restore and the hosted-mode refusal of `LocalSandbox`/`DockerSandbox` all land now.
- **Supabase project** — schema and queries land on stdlib sqlite3 behind the same `Store` API; provisioning and the Postgres driver swap are Stage 2.
- **Separate registrable domain for files** — code reads `OPPOSABLE_FILES_ORIGIN` and hosted mode refuses to start without it; buying the domain is yours.
- **Cloud secret manager, separate cloud account, allowlist-proxy host** — seams and config land; the accounts are yours.
- **Turnstile keys, email-verification provider** — the signup ladder's gates are implemented as pluggable checks; keys are yours.
- **DMCA agent registration ($6), insurance quotes, counsel review of the ToS/AUP drafts.**
