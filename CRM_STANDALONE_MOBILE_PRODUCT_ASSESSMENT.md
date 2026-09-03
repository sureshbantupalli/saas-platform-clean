# Standalone Local-First CRM — Product & Architecture Reassessment

**Supersedes:** the final architecture *recommendation* in `CRM_MOBILE_ARCHITECTURE_ASSESSMENT.md` (Option C / mobile-client-for-existing-server-CRM). That document's evidence about the existing Django CRM — what exists, what's well-designed, what's missing — remains accurate and is reused here as source material. Its recommendation does not apply to this product, because this is a different product (§17).
**Status:** Assessment only. No code written, no implementation started.
**Target product:** A standalone, local-first, zero-login, zero-mandatory-backend CRM app for Android + iOS, for solo professionals and small businesses. "No login. No cloud. No subscription. Just your customers."

---

## 1. Reassessed Existing CRM Assets — Five-Category Classification

### 1. Directly reusable
Nothing in the existing implementation is *directly* reusable — no Django code, no Postgres schema, no service-layer Python module can be dropped into a local-first mobile app unmodified, because the entire existing stack assumes a server, a request/response cycle, and multi-tenancy, none of which this product has. This is stated plainly and is not a negative finding — it is the expected, correct answer given how different the two products are (§17).

### 2. Reusable as domain knowledge
- Lead lifecycle concept: capture → work → won/lost, with a configurable ordered stage list (`LeadStage` design, `crm/models.py`).
- Lead temperature/priority as a *derived* signal from follow-up recency and record age (`crm/models.py:226-285`) — the algorithm shape, not the code.
- Follow-up automation triggers: something is created → schedule a next check-in automatically; a follow-up is completed → schedule the next one (`EnquiryLifecycleService.log_call`, `crm/services/enquiry_lifecycle_service.py:72-109`).
- The append-only, typed activity/timeline concept (`EnquiryActivity`'s action taxonomy, `crm/models.py:417-429`) — "every meaningful thing that happened to this customer, in order, never edited or deleted" is exactly the "customer memory" positioning this new product wants, and it's proven domain knowledge from the existing system.
- Validation rules as *product* rules, not code: don't allow marking something "lost" without a reason; don't let a stage change silently happen with no record of it (`crm/models.py:291-312`).
- Duplicate-phone detection as a UX safeguard when adding a new customer (`EnquiryForm.clean_phone`, `crm/forms.py:78-97`) — locally, this becomes "you already have a customer with this number," a genuinely useful quick-add-time nicety.

### 3. Reimplement in new architecture
- Persistence itself: a new local SQLite schema, not a port of the Postgres tables (§2).
- The service-layer *operations* (change stage, log an interaction, schedule/complete a follow-up) — same responsibilities, reimplemented as local-repository methods with no tenant/user/HTTP concept anywhere in their signatures.
- Search/filter — SQLite-native (FTS5 or indexed `LIKE`), not the Django `ListView` query-param pattern.
- Dashboard/metrics — `crm/metrics.py`'s *shape* (counts by stage, overdue count, recently added) is worth reimplementing as local aggregate queries; the Python module itself is not portable.

### 4. Not relevant
- Multi-tenancy (`Tenant`, `Branch`, `TenantAwareModel`, `TenantMiddleware`) — this product has exactly one user and no concept of an organization.
- RBAC (`Role`, `RolePermission`, `PermissionAction`, `RBACService`) — there is no second user to grant or withhold permissions from.
- Django session/Basic auth, and the JWT/token-auth work recommended in the prior assessment — no server, no account, nothing to authenticate *to*.
- `Enquiry.assigned_to`/staff-performance reporting (`crm/views.py:126-155`, `crm/metrics.py:69-81`) — meaningless for a single user.
- The Enquiry→Member conversion mechanism specifically (creating a *different kind of record* in a *different subsystem* — memberships/billing/attendance) — this new product has no such downstream subsystem to convert into (§7).
- `apps/documents` (billing documents), `apps/intake` (custom intake forms), `apps/payments`/`apps/bookings` signal integrations — all belong to the fitness-vertical SaaS platform's own domain, not this product.
- API versioning, pagination, DRF permission classes, rate limiting — all solve problems (many clients, many tenants, a network boundary) this product doesn't have.

### 5. Potential future integration
- The existing Postgres schema and Django domain model are a reasonable **reference design** if a future optional "Team/Cloud" tier of this same product is ever built (a genuinely different SKU — see §17) — but that tier would likely be its own service, not a retrofit of the existing multi-tenant fitness platform.
- `apps/communications`' adapter/event pattern (email/SMS/WhatsApp adapters, rate limiting, retry) is a reasonable reference if a future cloud tier ever needs server-triggered notifications (e.g., a team-shared reminder) — not relevant to the fully local V1.
- The RBAC data model (`module:action:scope`) is a reasonable reference for a future multi-user/team tier, where "who on the team can edit this customer" becomes a real question for the first time.

---

## 2. Database Re-Evaluation

**Option 3 — local SQLite now, designed so optional future sync doesn't require a rewrite — is the correct choice**, and it earns that conclusion on its own merits, not because it was suggested as the expected answer:

- **Option 2 (Postgres via API) is disqualified outright by the product definition itself**, not by a preference — "no mandatory server" is a stated, non-negotiable product principle, and Option 2 requires one by construction. It is not a close call.
- **Option 1 (local SQLite, designed only for what V1 needs, no forward-compatibility considerations)** would work for V1 but creates a real, avoidable future cost: if autoincrement integer local IDs are used and a device later needs to sync with another device or a server, every foreign key in the local database would need remapping the moment two devices' ID sequences collide — a genuinely painful migration. The fix (UUID primary keys instead of autoincrement integers) costs nothing today and eliminates that entire future problem.
- **Option 3** is Option 1 plus a small, deliberate set of schema decisions (UUIDs, timestamps, soft-delete, a local revision counter — detailed in §5) that cost effectively nothing to include now and preserve every future option without building any actual sync mechanism today. This is not "building for a hypothetical" — none of these decisions add a feature, a screen, a dependency, or a line of sync logic; they are just *which kind of primary key* and *which extra timestamp columns* the schema uses. That is why Option 3 wins without over-engineering: the cost of choosing it is approximately zero.

**Recommendation: local SQLite (via `drift` in Flutter, or platform-equivalent), forward-compatible schema, no sync code in V1.**

---

## 3. Backend Re-Evaluation — Is One Required for V1?

Walking through every capability named in the brief, against what the device alone can do:

| Capability | Requires a backend? | Why |
|---|:---:|---|
| Create customer records | No | Local insert |
| Record interactions | No | Local insert, append-only |
| Schedule follow-ups | No | Local insert + OS-scheduled local notification |
| Operate pipelines | No | A local field with local business rules |
| Search/filter | No | SQLite is fast enough at solo/small-business record volumes (hundreds to low thousands of customers) without a server-side search index |
| Reminders (actually firing) | No | Local notification scheduling APIs (`flutter_local_notifications`/native equivalents) are OS-level, not push-service-dependent — this is the key distinction from server-triggered push, which *would* need a backend |
| Backup/export | No | Writing a file to device storage / OS share sheet requires no server; the *destination* the user picks (Drive, iCloud, email) is the OS's job, not the app's |
| Import (contacts/CSV) | No | Local parsing, local inserts |
| PIN/biometric | No | This is device-local access control, not authentication to anything remote — see §4 |

**Explicit answer: No backend is required for V1.** Every core capability the product needs is achievable entirely on-device. An API was not introduced here merely because the source project happens to be Django — the evidence above is the actual justification, and it would reach the same conclusion regardless of what the existing platform was built with.

---

## 4. Authentication Re-Evaluation

Two genuinely different things must not be conflated, and the existing CRM's own vocabulary (session auth, RBAC, tenant roles) belongs entirely to the first category, which this product does not need:

- **Authentication to a server** — proving identity to a remote system so it releases *that account's* data. Not applicable: there is no server and no account.
- **Local application access control** — a gate on the *device* deciding whether the person holding the phone right now may open the app and see the PII already sitting on it. This *is* applicable, because the app stores real customer names/phone numbers on a device that can be lost, stolen, or picked up by someone else.

**Recommended local security model:**
- No account, no username, no password, no server-side identity of any kind — ever, for the core product.
- Optional (not forced during first-run) **PIN**, offered once during onboarding as a single, dismissible prompt — the app must be fully usable with zero setup friction, matching the "extremely simple" principle, but a business notebook containing real people's contact details left completely unlockable by default undersells the product's own trustworthiness. A PIN gate is a *few seconds* of friction the user can decline entirely, not a login flow.
- **Biometric unlock** (Face ID / Touch ID / Android biometric) layered on top of the PIN as a convenience, never as a replacement for having *some* underlying local secret — biometric failure or unavailability always falls back to the PIN, never locks the user out permanently, and never phones home to verify anything.
- The local database itself should be encrypted at rest regardless of whether the user enables a PIN (see §12) — the PIN/biometric gates the *screen*, encryption protects the *file*, and these are two different, complementary controls, not the same thing.
- JWT, OAuth, user accounts: **not introduced**, and there is no evidence anywhere in this product's own stated principles that would justify them for V1.

---

## 5. Offline Architecture Re-Evaluation

The prior assessment's "read-cache + write-outbox" model assumed a server whose data the app was catching up with — that concept does not apply here, because **there is no remote source of truth to be behind.** The correct model is local-first / local-source-of-truth, exactly as sketched in the brief:

```text
Mobile App
    │
    ├── UI (screens/widgets)
    ├── Application Layer (use-cases: "add customer", "log interaction",
    │      "complete follow-up" — orchestration only, no business rules)
    ├── Domain Layer (pipeline-stage rules, temperature/priority scoring,
    │      duplicate-phone check — pure logic, no I/O)
    ├── Local Repository (the only thing that talks to the database;
    │      everything above this line is 100% unaware SQLite exists)
    └── Local SQLite Database
             ├── customers
             ├── interactions
             ├── follow_ups
             ├── pipeline_stages
             ├── tags
             └── settings
```

There is no "online" and "offline" mode to design for — there is only "on." Network connectivity is never checked, never required, and never referenced anywhere in the application or domain layers. The only place network ever appears at all is the OS-level share sheet the user invokes *themselves* to move an export file somewhere (§13) — an action the app hands off to the operating system and has no further involvement in.

---

## 6. Future Cloud Sync — What to Decide Now, What Not to Build Now

**Decide now (near-zero cost, preserves every future option):**
- **UUID primary keys** on every entity (`Customer`, `Interaction`, `FollowUp`, `PipelineStage`, `Tag`) — never autoincrement integers. Generated client-side at creation time, so a record's identity is stable before it has ever touched a network.
- **`created_at` / `updated_at`** on every row, set/maintained by the repository layer, not left to the UI to remember.
- **`deleted_at`** (nullable) instead of hard delete anywhere in the schema — a deleted customer becomes invisible in the UI immediately but the row persists as a tombstone. This is what makes both "Recently Deleted" recovery (§13) and any future sync's deletion-propagation possible, for the same underlying reason.
- **A local revision counter** (`local_rev`, a simple monotonically incrementing integer per row, bumped on every write) — cheap to maintain now, and it is exactly the primitive a future last-write-wins or more advanced sync strategy would need; adding it retroactively means backfilling every historical row, which is unnecessary friction to avoid.
- **A device-local install identifier** (`device_id`, generated once, stored in `settings`) — needed the moment there is ever more than one device, whether that's a future sync feature or simply "the user's data exported from Phone A and imported into Phone B" (§13's move-to-new-phone path already benefits from being able to say which device a record originated on).
- **A versioned export/import format** (see §13) — designing this well now, as a clean, self-describing JSON schema, means it can double as the wire format for a future sync protocol without a second design pass; a raw SQLite-file dump would not.
- **A `schema_version` field in `settings`, with a real (if currently tiny) local migration runner from first release** — this is not sync-driven scope; any local-only app needs a way to evolve its schema across app updates, and building that muscle from v1.0 rather than retrofitting it after the first breaking schema change is just ordinary good practice.

**Do not build now:**
- No sync protocol, no server endpoint, no conflict-resolution UI, no merge engine, no push-based real-time updates, no multi-device awareness beyond the single `device_id` field above. None of this is justified by V1's actual requirements, and building it speculatively is exactly the over-engineering the brief warns against. If/when a future cloud tier is greenlit, the schema decisions above mean that work starts from "add a sync engine" rather than "redesign the local schema and migrate every existing user's data," which is the entire point of deciding these items now and nothing more.

---

## 7. Existing CRM Domain — What's Generic vs. Industry-Specific

| Existing (fitness-platform-specific) | Underlying generic concept | Carried forward? |
|---|---|---|
| `Enquiry` | A person you're in a sales/service relationship with, at any stage | Yes — as `Customer`, unified (see below) |
| `Enquiry → Member` (conversion to a *different model* in a *different subsystem* — memberships/billing/attendance) | "This person said yes" | Yes, but as a **stage change on the same record**, not a conversion to a different entity — this product has no separate downstream subsystem for a converted customer to become a member *of* |
| `LeadStage` (tenant-scoped, admin-configured) | An ordered, user-customizable pipeline | Yes — as `PipelineStage`, single-user-scoped instead of tenant-scoped, shipped with sensible defaults the user can edit |
| `EnquirySource` | Where a lead came from | Yes, but demoted from a rigid managed lookup table to a lightweight optional tag/field — a solo user doesn't need a source-management screen |
| `EnquiryLostReason` | Why a lead didn't convert | Optional/Should-have — a short free-text field or a small default list, not a strictly enforced separate entity |
| `FollowUp` | A scheduled check-in | Yes — as `Reminder` (or `FollowUp` — naming is a UX decision, not architectural), central to the product |
| `EnquiryActivity` | An immutable timeline of everything that happened | Yes — as `Interaction`, central to the "customer memory" positioning |
| Lead temperature / priority | A derived urgency signal | Yes, as a computed local value, not a stored field |
| `assigned_to`, staff performance, `Branch` | Multi-user/multi-location coordination | No — single user, no organization concept |
| `Tenant`, RBAC | Who's allowed to do what | No — see §1 category 4 |

**The single most important reframing:** the existing system treats "Enquiry" and "Member" as two different kinds of things, connected by a one-time, one-way, irreversible conversion event, because a Member unlocks a completely separate subsystem (memberships, billing, class attendance) that this standalone product does not have and has no reason to build. For this product, there is no second subsystem to hand a person off to — so the correct model is **one entity, `Customer`, whose relationship stage changes over time**, not two entities joined by a conversion. This is a genuine, deliberate design departure from the existing system, made because the reason for the existing split (a downstream subsystem) doesn't exist here — not an oversight, and not a case of blindly copying the old model.

---

## 8. New Product Domain Model

| Entity | Included in V1? | Notes |
|---|:---:|---|
| `Customer` | ✅ | Unified lead+customer (see §7). Fields: `id` (UUID), `name`, `phone`, `email?`, `pipeline_stage_id`, `created_at`, `updated_at`, `deleted_at?`, `local_rev`. |
| Contact information | ✅ | Folded into `Customer` (phone/email), not a separate entity — one customer, a small fixed set of contact fields, no need for a generalized multi-value contact-method table at this scale. |
| `Tag` | ✅ (lightweight) | Free-form, user-created, many-to-many with `Customer`. Simple list, not a managed taxonomy. |
| `Note` | Folded into `Interaction` | A note *is* an interaction (type = "note") — see reasoning below; not a separate table. |
| `Interaction` | ✅ | The activity timeline. Fields: `id` (UUID), `customer_id`, `type` (note / call logged / whatsapp / sms / email / stage changed / follow-up completed), `text?`, `created_at`. Append-only — no edit/delete of history, matching the existing `EnquiryActivity` design's proven value. |
| `Reminder` / `FollowUp` | ✅ | Fields: `id` (UUID), `customer_id`, `due_at`, `type?`, `status` (pending/done/missed), `note?`. |
| `PipelineStage` | ✅ | User-editable ordered list, sensible defaults shipped (e.g., New → Contacted → Interested → Won / Lost). Not tenant-scoped — one list per install. |
| Pipeline (as a board/view) | ✅ as a **view**, not a new entity | Just a grouping of `Customer` by `pipeline_stage_id` — no separate "Pipeline" table needed. |
| Activity history | ✅ | = `Interaction`, per-customer chronological list; this *is* the app's core value proposition, not a secondary feature. |
| `Settings` | ✅ | Single local row: PIN hash, biometric-enabled flag, `device_id`, `schema_version`, `last_backup_at`, notification preferences (e.g., "hide names on lock screen" — §12). |
| Backup/export metadata | Folded into `Settings` | `last_backup_at` is enough; no need for a dedicated table to track backup history in V1. |

**Deliberately not added**, and why: a separate `Note` entity (redundant with `Interaction`, and splitting them would fragment the single chronological timeline the product's whole value proposition depends on); `EnquiryLostReason` as a rigid managed table (a free-text field or an optional short list is enough at this scale — an entire CRUD screen for managing "reasons a deal was lost" is exactly the kind of enterprise-CRM weight this product is explicitly positioned against); any `Branch`/organization concept (no multi-location relevance for a solo user).

---

## 9. MVP Re-Evaluation

| Feature | Classification | Reasoning |
|---|---|---|
| Home dashboard | **Must** | Orientation on open — "what needs my attention today." |
| Today / overdue / upcoming follow-ups | **Must** | This *is* the core daily-use loop; without it, the reminder feature is inert. |
| Customer database (list) | **Must** | The core data set. |
| Customer profile | **Must** | Where the "memory" lives. |
| Notes | **Must** (as `Interaction` type) | See §8 — folded in, not cut. |
| Interaction history | **Must** | Central to the product's own positioning. |
| Tasks/reminders | **Must** | Same concept as follow-ups (§8) — one feature, not two. |
| Pipeline (as *data*, a stage per customer) | **Must** | Every customer needs *some* status; cheap, high-value. |
| Pipeline (as a visual Kanban *board with drag-and-drop*) | **Should / Later** | The underlying stage concept is Must; a dedicated drag-and-drop board UI is a nice-to-have that can ship as a stage badge + quick-picker in V1 and become a full board later — separating the data requirement from the UI-polish requirement avoids over-scoping V1's UI work. |
| One-tap Call | **Must** | Zero backend cost (`tel:` intent), high, frequent value. |
| WhatsApp | **Must** | Same cost profile as Call; explicitly named as central to the target workflow (§14). |
| SMS | **Should** | Same low cost (`sms:` intent) as Call/WhatsApp but lower expected usage frequency for this audience — cheap enough to bundle into the same release rather than truly deferring. |
| Email | **Should** | `mailto:` intent, low cost, lower usage frequency than Call/WhatsApp for this target user. |
| Maps | **Should / Later** | Only meaningful if a customer has an address on file; not core to a quick-add-focused product — add once an address field exists, not before. |
| Phone-contact import | **Should** | High onboarding value ("bring my existing contacts in as customers") but adds real complexity (permissions, de-duplication against phone number) — valuable fast-follow, not a hard V1 gate, since manual quick-add already delivers the core loop. |
| CSV export | **Must** (elevated) | Directly required by the "no lock-in" principle — a user must be able to get their data *out* in a portable, spreadsheet-openable form, not only as an app-specific backup file. |
| CSV import | **Should** | Useful, not core-loop-blocking; naturally follows once export exists (same parsing/mapping logic, reversed). |
| Local JSON backup | **Must** | Directly and explicitly required by the product principles as stated. |
| PIN lock | **Must** (offered, not forced) | Real PII on a losable device; see §4 for exactly how this is offered without adding onboarding friction. |
| Biometric unlock | **Should** | A convenience layered on the PIN, not a substitute for it — valuable, not blocking. |
| Local notifications | **Must** | Without these, "today's follow-ups" requires the user to remember to open the app — the feature doesn't function without this. |
| No server required | **Must** (constraint, not feature) | The defining product principle; confirmed achievable in full in §3. |

---

## 10. Quick-Add UX — Architectural Requirements

Target: Name → Phone → Interest → Follow-up date → Done, in ~15 seconds. This is achievable, and it drives specific, concrete architecture decisions rather than being a purely visual-design concern:

- **Every `Customer` field except `name` and `phone` must be nullable at the schema level.** A quick-add flow that silently requires five fields behind the scenes (even if the UI only shows four) will eventually force the user into a slower path; the schema must genuinely permit a bare `{name, phone}` row.
- **One screen (or a single bottom sheet), not a multi-step wizard.** Every field visible and editable at once; no "Next" button chain.
- **Smart defaults, always pre-filled, always overridable:** `pipeline_stage_id` defaults to the first stage in the user's list with no picker interaction required unless the user wants to change it; `due_at` for the initial follow-up defaults to "tomorrow" (mirroring the existing system's own proven auto-follow-up-next-day rule, §1 category 2), again editable but never blocking.
- **"Interest" is a plain text field or a small chip-select of the user's own recent/common tags — never a required relational lookup** that would force navigation away from the quick-add screen to create or find a matching record first.
- **Keyboard-first interaction:** auto-focus the name field on open, numeric keypad automatically for the phone field, large tap targets for the date-quick-picks ("Tomorrow" / "In 3 days" / "Next week" chips rather than requiring a full calendar-picker interaction for the common case).
- **"Done" is instantaneous.** Because there is no network call in the critical path (§5), the save is a local write with no perceptible latency and no loading spinner — this is one of local-first's real, tangible UX payoffs for this specific interaction, not an incidental side effect.
- Architecturally, this argues for a distinct, deliberately minimal `quickAddCustomer(name, phone, interest?, followUpDate?)` repository method, separate from the fuller "edit customer" form that exposes every field — two different UX surfaces over the same underlying table, not one form with progressive disclosure bolted on.

---

## 11. WhatsApp-First Workflow — What's Realistically Implementable

The requested flow — Customer → WhatsApp → return to record → add interaction → set follow-up — is achievable, but with one honest, explicit limitation stated up front: **the app can launch WhatsApp and can detect that the user has come back to the app afterward, but it cannot see anything that happened inside WhatsApp.** There is no public consumer-facing WhatsApp API that exposes message content, delivery status, or read receipts to a third-party app, and assuming otherwise would be an unsupported claim this assessment is explicitly instructed to avoid.

What *is* standard, well-supported, and safe to build:
- **Launch:** `https://wa.me/<phone>` (optionally with a pre-filled `?text=`) opens a chat with that number directly in WhatsApp — supported on both platforms via a standard URL scheme, no WhatsApp account/API integration required on the app's side.
- **Detect return:** standard app-lifecycle events (`onResume` / the app becoming foregrounded again) let the app notice "the user just came back," without knowing anything about what they did in the other app.
- **Prompt, don't assume:** on that return, show a small, dismissible, one-tap prompt — "Add a note about your WhatsApp message to Priya?" — that the user can accept (logging an `Interaction` of type "whatsapp") or dismiss with zero friction. This is a real, commonly-used pattern in consumer apps and relies only on the app's own lifecycle, not on any WhatsApp-provided signal.
- Identical reasoning and identical implementation shape apply to **Call, SMS, and Email** — the same `tel:`/`sms:`/`mailto:` launch-and-detect-return pattern. One additional, platform-specific limitation worth flagging explicitly: **iOS does not allow third-party apps to access call history or call outcomes at all** (no CallKit-based read access for arbitrary apps), so "log a call" must be a manually-confirmed, prompted action on iOS by necessity, not merely by design choice — Android is somewhat more permissive in principle but the same manual-prompt pattern should be used uniformly across both platforms for a consistent product experience rather than having iOS and Android behave differently.

---

## 12. Backup and Recovery — First-Class Requirement

- **Create a local backup:** on-demand (a button in Settings) and optionally auto-reminded ("It's been 30 days since your last backup") — never silent/automatic-only, since the user should always know a backup happened and where it went.
- **Format:** a versioned, self-describing **JSON export** as the primary backup format (doubles as the future sync wire format, §6) *and* a simple raw-file copy of the SQLite database as a secondary "fast, exact" option — two different tools for two different needs: JSON is portable/inspectable/future-proof, the raw file is the fastest possible full-fidelity snapshot.
- **Where it goes:** handed to the OS share sheet — the user picks Google Drive, iCloud Drive, email-to-self, a file manager, AirDrop, whatever they already use. The app never manages cloud storage itself, which is precisely what keeps "backup is mandatory" and "no mandatory cloud" simultaneously true: the app requires the *capability*, not any particular *destination*.
- **Restore:** import that same file back in. **V1 scope: restore targets a fresh/empty local database only**, with a clear warning if existing data is present, rather than attempting a merge — merge conflict resolution is explicitly deferred (§6) and should not be smuggled into V1 via the restore flow.
- **Move to a new phone:** the same export → (user moves the file via their own chosen method) → import flow, explicitly documented in-app as "Moving to a new phone?" — this is not a separate mechanism, it's the same backup/restore pair given a second, user-facing name for the scenario people actually search for.
- **CSV export:** a distinct, separate purpose from JSON backup — CSV is for "take my data to a spreadsheet or another tool," not for perfect-fidelity restore (it naturally can't represent nested per-customer interaction/reminder history in a flat table well) — both should exist, and neither should be presented as a substitute for the other.
- **Accidental-deletion recovery:** because deletes are soft (`deleted_at`, §6), a simple **"Recently Deleted"** list (auto-purged after, e.g., 30 days) gives free, immediate recovery for the common "oops, wrong customer" case without needing a full backup restore or a complex undo-stack.

---

## 13. Security — Local-Device-Specific

- **Local database encryption at rest:** encrypt the SQLite file itself (e.g., SQLCipher, or the equivalent encrypted-database capability of the chosen local-DB package) rather than relying solely on the OS's own full-disk encryption — protects against extraction from a rooted/jailbroken device or an unencrypted device-level backup.
- **Key management:** the encryption key is generated on first launch and stored in the **Android Keystore** / **iOS Keychain** (hardware-backed Secure Enclave where the device supports it) — never in the database itself, never in plain app-preferences storage.
- **PIN handling:** stored only as a salted hash, never in plaintext; ideally used to gate/derive access to the Keystore-held encryption key rather than being an application-level string comparison sitting beside the data it's meant to protect.
- **Biometric:** implemented via the platform's own biometric APIs (BiometricPrompt / LocalAuthentication), always with a PIN fallback — never the sole access path, and never something the app implements itself rather than delegating to the OS.
- **Backup/export file security:** once an export leaves the app's encrypted local storage (e.g., a JSON file now sitting in the user's Google Drive), it is **no longer protected by the app's own encryption** — this should be stated to the user, not left implicit, and the export flow should offer an optional user-chosen export password (a standard password-derived-key-encrypted archive) especially for the "move to new phone" scenario, which is the path most likely to transit through email or shared cloud storage.
- **Screenshot / app-switcher preview:** mark customer-data screens with the platform's secure-content flag (`FLAG_SECURE` on Android; iOS has a more limited but partially analogous mechanism) so a list of real customer names/numbers doesn't appear in the OS's recent-apps thumbnail preview.
- **App data isolation:** covered by standard OS app-sandboxing; the only action item is to avoid ever writing customer data to a world-readable or unencrypted location outside the app's own sandbox except via the explicit, user-initiated export flow.
- **Clipboard leakage:** both platforms now surface a system notice when an app reads the clipboard; low risk here, but avoid unnecessary auto-copy-to-clipboard behaviors for phone numbers/emails beyond an explicit user tap.
- **Notification privacy:** reminder notifications will, by default, show a customer's name on the lock screen ("Follow up with Priya Sharma today") — support the OS's sensitive-content-hidden notification style as a user-toggleable setting, since this is a real, concrete, and easily-overlooked privacy leak for an app that is, by design, carried around in someone's pocket.
- **What is explicitly not needed:** any server-side authentication, session/token security, CORS, or API rate-limiting — all of it belongs to Product A's threat model (prior assessment §14), not this product's, because there is no server-side attack surface here to defend at all.

---

## 14. Existing CRM Reuse Matrix

| Existing CRM Asset | Reuse Directly | Reuse Conceptually | Reimplement | Future Integration | Do Not Reuse | Reason |
|---|:---:|:---:|:---:|:---:|:---:|---|
| Django models (`crm/models.py`) | | | ✅ | | | Framework/ORM-coupled to a server stack this product doesn't have; the *field shapes* inform the new local schema |
| `crm/services/*` (lifecycle, guard, followup) | | ✅ | ✅ | | | Operations and rules are worth carrying forward; the Python service classes themselves are not portable to a mobile client |
| Business rules (stage-transition validation, duplicate-phone check, follow-up auto-scheduling) | | ✅ | | | | Exactly the kind of domain knowledge worth reimplementing locally, unmodified in *intent* |
| PostgreSQL database | | | | ✅ | | Only relevant if a future server/cloud tier is built; irrelevant to local-first V1 |
| PostgreSQL schema design (constraints, relationships) | | ✅ | | | | Reference design informs the local schema's own constraints |
| Django views (`crm/views.py`) | | | | | ✅ | Server-rendered-HTML-coupled; nothing to carry forward, not even conceptually — the new app has its own native UI |
| Django forms (`crm/forms.py`) | | ✅ (validation rules only) | ✅ | | | The Django `ModelForm` mechanism is discarded; the specific validations it encodes are reimplemented locally |
| Templates (`templates/crm/*`) | | | | | ✅ | Web-rendering artifact, zero relevance to a native mobile UI |
| APIs (the 3 ad hoc `JsonResponse` endpoints) | | | | | ✅ | Never a real API to begin with (prior assessment §11); nothing to reuse |
| Authentication (session/Basic, and the JWT work recommended for Product A) | | | | ✅ | | Only relevant to a future account-based/cloud tier; V1 has no authentication-to-a-server concept at all |
| RBAC (`Role`/`RolePermission`/`PermissionAction`/`RBACService`) | | | | ✅ | | Same — only meaningful once there is a second user to grant/deny permissions to |
| `crm/metrics.py` | | ✅ | ✅ | | | The dashboard-aggregation *shape* is reused; the Django/Postgres query code is not |
| `EnquiryActivity` (activity/audit history) | | ✅ | ✅ | | | The single most valuable conceptual asset for this product — becomes `Interaction`, the core "memory" feature |
| `FollowUp` / follow-up logic | | ✅ | ✅ | | | Becomes `Reminder`, a Must-have core loop feature |
| Lead temperature / priority scoring | | ✅ | ✅ | | | Reimplemented as a local computed value, same underlying signal (follow-up recency, record age) |
| `LeadStage` / pipeline | | ✅ | ✅ | | | Becomes `PipelineStage`, single-user-scoped instead of tenant-scoped |
| Validation (duplicate phone/email, stage-transition guards) | | ✅ | ✅ | | | Rules carried forward, mechanism rebuilt |
| Signals (`crm/handlers.py`, cross-module event integration) | | | | | ✅ | Exists specifically to bridge CRM with the fitness platform's payments/bookings modules, which this product has no equivalent of |
| Enquiry→Member conversion workflow | | ✅ (the underlying "they said yes" concept) | | | ✅ (the mechanism) | The *concept* survives as a stage change on the same `Customer` record (§7); the *mechanism* (creating a record in a separate downstream subsystem) does not apply — there is no such subsystem here |

---

## 15. Product A vs. Product B — Why These Are Different Products

| | **Product A** — mobile client for the existing server CRM | **Product B** — standalone local-first CRM |
|---|---|---|
| Buyer | An existing SaaS platform tenant, already paying for the fitness-business platform | A solo professional or small business who may never have heard of the original platform |
| Business model | Bundled feature extending an existing subscription | Potentially free/freemium, independent go-to-market, possibly its own brand |
| Distribution | Delivered to users who already have platform accounts | App-store discovery, cold-start acquisition, zero prerequisite |
| Technical foundation | Must integrate with existing tenant/RBAC/Postgres/session-auth infrastructure | Zero technical dependency on the original platform; could ship even if that platform's server disappeared tomorrow |
| Trust/data model | Institutional — an admin manages staff logins and centrally controls tenant data | Personal — one individual owns their own data outright, on their own device |
| Source of truth | The server, always | The device, always (by design, not by limitation) |
| What "offline" means | A degraded mode to tolerate until reconnected | The only mode there is — not degraded, just how the product works |
| Primary engineering challenge | API design, auth, object-level authorization, sync-with-server correctness | Local schema design, on-device security, forward-compatible-but-unbuilt sync readiness |

These are not two points on one roadmap — they are two different products that happen to share a common ancestor in their business-rule thinking (§1, §7). Treating Product B as "Product A's V1, minus the server for now" would be a mistake in both directions: it would import genuine complexity Product B doesn't need (tenancy, RBAC, API versioning, token auth), and it would risk under-investing in what Product B actually needs and Product A never had to think about at all (on-device encryption, PIN/biometric UX, a forward-compatible local schema, a real backup/restore story, offline-native reminder scheduling). The comparison in this document was built independently against Product B's own stated principles (§2-§13) precisely to avoid that bias, not by starting from Product A's architecture and subtracting the server.

---

## 16. Final Architecture — Standalone Local-First CRM V1

### Mobile Framework Evaluation (for *this* product specifically)

| Framework | Fit for this product |
|---|---|
| **Flutter** | **Recommended.** No backend/API-client concern to weigh (unlike Product A's evaluation), so the deciding factors here are: single codebase for a lean V1 team; mature, well-maintained plugin coverage for every capability this product actually needs (`drift` + SQLCipher for encrypted local SQLite, `local_auth` for biometrics, `flutter_local_notifications` for reminders, `url_launcher` for tel:/sms:/mailto:/WhatsApp intents, `contacts_service`/platform contact-picker APIs, `share_plus`/file-export for backup); and rendering performance that comfortably exceeds what a list/detail/reminder-style consumer app needs. |
| **React Native** | Workable — the same plugin-coverage argument applies via the RN ecosystem's own equivalents — but offers no particular advantage over Flutter for this feature set, and the JS-bridge architecture is a real (if usually minor, for an app this simple) performance consideration Flutter doesn't have. No compelling reason to prefer it here. |
| **Kotlin Multiplatform** | More *interesting* for this product than it was for Product A, because with zero backend/API-client layer to share, KMP's actual value proposition (shared business/domain logic, fully native UI per platform) is cheaper to realize — there's simply less to share overall, so the "why pay for two UI codebases" cost is the whole story. Worth serious consideration **if** platform-idiomatic native UI polish is judged to matter commercially for this specific consumer positioning; not the default V1 recommendation absent that evidence, because it means building two UIs (SwiftUI + Jetpack Compose) for a product whose success depends on speed-to-market and simplicity more than platform-native chrome. |
| **Native (separate Android + iOS codebases)** | Not justified — this product's UI complexity (list/detail/reminders/simple pipeline view) does not require platform-specific engineering depth, and building two full native apps is the highest-cost option for the lowest incremental benefit here. |

**Recommendation: Flutter**, arrived at independently against this product's own requirements (no backend/API weighting carried over from the prior assessment) — the recommendation happens to match Product A's, but for different, product-specific reasons stated above, not by default.

### Architecture Summary
- Local-first, offline-native, zero-login, zero-backend, as detailed in §3-§5.
- Encrypted local SQLite (`drift` + SQLCipher) as the sole source of truth, forward-compatible schema per §6, no server component anywhere in V1.
- PIN + optional biometric local access control, offered not forced, per §4.
- Native OS integrations only (`tel:`/`sms:`/`mailto:`/WhatsApp URL scheme, local notifications, contacts, share sheet) — no proprietary integration assumed beyond standard, documented platform capabilities (§11).
- Backup/export as a first-class, always-available, user-directed feature, never a hidden or automatic cloud dependency (§13).
- Testable: domain layer (pipeline rules, temperature scoring, duplicate detection) is pure logic with no I/O, trivially unit-testable; repository layer tested against an in-memory/test SQLite instance; no server/network mocking required anywhere, which is a genuine testing-simplicity advantage of this product over Product A.
- Extensible toward an optional future cloud tier without that tier's existence being assumed, required, or partially built now (§6).

---

## 17. FINAL DECISION

### RECOMMENDED DECISION

**Product Architecture:**
Standalone, local-first mobile application. Layered client architecture (UI → Application → Domain → Local Repository → Local SQLite), with zero server dependency of any kind for the core product.

**Backend Required for V1:**
NO.

**Login Required:**
NO.

**Cloud Required:**
NO.

**Local Database:**
SQLite, encrypted at rest (SQLCipher or equivalent), accessed via a repository layer (`drift` recommended for the Flutter choice below).

**Source of Truth:**
The device's local database, unconditionally. There is no remote copy to reconcile against in V1.

**Offline Capability:**
Full, native, and permanent — not a fallback mode. The app has no concept of "online" anywhere in its application or domain layers; the only network-adjacent action in the entire product is the user manually invoking the OS share sheet to move a backup/export file somewhere of their own choosing.

**Existing CRM Database:**
Reference only. The Postgres schema's relationships and constraints inform the new local schema's design; no data, table, or connection is reused, and no migration from it is performed.

**Existing CRM Backend:**
Do not reuse. The Django views/services/models are server-and-tenant-coupled by construction; their *rules* are reimplemented locally (§1, §14), their *code* is not carried over.

**Existing CRM Business Logic:**
Survives as domain knowledge: pipeline/stage lifecycle, follow-up automation triggers, lead temperature/priority scoring, duplicate-phone detection, and — most importantly — the append-only activity-timeline concept that becomes this product's central "customer memory" feature. All reimplemented natively and locally; none of the surviving logic requires a server to execute.

**Existing CRM Frontend:**
Not reused in any form, not even conceptually — a fully native mobile UI is required regardless of what the existing frontend looks like, because the existing frontend is server-rendered HTML and this product has no server to render from.

**Existing CRM API:**
Not applicable — none existed to begin with (prior assessment §11), and this product needs none.

**Authentication/RBAC:**
Neither is introduced. Replaced entirely by local application access control (PIN, optional biometric) gating access to an encrypted local database — a device-level concern, not an identity-to-a-server concern (§4).

**Mobile Framework:**
Flutter — recommended independently against this product's own requirements (§16), not carried over by default from the prior assessment, though it reaches the same conclusion for largely overlapping reasons (single codebase, mature plugin ecosystem, strong local-database/offline tooling).

**Future Cloud Sync:**
Accommodated architecturally, not built. UUID identifiers, `created_at`/`updated_at`/`deleted_at`, a local revision counter, a device identifier, and a versioned JSON export format are adopted now, at near-zero cost, specifically so that a future sync engine — if ever built — can be added without a disruptive schema migration or a redesign of the local data model. No sync protocol, conflict-resolution logic, or server component is part of V1.

**Estimated Existing CRM Reuse:**
Qualitative, not a percentage, because the two products' delivery mechanisms are almost entirely disjoint (server-rendered Django vs. offline-native mobile), which makes a code-reuse percentage close to meaningless here — the honest measure is: a **small but genuinely valuable fraction of the existing CRM's total engineering effort transfers directly** (essentially none of the code, but a real and well-proven set of business rules and the activity-timeline design pattern), while the **overwhelming majority of this new product's engineering work — local persistence, on-device security, native platform integrations, and the entire mobile UI — is net-new regardless of the existing CRM's quality**, because that existing CRM was never built to run anywhere except behind a server it no longer has in this product.

---

### MOST IMPORTANT CONCLUSION

> **If we had no existing CRM at all and were starting this product today, would we design it differently from the existing CRM?**

**Yes, substantially.** Not because the existing CRM is poorly built — its service layer, activity-audit design, and follow-up-automation rules are genuinely good work — but because it was built to solve a different problem: many tenants, many staff members, centrally managed, server-resident data, integrated into a larger multi-module SaaS platform. This product's actual problem is one person, one device, zero accounts, data that must survive with no server at all. Multi-tenancy, RBAC, a REST API, and token authentication are not simplified versions of what this product needs — they are answers to questions this product doesn't ask. Starting from a blank page and starting from "how do we strip the server out of the existing CRM" would arrive at meaningfully different architectures, and this assessment deliberately took the former path, per the brief's own instruction, precisely to avoid the latter's bias.

> **Which parts of the existing CRM are valuable enough that we should carry them into that new architecture?**

Three things, specifically, and they are the same three things repeated across §1, §7, and §14 because they are genuinely the load-bearing assets: **(1)** the append-only, typed activity-timeline concept — the single design element most directly responsible for this new product's own "customer memory" positioning actually working in practice; **(2)** the follow-up-automation *rules* (auto-schedule the next check-in on creation, after a logged call, after a completed follow-up) — proven, sensible defaults that make the reminder loop feel automatic rather than like homework; and **(3)** the general shape of a configurable, ordered pipeline with a small set of well-validated transition rules (a reason required to mark something lost; no editing history after the fact). Everything else that made the existing system work — the server, the tenancy, the accounts, the API, the framework — belongs to a different product's problem, and correctly does not travel with these three.

---

Implementation has not begun. This document is the product/architecture decision record; a separate, explicit go-ahead is required before any schema, screen, or code is written.
