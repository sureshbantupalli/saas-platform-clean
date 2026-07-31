# ANJASI — Infrastructure Readiness Status

**Last updated:** 2026-07-30
**Branch:** `fix/mvp-bugs` (pushed to origin)
**Purpose:** Resume point. Read this first when picking the work back up.

To deploy, see **`DEPLOYMENT_RUNBOOK.md`** — server build, gunicorn, nginx,
TLS, cron, smoke tests, rollback and troubleshooting.

To hand deployment to someone else, give them **`SERVER_SOFTWARE_SPEC.md`** —
the full software inventory, what is deliberately not needed, and the seven
things they should be told before starting.

First deployment target is **Setu Yoga Studio** as tenant #1.

---

## 0. How to run anything here

```bash
# ALWAYS use the venv interpreter — the system python has no pytest installed
./venv/Scripts/python.exe -m pytest apps -q          # full suite (~12 min, 1124 tests)
./venv/Scripts/python.exe -m pytest apps/communications -q
./venv/Scripts/python.exe manage.py check
```

**Traps that cost time before — don't repeat them:**

| Trap | What happens | Do instead |
|---|---|---|
| Using `python` instead of `./venv/Scripts/python.exe` | `No module named pytest` | Always use the venv path |
| Running two pytest processes at once | Both deadlock on the shared test DB, ~87 spurious errors that look like a real regression | Run test suites **serially**, never a background run alongside a foreground one |
| Trusting `pytest apps/<app>` counts | See §4 — collection patterns silently skipped files | Fixed now, but sanity-check counts change when you add a test file |

Postgres runs on **port 5433** (not 5432). Credentials come from `.env` (gitignored); `.env.example` documents every variable.

---

## 1. What is DONE

### P0 — deployment blockers

| ID | Item | Files |
|---|---|---|
| P0-1 | DB credentials moved to env vars; `load_dotenv()` made path-explicit | `config/settings/base.py` |
| P0-2 | `production.py` CSV parsing fix — `"".split(",")` → `['']` made `check --deploy` fail | `config/settings/production.py` |
| P0-3 | `requirements.txt` rebuilt (UTF-16→UTF-8, 11→15 pkgs; added gunicorn, whitenoise, Pillow, requests) | `requirements.txt` |

### P1 — provisioning & messaging

| ID | Item | Files | Tests |
|---|---|---|---|
| P1-4 | `provision_tenant` command — atomic, validated, password never passed in argv | `apps/tenants/management/commands/provision_tenant.py` | — |
| P1-3 | MSG91 SMS adapter | `apps/communications/adapters/sms.py` | 14 |
| P1-1 | AWS SES email adapter + the `EMAIL_*` settings block (none existed before) | `apps/communications/adapters/email.py`, `config/settings/base.py` | 14 |
| P1-2 | WhatsApp Meta Cloud API adapter + shared phone normalisation | `apps/communications/adapters/whatsapp.py`, `apps/communications/adapters/phone.py` | 17 |
| — | Platform tenant + platform comms | `apps/core/platform.py`, `apps/communications/services/platform_comms.py`, `apps/tenants/management/commands/ensure_platform_tenant.py` | 16 |
| — | Platform templates + trigger rules seeded | `apps/communications/management/commands/seed_platform_comms.py` | 12 |
| P1 | **Per-tenant SMS/WhatsApp credentials** | `apps/communications/models.py` (`TenantMessagingConfig`), `services/messaging_config_service.py`, both adapters, admin | 15 |
| P1 | **Invite-link onboarding** | `apps/tenants/` — `models.py` (`TenantInvite`), `invite_service.py`, `views.py`, `urls.py`, `create_tenant_invite` command, `templates/tenants/` | 29 |

**The adapter layer is complete — no mocks remain on any channel.**

### Verification at time of writing
- Full suite: **1181 passed, 0 failed** (~13–16 min) — run after both commits
- `apps/communications`: **199 passed**
- `manage.py check`: clean

### Commits
| SHA | Contents |
|---|---|
| `370b7cb` | All the infra work above — adapters, platform tenant, settings, pytest collection fix, this document |
| `a7d0dbf` | Snapshot of pre-existing uncommitted work found in the tree (17 previously untracked apps, templates, planning docs). **Not authored or reviewed as part of the infra effort** — do not assume it is verified. |
| `5f3d948` | Doc correction — commit SHAs and verified test count |
| `b8d11af` | Stop tracking `lifecycle_log.txt` (runtime log, already in .gitignore) |

All on **`fix/mvp-bugs`**, pushed to `origin/fix/mvp-bugs`. `develop` and `main`
are also in sync with origin. The infra work is **not yet merged into
`develop`** — open a PR from `fix/mvp-bugs` when ready. Working tree clean.

Deliberately **not** committed, via `.gitignore`:
- `memory/` — assistant working notes from an earlier session; contains local dev credentials. Note its `MEMORY.md` index references 5 files but only 2 exist.
- `audit_report.txt`, `dependency_analysis.txt`, `model_dependencies.txt`, `test_errors.txt` — regenerable analysis output.

---

## 2. Design decisions and WHY (don't re-litigate these)

**Email goes through Django's mail framework over SES's SMTP interface, not boto3.**
No new dependency, and the provider becomes swappable (SES → SendGrid → Mailgun → local relay) by changing env vars alone. Tests can use the locmem backend and assert on `mail.outbox`.

**WhatsApp requires a pre-approved template in production.**
Meta only allows free-form text if the member messaged the business within 24 hours. Every message this platform sends (reminders, receipts, renewals) is business-initiated and therefore falls *outside* that window, rejected with error 131047. The adapter uses a template whose body is a single `{{1}}` variable — the same one-variable shape the MSG91 DLT template uses — selected by `WHATSAPP_TEMPLATE_NAME`. Blank name = free-form, correct only for testing and in-window replies.

**Phone normalisation is shared (`adapters/phone.py`).**
MSG91 and Meta want the identical bare E.164 form. India numbering rules living in two files would drift. `sms.py` re-exports a wrapper that re-raises as `SMSDeliveryError` so its callers still catch one exception type.

**All adapters follow the same contract — this is load-bearing:**
- `__init__` must **never raise** — `_get_adapter()` builds *every* adapter on *every* send, so one missing credential would take the other two channels down.
- `send()` must **raise on failure** — the caller turns the exception into a FAILED `CommunicationLog` that `retry_failed_messages` picks up. Returning quietly records an undelivered message as SENT.
- Unconfigured → **log and return**, so dev and tests work without credentials.
- Signature is `send(self, to, message, subject="", text="")` — all four, always.

**ANJASI is modelled as an ordinary tenant flagged `is_platform=True`.**
The communications models are all tenant-scoped, so there was no "from the platform" concept. Rather than build a parallel platform-messaging stack, ANJASI is a tenant — templates, trigger rules, rate limiting, logging and retry are all reused. Cost: a synthetic tenant gets swept into jobs that loop over tenants, so those jobs call `exclude_platform()` (renewals scheduler, revenue nudges, `seed_comms_defaults` bulk mode). A DB constraint enforces at most one platform tenant.

```bash
./venv/Scripts/python.exe manage.py ensure_platform_tenant   # idempotent, has --dry-run
./venv/Scripts/python.exe manage.py seed_platform_comms      # ANJASI's own templates
```

**Onboarding a studio** (replaces SSH + `provision_tenant`):

```bash
./venv/Scripts/python.exe manage.py create_tenant_invite     --studio "Setu Yoga" --email owner@setuyoga.com --owner-name "Suresh"
```

The owner sets their own password via the emailed link, so no one handles it
for them. The raw token is printed once and stored only as a SHA-256 hash —
if it is lost, revoke the invite in Django admin and issue a new one.
`--no-email` prints the link without sending; `--dry-run` changes nothing.

> ⚠️ The link goes to a brand-new address, so **SES must be out of the sandbox**
> before this works for a real studio. In sandbox SES only delivers to verified
> identities. Development and tests are unaffected.

---

## 3. Credential ownership — who registers what

This split matters and is easy to get wrong, because you own both ANJASI and Setu Yoga and will perform both roles for tenant #1.

| Item | Owner | Why |
|---|---|---|
| **AWS SES** | **ANJASI** | Sending infrastructure, not an identity. One account serves every tenant. Tenants only add SPF/DKIM DNS records if they want mail from their own domain. |
| Razorpay | **Tenant** | Money settles into the studio's bank account. ANJASI cannot legally collect on their behalf without an RBI Payment Aggregator licence. |
| WhatsApp WABA + Business verification | **Tenant** | The account binds to the studio's phone number and verified name. Members must see "Setu Yoga", not "ANJASI". |
| MSG91 / DLT | **Tenant** | Under TRAI DLT the Principal Entity is whoever's content it is; the sender header is registered to their PAN/GST. |

**Code status against that model:**

| Channel | Per-tenant credentials? |
|---|---|
| Razorpay | ✅ `TenantPaymentConfig` — encrypted, `is_active`, per-provider |
| Email (SES) | ✅ correctly global — ANJASI-owned by design |
| SMS (MSG91) | ✅ `TenantMessagingConfig` — encrypted, `is_active`, env fallback for dev |
| WhatsApp (Meta) | ✅ `TenantMessagingConfig` — encrypted, `is_active`, env fallback for dev |

> ✅ Resolved. Each tenant's credentials live in `TenantMessagingConfig` (Django
> admin → Communications). Global env vars remain only as a dev / single-tenant
> fallback, and the app logs an ERROR if that fallback is used while more than
> one tenant exists — the misrouting failure mode is silent otherwise.

---

## 4. Bugs found while verifying (context for why coverage is distrusted here)

**Adapters were missing the `text` kwarg.** `BaseAdapter` and the caller both use four arguments; the SMS and WhatsApp mocks used three. **Every send on all three channels** raised `TypeError` and was silently recorded as FAILED. 32 existing tests missed it because they patch `send` with a `Mock`, which accepts any kwargs. There is now a contract test (`AdapterContractTests`) that pins the signature.

**`pytest.ini` `python_files` did not match `tests_*.py`.** **11 test modules had never run**, including `tests_razorpay.py` and `tests_tenant_config.py`. Fixed by adding the pattern. `*_test.py` is deliberately *not* in the list — `apps/core/views_test.py` is a views module whose view is named `test_ui`, which pytest mis-collects and fails.

**`notify_platform` returned `True` when no TriggerRule matched.** An unconfigured invoice event would report success while sending nothing. Now logs an error and returns `False`.

Lesson: on this codebase, *"the tests pass"* has repeatedly meant *"the tests did not run"*. Check collection counts change when adding files.

---

## 5. What is PENDING

### 5a. External approvals — the actual critical path
| Item | Owner | Wait |
|---|---|---|
| SES sandbox exit | **ANJASI** | 24–48h |
| Razorpay KYC | Setu Yoga | days |
| MSG91 DLT registration | Setu Yoga | days–weeks |
| Meta Business verification | Setu Yoga | days–weeks |
| Meta template approval | Setu Yoga | days — **sequential after verification** |

Code is not the constraint on any channel. These are.

### 5b. Immediate code work
| Item | Size | Note |
|---|---|---|
| **Nothing outstanding** | — | The P1 queue is clear. Next work is the P2 go-live list below. |

### 5c. P2 — before go-live
- Cron for the 10 management commands
- Real `SECRET_KEY`
- TLS / certbot
- Media → object storage (`MEDIA_ROOT` is local disk; tenant logos lost on rebuild)
- Widen `pytest.ini` `testpaths` — still `apps/assessments/tests`, so bare `pytest` runs 87 of 1124

### 5d. P3 — hardening
- Tests for the 7 apps with **no test module at all**: `activity`, `catalog`, `documents`, `expenses`, `payouts`, `platform_sessions`, `verticals`
- Sentry
- Manual refund SOP

### 5e. Deferred by explicit decision
- **SaaS subscription billing + ANJASI's own Razorpay.** No platform-level billing exists — `Tenant` has no plan, subscription, trial or billing state, and there is no `TenantSubscription`/`SaasPlan`/`PlatformInvoice` model. Decision: invoice manually until ~10 tenants; automated billing is a multi-week build best deferred until pricing settles.
- **Client self-service portal.** Confirmed absent, multi-week. Until it exists, new tenant credentials are entered via Django admin — acceptable for a handful of tenants, not beyond.

---

## 6. Suggested order when resuming

1. P2 go-live items (cron, SECRET_KEY, TLS, object storage, testpaths)
2. P3 hardening

Chase the **SES sandbox exit** in parallel from day one — it is ANJASI-side, only takes 24–48h, and item 3 depends on it.
