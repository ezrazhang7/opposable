# opposable — Privacy Policy and Retention Schedule

**Version:** 2026-07-31 · **Status: draft, not reviewed by counsel.**

Controller: *[operating entity, address — to be completed.]* Contact: `privacy@` *(to be published at launch)*.

## 1. What we collect

| Category | Examples | Why |
|---|---|---|
| Account | email, password hash, org, plan, terms version and acceptance time | to run your account and prove acceptance |
| Task content | your prompt, the agent's transcript, files it produced, its plan | to run and replay the task, and to let you share it |
| Operational | command, URL and file audit records; task timings; egress volume | security, abuse response, and quota enforcement |
| Billing | plan, invoices, payment-processor reference | to charge you and meet tax obligations |
| Technical | IP address and user agent at sign-in, error traces | security and debugging |

**We do not store your model-provider API key in our primary database.** It goes into a secret manager and we hold only a reference. It is never exposed to the agent's sandbox.

## 2. What we do not do

We do not sell personal data. We do not use your task content to train models. We do not read your tasks except where you ask us to for support, where an abuse signal requires investigation, or where the law compels us — and each such access is itself logged.

## 3. Processors

Model inference (your chosen provider, under your key), sandbox infrastructure, object storage, database and authentication, payment processing, and transactional email. The current list with locations is published at `/legal/subprocessors` and we give 30 days' notice before adding one.

## 4. Retention schedule

Retention that is documented but not enforced is worse than no policy, so each row below is implemented in code, and **our backup retention matches it** — deleted data does not survive indefinitely in a backup.

| Data | Retained | Then |
|---|---|---|
| Task workdir and artifacts | 24 h (free) / 30 d (paid) active, then archived 7 d | deleted |
| Task transcript (events) | 30 d by default | deleted |
| Command / URL / file audit records | 30 d minimum, up to 90 d | deleted |
| Spend and usage records | 30–90 d | aggregated, then deleted |
| Security events (sign-ins, suspensions, abuse) | 12 months | deleted |
| Billing and invoices | 7 years | statutory retention |
| Account record | life of account + 30 d | deleted |
| Share links | until revoked or expired | deleted with the task |

Secrets are scrubbed **on write**, not on read. A credential that reached a log file is already leaked.

## 5. Your rights

Access, rectification, erasure, restriction, portability, and objection. Email `privacy@`; we respond within **one calendar month**, extendable by two further months for complex requests, in which case we will tell you why within the first month.

Deleting your account starts deletion on the schedule above. Some records — billing, security events, and anything under legal hold — are retained for their stated period.

## 6. Legal bases (UK/EU)

Contract, for running your account and your tasks. Legitimate interests, for security, abuse prevention and service improvement, balanced against your rights. Legal obligation, for tax and law-enforcement requests. Consent, for optional marketing email only, withdrawable at any time.

## 7. Transfers

Where data leaves your region we rely on the UK/EU Standard Contractual Clauses or an adequacy decision. Regions are listed with each subprocessor.

## 8. Security

Encryption in transit and at rest; per-task isolation; scoped access with tenant checks on every request; secrets in a dedicated manager; audit logging of privileged access. No system is perfect: if a breach affects your data we will notify you and the relevant regulator within the statutory window.

## 9. Children

The Service is not for anyone under 18 and we do not knowingly collect their data.

## 10. Changes

Material changes are notified by email 30 days before taking effect. Every version is archived with its version string.

---

*Open questions for counsel: controller entity and any EU/UK representative; whether a DPA and SCC package is needed for business customers; whether the transcript default of 30 days should be user-configurable; breach-notification thresholds per jurisdiction.*
