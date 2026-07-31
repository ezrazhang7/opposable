# Legal — what exists, and what is still on you

Stage 0g of [../TODO-hosted.md](../TODO-hosted.md). These are **drafts**. Nothing here has been reviewed by a lawyer, and none of it should be published as-is.

| Document | Status |
|---|---|
| [TERMS.md](TERMS.md) | draft — jurisdiction and dispute clauses unfilled |
| [ACCEPTABLE_USE.md](ACCEPTABLE_USE.md) | draft — provider prohibited-use list flowed down |
| [PRIVACY.md](PRIVACY.md) | draft — includes the retention schedule, which *is* implemented |

## What is wired into the code

- **Affirmative acceptance.** Registration in hosted mode fails without `accept_terms`, and records `terms_version` plus a timestamp against the user. Posting terms alone is unenforceable; a recorded click is the point.
- **`OPPOSABLE_TERMS_VERSION`** must be set or hosted mode refuses to start. It has to match the version string at the top of `TERMS.md`.
- **Retention is enforced, not just described.** `audit.AuditLog.prune()` drops records past the window, and the sandbox lifecycle (`running → idle → paused → archived → deleted`) implements the task-data rows.
- **Secrets are scrubbed on write** into every log path.
- **Suspension** revokes every session immediately, so a suspended account cannot keep working on a stolen cookie.

## What still needs you (money, signatures, or an account)

- [ ] **Counsel review** of all three documents, and the jurisdiction/venue decision they depend on.
- [ ] **Operating entity** named as controller in `PRIVACY.md`.
- [ ] **DMCA designated agent** registered with the US Copyright Office — **$6, renew every 3 years**. Without it there is no §512 safe harbour, so this is the cheapest legal protection you will ever buy and it does not exist until someone files it.
- [ ] **`abuse@` and `privacy@` mailboxes**, monitored, with a documented triage path.
- [ ] **Subprocessor list** published at `/legal/subprocessors` once vendors are chosen (S1 decides the sandbox one).
- [ ] **Tech E&O / cyber insurance** quoted and bound before there is revenue worth suing for. §230 covers speech and §512 covers copyright; neither covers "your box DDoSed us".
- [ ] **Backup retention** configured to match the schedule in `PRIVACY.md` — a mismatch here is exactly what regulators look for.
- [ ] **DSAR workflow** staffed: one calendar month to respond, extendable by two if you say why within the first month.
