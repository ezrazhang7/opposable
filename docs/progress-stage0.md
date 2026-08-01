# Stage 0 — progress report

**Date:** 2026-07-31 · Covers the implementation of [plan-stage0.md](plan-stage0.md), groups 0a–0g of [TODO-hosted.md](TODO-hosted.md).

Stage 0 is built out. **105 tests pass** (was 21), the frontend builds clean, and the browser e2e is 16/16 twice consecutively.

## What landed, in 11 commits

**0a — credential leaks.** `LocalSandbox` ran model-generated commands with `env={**os.environ}`, so `echo $ANTHROPIC_API_KEY` was a working exfiltration primitive; the env is now an allowlist. `base_url`, `model` and `image` are allowlisted rather than passed through — a client-chosen `base_url` was receiving our `Authorization` header.

**0b — the sandbox.** `_resolve` confinement (absolute paths, traversal, symlinks), the Docker hardening set, `write_file` via stdin instead of `shlex.quote` at `ARG_MAX`, `pause`/`resume`/`snapshot` plus portable `archive`/`restore`, and a default-deny egress guard. That last one closed something not in the PRD's findings table: **`web_fetch` runs in the server process**, so it reached `169.254.169.254` from the API host — worse than a sandbox doing it.

**0c — identity.** Opaque DB-backed sessions, `__Host-` cookie, `Sec-Fetch-Site` CSRF, tenant-scoped fetches returning 404 (never 403), full `uuid4()` ids, and SSE that re-reads the session row on the heartbeat. Hex-validating task ids also closed an unlisted traversal: `.opposable-../../etc` walked out of the base directory.

**0d–0g.** Files on a separate signed origin with `.opposable/` filtered server-side; BYOK behind a secret-store seam with scrubbing on write; per-org quotas, a wall-clock watchdog, egress-triggered suspension and a 30-day audit log; ToS/AUP/privacy drafts whose retention schedule matches what the code enforces.

Hosted mode **fails closed** — `opposable serve` with `OPPOSABLE_HOSTED=1` lists all ten missing pieces and exits 2.

## Three things you should know

**A real bug was already on your disk.** A confinement test failed on `C:\sandbox\report.md` — a file the old `_resolve` bug wrote outside the sandbox during an earlier agent run. I didn't delete it; the test now uses a unique path. You may want to check what else is at your drive root.

**Two deliberate departures from the PRD**, both recorded in [plan-stage0.md](plan-stage0.md):

- The PRD's Docker flag set (`--read-only`, `--user 1000:1000`) makes `apt-get install` impossible, and that's the README's headline Docker example. I shipped two profiles — `hardened` default, `permissive` for package installs. Hosted uses neither.
- Egress has two tiers. Link-local and the metadata service (in all four disguises — `::ffff:`, 6to4, NAT64) are refused everywhere; loopback and RFC1918 only once there's a second tenant. Blocking those on a laptop is theatre — the agent has a shell on that host.

**What's blocked on you, not on work.** `MicroVMSandbox` (needs S1: prototype Fly Sprites' resume path and confirm the rates — the PRD flags them as blog-attested for a 7-month-old product); the Supabase project (schema and queries are done on stdlib sqlite3 behind a `Store` seam — note sqlite has **no RLS**, so application filtering is currently the only layer); a registrable domain for files; cloud accounts for the secret manager, egress proxy and sandbox isolation; Turnstile and mail keys; and counsel review plus the $6 DMCA registration.

One unrelated edit sits uncommitted: something added `AGENTS.md` to `web/.gitignore`. Not mine, so I left it.
