# opposable — Terms of Service

**Version:** 2026-07-31 · **Status: draft, not reviewed by counsel.** Do not publish without a lawyer reading it. The `OPPOSABLE_TERMS_VERSION` environment variable must match the version string above; registration records which version each user accepted, and acceptance is by affirmative click, not by posting.

## 1. What the service is

opposable Hosted ("the Service") runs an autonomous software agent on our infrastructure on your instruction. The agent executes commands, reads and writes files, and fetches web pages inside a sandbox we operate on your behalf.

**You direct the agent; we run the machine.** You are responsible for the instructions you give it, for the content it produces at your direction, and for ensuring both are lawful and permitted by any third party whose systems or data are involved.

## 2. Accounts

You must be 18 or older, provide a working email address, and keep your credentials secure. One person, one account, unless we agree otherwise in writing. You are responsible for everything done through your account.

We may suspend or terminate an account **immediately and without notice** where we reasonably believe it is being used in breach of the Acceptable Use Policy, where it threatens the security or availability of the Service or a third party, or where we are required to by law. See [ACCEPTABLE_USE.md](ACCEPTABLE_USE.md), which forms part of these Terms.

## 3. Model access and your API key

The Service is **bring-your-own-key**: you supply a key for a third-party model provider, and inference is billed by that provider directly to you. We store your key in a secret manager and use it solely to make model calls for your tasks. We never expose it to the agent's sandbox.

A limited **free trial** may run on our own provider account. It is capped, non-renewing, and provided as a courtesy; we may withdraw or change it at any time.

**Your provider's policies flow down.** When you use a provider key through the Service you remain bound by that provider's usage policies, and this Agreement's Acceptable Use Policy is at least as strict. Nothing here grants you rights a provider's terms deny you.

## 4. Fees

Paid plans are billed in advance on the interval shown at purchase, priced on sandbox capacity — sandbox-hours, concurrent tasks, and retention — not on model tokens. Fees are non-refundable except where required by law. We may change prices with 30 days' notice; changes take effect at your next renewal.

## 5. Your content

You keep ownership of everything you submit and everything the agent produces for you. You grant us a licence to host, process, transmit and display it **only** as needed to operate the Service, support you, and comply with law.

**Share links.** If you create one, you are publishing a frozen copy of that task to anyone holding the link. Check it before you share it. We scan for obvious secrets at share time as a courtesy, not as a guarantee.

## 6. Retention and deletion

Task data follows the published lifecycle: active, then archived, then deleted, on the schedule in [PRIVACY.md](PRIVACY.md). Deleting your account starts deletion of your content on that schedule, save where we must retain records by law. **Our backup retention matches our stated retention** — deleted data does not survive indefinitely in a backup.

## 7. Availability, and what we do not promise

The Service is provided **"as is"**. We do not warrant that it will be uninterrupted, that a task will complete, or that the agent's output will be correct, safe, or fit for any purpose.

**Agents make mistakes, and this one runs commands.** Do not point it at production systems, irreplaceable data, or anything where an incorrect action is costly. Verify its output before relying on it.

## 8. Liability

To the maximum extent permitted by law, our aggregate liability arising out of or relating to the Service is limited to the greater of (a) the fees you paid us in the twelve months before the claim, or (b) USD 100. We are not liable for indirect, incidental, special, consequential or exemplary damages, or for lost profits, revenue, or data.

Nothing in this section limits liability that cannot be limited by law.

## 9. Indemnity

You will indemnify and hold us harmless against claims, damages and costs arising from your use of the Service in breach of these Terms or the Acceptable Use Policy, or from content you submit or direct the agent to produce.

## 10. Changes

We may amend these Terms. Material changes take effect 30 days after notice to your registered email, or on your next acceptance, whichever is earlier. Continued use after that constitutes acceptance. Every version is archived with its version string.

## 11. Termination

You may close your account at any time. On termination your right to use the Service ends immediately, and sections 5 (as to licences already granted), 8, 9 and 12 survive.

## 12. General

**Governing law and venue:** *[to be completed — depends on the operating entity's jurisdiction; counsel to advise.]*

**Notices** to you go to your registered email; notices to us go to the address published at `/legal`.

If any provision is unenforceable, the rest stands. Our failure to enforce a provision is not a waiver of it. You may not assign this Agreement; we may assign it to a successor in a merger or sale of assets.

---

*Open questions for counsel: operating entity and jurisdiction; whether an arbitration clause and class-action waiver are appropriate; consumer-law carve-outs for UK/EU users; whether the liability cap survives in each target market.*
