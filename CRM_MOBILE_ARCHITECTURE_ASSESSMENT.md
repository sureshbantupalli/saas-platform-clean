# CRM Mobile Application — Architecture Assessment & Due-Diligence Report

**Scope:** CRM module (`crm/` app — Enquiry/Lead pipeline) only, plus directly-affecting shared dependencies (auth, identity, RBAC, tenants, shared APIs, notifications, file storage, infrastructure).
**Status:** Assessment only. No code was modified, no migrations created, no APIs changed. Implementation begins only after this document is approved.
**Method:** Every claim below is sourced from the actual repository (file paths and line-level evidence cited inline). Where the repository does not answer a question, it is marked **UNKNOWN / REQUIRES VERIFICATION**.

---

## 1. Executive Summary

The existing CRM ("Enquiry" pipeline) is a **server-rendered Django application with no API surface at all** — not a partially-mobile-ready system, not an API that merely needs hardening. Every CRM screen (`crm/views.py`) returns HTML via Django's template engine; the only non-HTML endpoints are three bare `JsonResponse({"status": "success"})` AJAX handlers used by the Kanban board's drag-and-drop, which carry no data payload, no pagination, no versioning, and no error contract. There is no `serializers.py`, no DRF `ViewSet`, and no `/api/crm/` route anywhere in `config/urls.py`.

This is decisive for the central question the brief poses: **the existing CRM cannot be exposed to a mobile app as-is, under any option.** There is nothing to "expose" — the frontend and the API are the same artifact (server-rendered HTML), and that artifact cannot be consumed by a native mobile client.

However, the news is not uniformly negative. Underneath the missing API layer sits a **genuinely well-designed domain and service layer**: `EnquiryLifecycleService`, `FollowUpService`, and `crm/metrics.py` contain clean, framework-agnostic business logic (lead temperature/priority scoring, stage-transition rules, conversion-to-Member workflow, follow-up automation, dashboard KPIs) that has **zero dependency on Django's template/forms layer** and can be called directly from new DRF views with no rewrite. The platform also already has a proven, working pattern for exactly this kind of API (`members/api.py` + `members/serializers.py` + `apps/core/drf_permissions.py`), used by three other apps (`memberships`, `assessments`, `bookings`) — this is the template the CRM Mobile BFF should follow, not an invention.

Two platform-wide (not CRM-specific) gaps block *any* mobile app, not just CRM: (1) there is no token-based authentication anywhere in the codebase — `REST_FRAMEWORK` has no `DEFAULT_AUTHENTICATION_CLASSES`, so DRF falls back to `SessionAuthentication` + `BasicAuthentication`, neither viable for a production mobile client — and (2) the one existing DRF permission class (`MemberPermission`) checks only view-level module:action permission, never `has_object_permission()`, so the platform's own scope-aware RBAC engine (`RBACService`, which correctly distinguishes `ANY` vs `OWN` scope) is not actually wired into the API layer anywhere yet. Both are inherited by whatever gets built for CRM and must be fixed once, for the whole platform, not per-module.

Within CRM itself, one more concrete authorization gap exists: CRM's views/admin call the coarse `User.has_permission(module, action)` shortcut (`apps/accounts/models.py:152`), not the scope-aware `RBACService.has_permission(user, module, action, obj)` (`apps/authority/services.py:6`). If a tenant ever configures an `OWN`-scoped CRM permission (e.g., "staff may only convert enquiries they created"), it is **silently not enforced** anywhere in CRM today. This must be corrected in the new API layer's permission classes regardless of the mobile initiative, and is flagged here because a due-diligence review would be negligent not to surface it.

**Bottom line:** build a new, clean mobile architecture (Flutter recommended) served by a **new, versioned CRM Mobile API layer** that sits directly on top of the existing service layer and the existing PostgreSQL schema. Reuse the domain logic, the RBAC data model, the database, and the `members/api.py` architectural pattern. Rebuild the API contract, the authentication scheme, and the object-level permission enforcement — none of that exists today for any module, CRM included.

---

## 2. Existing CRM Architecture

### Frontend
- **Framework:** None (no SPA). Server-rendered Django templates (`templates/crm/*.html`, `crm/templates/admin/crm_dashboard.html`) styled with Bootstrap-class conventions (`form-control` classes applied in `crm/forms.py:41`).
- **Routing/navigation:** Django URL dispatcher (`crm/urls.py`), server-side redirects (`redirect("crm:enquiry_list")`), no client-side router.
- **State management:** None — request/response, Django `messages` framework for flash messages, no client-side state store.
- **Component architecture:** Django class-based generic views (`ListView`, `DetailView`, `CreateView`, `UpdateView`, `TemplateView`) — a page-per-view MPA model, not componentized.
- **API consumption:** N/A — templates render server-computed context directly. The only client→server async calls are three plain `fetch`/AJAX POSTs to Kanban helper endpoints (`update-stage/`, `quick-call`, `quick-followup`), each returning a one-key JSON status blob (`crm/views.py:639-800`).
- **Business logic in frontend:** None of substance — `EnquiryForm` (`crm/forms.py`) does field-level Django form validation server-side; no client-side validation logic exists.
- **Validation:** Server-side only, via Django `ModelForm.clean_*` methods and model `clean()`.
- **Authentication handling:** `LoginRequiredMixin` / `@login_required` (Django session-cookie auth) on every view.
- **Authorization handling:** Ad hoc per-view checks (`user.has_permission("CRM", "manage_enquiries")`, `user.is_platform_admin`) — see §14.
- **Offline behavior:** None. No service worker, no local storage strategy, no client caching beyond the browser's own HTTP cache.
- **File handling:** None. `Enquiry` has no `FileField`/`ImageField`; no upload UI exists anywhere in the CRM templates.
- **Notifications:** None client-side (no toast/push/websocket). Server-side `django.contrib.messages` flash messages only, rendered on next page load.
- **Web-specific assumptions:** Full-page reloads for nearly every mutation (assign, stage change via dropdown, add note, mark lost); Kanban drag-and-drop assumes a mouse-pointer DOM API — **not touch-portable as implemented** (see §13).

### Backend
- **Framework:** Django 6 (per root `CLAUDE.md`), function- and class-based views, no DRF anywhere in `crm/`.
- **Architecture pattern:** Fat-model-plus-service-layer hybrid. Some business logic lives correctly in `crm/services/` (`EnquiryLifecycleService`, `FollowUpService`, `enquiry_guard_service.ensure_enquiry_not_converted`); some lives in the model itself (`Enquiry.save()` auto-schedules a follow-up and writes `EnquiryActivity` — `crm/models.py:359-409`); some lives in the view (`EnquiryCreateView.form_valid` assigns tenant/branch and handles the duplicate-phone `IntegrityError` — `crm/views.py:412-460`).
- **Controllers/routes:** `crm/views.py` (11 view classes + 6 function views), `crm/urls.py` (16 routes), `crm/admin.py` (a parallel Django-admin management surface with its own conversion endpoint, `crm/admin.py:235-301`).
- **Services:** `crm/services/enquiry_lifecycle_service.py` (stage changes, call logging, lost-marking), `crm/services/followup_service.py` (follow-up CRUD/state, overdue-sweep, queue sections), `crm/services/enquiry_guard_service.py` (one guard function), `crm/metrics.py` (dashboard/KPI aggregation), `crm/handlers.py` (cross-module Django signal receivers — see below).
- **Domain/business logic:** Lead temperature (`hot`/`warm`/`cold` from `next_followup_date`, `crm/models.py:226-240`), lead priority scoring (`crm/models.py:260-285`), stage-transition validation (loss stage requires a reason; conversion stage requires a phone; stage is immutable after conversion — `crm/models.py:291-312`), atomic Enquiry→Member conversion (`crm/models.py:318-353`).
- **Repository/data-access layer:** None distinct — Django ORM used directly in views/services/model methods; no repository abstraction.
- **Authentication:** Django session auth (cookie-based), shared with the whole platform.
- **Authorization:** `RolePermission`/`PermissionAction` RBAC data model (shared platform asset, `apps/authority/models.py`), consumed by CRM via the coarse `User.has_permission()` shortcut rather than the scope-aware `RBACService` (see §14 for the concrete gap).
- **RBAC/permissions:** Module string used is `"CRM"` (`crm/views.py:336`, `:383`, `:566`) — actions observed: `manage_enquiries`, `convert_enquiry`. **No corresponding `PermissionAction` seed data was located in this scan; confirming these two actions are actually seeded is UNKNOWN / REQUIRES VERIFICATION** (check `apps/core/management/commands/seed_permissions.py`).
- **Validation:** `EnquiryForm.clean_phone` (hard block on duplicate phone per tenant), `clean_email` (soft warning on duplicate email, stored as `self.duplicate_email_warning` and surfaced via `messages.warning` — `crm/forms.py:78-121`); model-level `clean()` re-validates stage-transition rules independent of the form (defense in depth, `crm/models.py:291-312`).
- **API design:** None exists.
- **Error handling:** Django `messages` framework + form re-render on validation failure; `IntegrityError`/`ValidationError` caught explicitly around conversion and creation (`crm/views.py:432-440`, `600-607`).
- **Logging:** `logging.getLogger("crm.followup")` and `logging.getLogger("crm.handlers")` used in the service/handler layers with `logger.info`/`logger.exception` — reasonable practice. **One bare `except Exception: pass` exists in `Enquiry.save()`** around the auto-follow-up creation (`crm/models.py:384-396`) — silently swallows any failure with zero log line, unlike the handlers' correct pattern.
- **Notifications:** None *from* CRM directly (no email/SMS/WhatsApp sent on lead creation, stage change, or follow-up-due today, as far as `crm/` itself is concerned). CRM *consumes* other apps' events (see Signals, below) but does not itself emit into `apps/communications`.
- **Background jobs:** `FollowUpService.mark_overdue_as_missed(tenant=None)` is designed to run tenant-wide from a management command or cron (`crm/services/followup_service.py:113-128`), but it is presently invoked **inline, synchronously, on every `follow_up_queue` page view** (`crm/views.py:807-829`) rather than from a scheduled job — a request-time side effect that will grow slower as `FollowUp` rows accumulate. **No dedicated management command for this sweep exists in `crm/management/`** — the only management command found is `seed_crm_stages.py`.
- **File/document handling:** None (confirmed — no `FileField` on any CRM model, and `apps/documents` is an unrelated billing-document (invoice/quotation/receipt) subsystem with no relationship to `Enquiry` — see §3).
- **Integrations:** None external (no email/SMS provider called from CRM directly).
- **CRM-specific workflows:** Enquiry capture → stage progression (Kanban or dropdown) → follow-up scheduling/logging → conversion to `Member` (atomic, audited, one-way) → downstream membership assignment, optionally routed through an active intake form (`crm/views.py:584-599`, integrating with `apps/intake`).

### Signals — Cross-Module Event Integration (a real asset)
`crm/handlers.py` subscribes to three platform-wide Django signals defined in *other* apps and reacts by auto-creating follow-ups:
- `apps.payments.signals.payment_failed` → same-day recovery call follow-up
- `apps.bookings.signals.booking_confirmed` → next-day post-session check-in follow-up
- `apps.bookings.signals.session_missed` → same-day re-engagement follow-up

This is genuinely good architecture: loosely coupled (CRM doesn't know how payments/bookings work, just reacts to named events), defensively wrapped (`except Exception: logger.exception(...)`, never lets a follow-up-creation failure break the triggering payment/booking flow), and correctly uses `Membership.base_objects` (not `.objects`) inside `_resolve_member_from_payment`, which runs outside the request/response cycle (`crm/handlers.py:21-30`) — i.e., this one file *does* correctly follow the root `CLAUDE.md` manager-usage rule, unlike the CRM views/forms which manually re-implement tenant filtering because CRM's own models predate `TenantAwareModel` (see §10).

### Database
See §10 for the full reusability read; summarized here for completeness.
- **CRM-related tables/entities:** `LeadStage`, `EnquirySource`, `EnquiryLostReason`, `Enquiry`, `EnquiryActivity`, `FollowUp` (`crm/models.py`).
- **Relationships:** `Enquiry` → `Tenant`, `Branch`, `EnquirySource` (nullable), `LeadStage` (nullable, `PROTECT`), `User` (`assigned_to`, `created_by`, both nullable `SET_NULL`), `EnquiryLostReason` (nullable), `Member` (`converted_member`, one-to-one, nullable). `FollowUp` → `Enquiry` *or* `Member` (either, both nullable — a genuine polymorphic-lite design for pre/post-conversion follow-ups, `crm/models.py:504-518`). `EnquiryActivity` → `Enquiry` (cascade), immutable audit rows.
- **Primary/foreign keys:** All CRM models use Django's default auto-increment integer PK. `Member` (the conversion target) uses a `UUIDField` PK (`members/models.py:13`) — an inconsistency worth noting for API design (see §14).
- **Data ownership:** Each row carries an explicit `tenant` FK; multi-tenancy is enforced by manual `.filter(tenant=...)` at every call site rather than by an automatic manager (see §10).
- **Constraints:** `unique_together` on `(tenant, name)` for `LeadStage`/`EnquirySource`/`EnquiryLostReason`; a named `UniqueConstraint` on `(tenant, phone)` for `Enquiry` (`crm/models.py:210-215`) — enforced at the DB level, which is why `IntegrityError` is caught explicitly in the view.
- **Audit fields:** `created_at`/`updated_at` on every model; a dedicated append-only `EnquiryActivity` audit-trail model with 11 typed action kinds (`crm/models.py:417-429`) — this *is* the audit trail, and it is a strong one.
- **Soft deletion:** **None.** No `is_deleted` field anywhere in `crm/models.py`. Records can be hard-deleted via Django admin's default delete action or `.delete()`, which would cascade-delete `EnquiryActivity`/`FollowUp` history for that enquiry. This is a genuine gap relative to the root `CLAUDE.md`'s stated platform-wide "never hard-deletes tenant data" principle.
- **Status/state models:** `LeadStage` is tenant-configurable data (not a hardcoded enum), with `is_conversion_stage`/`is_loss_stage` boolean flags enforced to be mutually exclusive and unique-per-tenant in `clean()` (`crm/models.py:58-85`) — a well-designed configurable state machine.
- **CRM-specific business rules:** Enumerated in "Domain/business logic" above.
- **Stored procedures/functions/triggers:** None found. All business logic is in Python (model methods, services), not the database.
- **Migration count/maturity:** 7 migrations (`crm/migrations/0001`–`0007`), the most recent two being additive field changes (`stage_type`, `show_in_pipeline` — commented `# NEW FIELD (Safe addition)` in the model itself, `crm/models.py:31-42`), suggesting active, careful, backward-compatible iteration rather than a frozen legacy schema.
- **Suitability for API/mobile consumption:** Structurally sound (proper FKs, indexes on `phone`/`created_at`, real constraints) but **not yet API-shaped** — integer PKs invite enumeration, no soft-delete means a mobile client's local cache could reference a row that vanished without a tombstone, and the `FollowUp.member`/`FollowUp.enquiry` either-or pattern needs an explicit discriminator in any API contract (`display_name`/`phone` properties already resolve this politely at the Python level, `crm/models.py:546-560` — genuinely reusable as-is for JSON shaping).

### API Layer
Answered directly and unambiguously by inspecting `config/urls.py` and `crm/urls.py`:
- **Whether proper APIs already exist:** **No.**
- **API architecture:** N/A.
- **REST/GraphQL/etc.:** N/A — three bare `JsonResponse` endpoints exist (`crm/views.py:639-800`) but do not constitute an API (no resource representation, no content negotiation, no error schema).
- **Authentication mechanism:** Session cookie (web-only).
- **Authorization model:** Same ad hoc per-view checks as the HTML views.
- **API versioning:** N/A. (Platform-wide: the existing `/api/` mount for `members`/`memberships`/`assessments` is also unversioned — `config/urls.py:154-157`.)
- **Pagination, filtering, sorting, search:** Present in the HTML `ListView` only (`EnquiryListView.get_queryset`, `crm/views.py:193-218` — `stage`, `assigned`, `search` query params, Django's `paginate_by = 10`); none of this exists as JSON.
- **Validation, error contracts, response consistency, idempotency, rate limiting:** N/A — nothing to evaluate.
- **File upload/download:** N/A — no file handling in CRM at all.
- **Notification/event mechanism:** CRM *consumes* Django signals from other apps (see above) but exposes none of its own for external consumption.

---

## 3. Existing CRM Dependency Map

```text
crm/
 ├─ models.py ──────────────► core.Tenant, core.Branch, members.Member, AUTH_USER_MODEL
 ├─ services/
 │   ├─ enquiry_lifecycle_service.py ─► crm.models only (pure)
 │   ├─ enquiry_guard_service.py ─────► crm.models only (pure)
 │   └─ followup_service.py ──────────► crm.models only (pure)
 ├─ metrics.py ─────────────► crm.models only (pure)
 ├─ handlers.py ────────────► apps.payments.signals/models, apps.bookings.signals/models,
 │                              apps.memberships.models (Membership.base_objects)
 ├─ views.py ───────────────► apps.core.models.Branch, apps.intake.services.form_service,
 │                              django.contrib.auth.get_user_model()
 ├─ forms.py ───────────────► crm.models only
 └─ admin.py ───────────────► apps.core.models.Tenant, crm.metrics

Shared platform dependencies (in explicit assessment scope):
 apps/accounts   → custom User model (email auth), tenant/role FKs, has_permission() shortcut
 apps/authority  → Role, RolePermission, PermissionAction, RBACService (scope-aware, NOT used by CRM)
 apps/tenants    → Tenant provisioning/invites (CRM only references core.Tenant, not this app directly)
 apps/core       → TenantAwareModel, TenantManager, TenantMiddleware, drf_permissions.py, Branch
 apps/documents  → billing documents (invoice/quotation/receipt) — UNRELATED to CRM, no FK to Enquiry
 apps/communications → multi-channel notification engine (email/SMS/WhatsApp/phone adapters,
                        retry/rate-limit services) — NOT currently invoked by CRM, but the
                        natural integration point for future push notifications
 members/        → Member model (conversion target), members/api.py (existing DRF precedent)
```

**Reverse dependency** — one direction worth flagging explicitly: `apps/intake` and the membership-assignment flow both *depend on CRM's conversion outcome* (`crm/views.py:584-599` redirects into `apps.intake` and `membership_add` after conversion). A mobile conversion flow will need to either replicate this hand-off or intentionally scope it out of v1 (see §26).

---

## 4. Target New Mobile CRM Architecture

Designed first, independent of the existing implementation, against the actual shape of this domain: a small-to-mid-size fitness/wellness-business CRM used mainly by front-desk/sales staff to log leads, work a Kanban pipeline, and clear a daily follow-up queue — not a high-volume enterprise sales-ops tool. That sizing matters: it argues against over-building (no need for a bespoke sync engine, no need for GraphQL, no need for a microservices split) and for a lean, maintainable, offline-tolerant client.

### Presentation Layer
- **Component-based, declarative UI** (Flutter widgets or React Native + a modern state-driven UI library — see §11 for the framework decision) — screens: Dashboard/KPIs, Enquiry List (filter/search/sort), Enquiry Detail (timeline + actions), Kanban Pipeline, Follow-Up Queue, Enquiry Create/Edit, Convert-to-Member flow.
- **Navigation:** a declarative, deep-link-capable router (`go_router` in Flutter, or React Navigation in RN) so a push notification ("Follow-up due for Priya Sharma") can deep-link straight into `EnquiryDetail(id)`.

### State Management
- A single **unidirectional, testable state layer** (Riverpod/Bloc in Flutter; Redux Toolkit/Zustand in RN) separating: (a) server-cache state (fetched enquiries/followups, with cache invalidation), (b) UI/ephemeral state (form drafts, filter selections), (c) session state (auth token, current tenant/user, permission set).
- Server-cache state should be backed by a **local persistence layer** (see Data Layer) so cache and offline-queue are the same mechanism, not two parallel systems.

### Domain/Business Layer
- A thin client-side domain layer that mirrors — deliberately, not coincidentally — the server's own service boundaries (`EnquiryLifecycleService`, `FollowUpService`) so the same *names* and *rules* exist on both sides: "can this enquiry be converted," "is this follow-up overdue," "what is this lead's temperature." Rules that are cheap to duplicate for optimistic-UI purposes (e.g., lead temperature coloring) are duplicated; rules with real consequence (e.g., "is this enquiry actually eligible for conversion") are **never** trusted client-side and are always re-validated server-side on the mutating call — the mobile client's copy is UI-affordance only.

### Data/API Client Layer
- A generated or hand-rolled typed API client against the new versioned CRM Mobile API (§8/§14), with a single HTTP layer providing: auth-token attachment and refresh, structured error decoding, retry-with-backoff for idempotent GETs, and a request queue for the offline-write scenarios enumerated in §15.

### Local Persistence / Cache
- An embedded relational store (`drift`/SQLite in Flutter; `WatermelonDB`/SQLite in RN) mirroring the mobile-relevant subset of the server schema: enquiries, followups, lead stages/sources/lost-reasons (small reference tables, fully cacheable), and a local **outbox** table for queued writes made while offline.
- Secure token storage via the platform keystore (`flutter_secure_storage` / iOS Keychain + Android Keystore equivalents in RN) — never `SharedPreferences`/`AsyncStorage` in plaintext.

### Offline Synchronization Strategy
See §15 for full detail. Summary: **read-cache + write-outbox**, not full bidirectional sync. Recently-viewed leads and the follow-up queue are cached for offline browsing; a small, deliberately limited set of high-value mutations (log call, mark follow-up done, add note, change stage) can be queued while offline and replayed on reconnect, with the server's append-only `EnquiryActivity` audit trail as the authoritative conflict resolver (last-write-wins on the mutable fields, but every action is still individually recorded, so nothing is silently lost even under a conflict).

### Push Notification Architecture
- FCM (Android) + APNs via FCM's iOS bridge, or a unified provider (OneSignal) if the team wants to avoid running two native push pipelines. Server-side trigger point: extend `apps/communications`' existing adapter pattern (`apps/communications/adapters/{email,sms,whatsapp,phone}.py`) with a new `push.py` adapter, so push notifications reuse the platform's already-built event schema, rate limiter, and retry service rather than inventing a parallel notification system. New CRM-originated events worth emitting: `enquiry_assigned_to_me`, `followup_due_today`, `followup_overdue`.

### File/Document Handling
- Net-new capability (nothing to reuse — see §3). If/when needed (e.g., photographing an ID or a filled paper enquiry form), use direct-to-object-storage presigned uploads (S3-compatible) referenced from a new `reference_type`/`reference_id` pattern already used elsewhere in this codebase (`FollowUp.reference_type/reference_id`, `apps/documents.Document.reference_type/reference_id`) rather than storing binaries through the Django app server.

### Error Handling
- A single client-side error taxonomy mapped from a **new, consistent API error contract** (see §14) — network, auth-expired (triggers silent refresh, then re-auth), validation (field-level, surfaced inline), permission-denied (distinct from validation — surfaced as a blocking message, never silently retried), server error (retry-with-backoff + user-visible fallback).

### Security Architecture
See §14 in full. Summary of what the target *requires*, independent of what exists today: short-lived access token + longer-lived refresh token (JWT or opaque, via `djangorestframework-simplejwt` — see §14), refresh-token revocation on logout/device-removal, certificate pinning optional (evaluate against MITM threat model for this business category — likely not required for v1, see §26), encrypted local storage for the auth token, no credentials ever cached for repeat Basic-Auth-style calls, object-level permission enforcement on every mutating endpoint (closing the `RBACService` gap identified in §14), and rate limiting on the mobile-facing login/refresh endpoints specifically (login-abuse surface).

### Testing Architecture
- Client: widget/unit tests for domain-layer rules, golden/screenshot tests for key screens, integration tests against a mocked API client.
- Server: **new** API-level test suite (`pytest`, matching root `CLAUDE.md`'s existing test conventions) — CRM currently has **zero** test coverage (`crm/tests.py` is empty, confirmed in §16), so any new API layer must ship with its own tests from day one; there is no existing regression safety net to lean on.

### CI/CD Considerations
- Server-side: standard Django/DRF pipeline already implied by the existing `pytest.ini`/`manage.py test` conventions — add the new CRM API app to the same pipeline, nothing novel required.
- Client-side: Flutter/RN standard CI (Codemagic, Fastlane, or GitHub Actions matrix) for build/test/store-upload — **fully independent of the Django backend's deployment pipeline**, which is itself the correct separation of concerns for a new mobile architecture.

---

## 5. Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     NEW CRM MOBILE APP (Flutter)                     │
│   Presentation → State (Riverpod/Bloc) → Domain → Data/API Client    │
│                 Local cache + outbox (SQLite/drift)                  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │  HTTPS + JWT (access + refresh)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 NEW CRM MOBILE API  (crm/api/, versioned)             │
│  DRF ViewSets · new mobile-shaped serializers · new permission        │
│  classes (view-level + object-level, via RBACService)                 │
└───────┬───────────────────────────────────────┬───────────────────────┘
        │ reused directly, unmodified            │ new, shared platform work
        ▼                                        ▼
┌───────────────────────────┐        ┌─────────────────────────────────┐
│  EXISTING CRM DOMAIN/      │        │  SHARED PLATFORM SERVICES        │
│  SERVICE LAYER (crm/       │        │  · Token auth (new, shared)      │
│  services/*, crm/metrics)  │        │  · RBACService (existing, reused)│
│  — REUSED AS-IS            │        │  · apps.communications (extended │
└───────────┬─────────────────┘        │    with a push adapter)          │
            │                          └─────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│         EXISTING CRM DATABASE (PostgreSQL) — REUSED AS-IS,            │
│         + two additive hardening migrations (soft-delete flag,        │
│         optional public UUID identifier)                              │
└─────────────────────────────────────────────────────────────────────┘

  Existing Django server-rendered CRM UI (templates/crm/*, crm/views.py)
  continues to run UNCHANGED, side-by-side, sharing the same database
  and the same service layer as the new mobile API. Neither depends on
  the other.
```

---

## 6. Existing vs Target Architecture Comparison

| Dimension | Existing CRM | Target Mobile CRM |
|---|---|---|
| Client | Server-rendered HTML (Django templates) | Native/cross-platform app (Flutter) |
| Transport | Full-page HTTP + session cookie | JSON over HTTPS, versioned API |
| Auth | Session cookie + CSRF | JWT access/refresh, secure device storage |
| Authorization | Coarse module:action check (`User.has_permission`) | View-level + object-level (`RBACService`), scope-aware |
| State | None (stateless request/response) | Client-side cache + outbox, server-authoritative |
| Offline | None | Read-cache + queued high-value writes |
| Business logic location | Split across model/service/view | Server-authoritative in existing services; thin client mirror for UX only |
| Notifications | None from CRM | Push, via extended `apps.communications` adapter pattern |
| Versioning | N/A | Explicit `/api/v1/` from day one |
| Test coverage | None | New, mandatory from day one |

---

## 7. Component-by-Component Reuse Matrix

| Existing CRM Component | Reuse Directly | Adapt | Integrate Behind API | Rebuild | Replace | Do Not Reuse | Reason |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| PostgreSQL database/schema | ✅ | | | | | | Sound constraints/relationships; see §10 |
| `Enquiry`, `LeadStage`, `EnquirySource`, `EnquiryLostReason` models | ✅ | | | | | | Pure Django models, framework-agnostic |
| `FollowUp`, `EnquiryActivity` models | ✅ | | | | | | Same |
| `EnquiryLifecycleService` | ✅ | | | | | | Pure Python, no HTTP/template coupling |
| `FollowUpService` | ✅ | | | | | | Same |
| `enquiry_guard_service` | ✅ | | | | | | Same |
| `crm/metrics.py` (dashboard KPIs) | ✅ | | | | | | Pure functions, trivially wrapped by a new endpoint |
| `crm/handlers.py` (cross-module signals) | ✅ | | | | | | Correct, decoupled, already `base_objects`-safe |
| `Enquiry.clean()`/`.save()` business rules | | ✅ | | | | | Logic is right; extraction out of the model into the service layer is a worthwhile *optional* refactor, not a mobile blocker (see §21) |
| `EnquiryForm` (Django `ModelForm`) | | | | | | ✅ | Web-form technical implementation; the *rules inside it* (duplicate phone/email) are reused, the Django Forms mechanism itself is not portable |
| `crm/views.py` (HTML views) | | | | | | ✅ | Template-coupled; superseded by new API views, left running for web use |
| `crm/templates/*.html`, Kanban drag-and-drop JS | | | | | | ✅ | Web-only rendering/interaction model, not applicable to native mobile UI |
| `RolePermission`/`Role`/`PermissionAction` (RBAC data model) | ✅ | | | | | | Tenant-safe (`TenantAwareModel`), scope-aware, framework-agnostic |
| `RBACService.has_permission` | ✅ | | | | | | Already correct and scope-aware — needs to be *wired in*, not rebuilt |
| CRM's own permission checks (`user.has_permission`) | | ✅ | | | | | Coarse; new API permission classes must call `RBACService` with `obj=` instead |
| `apps/core/drf_permissions.py` (`MemberPermission` pattern) | | ✅ | | | | | Right shape, missing `has_object_permission()` — the pattern to extend, not discard |
| `members/api.py` / `members/serializers.py` | | | ✅ | | | | Not CRM's own code, but the direct architectural template for the new CRM API app |
| Django session auth | | | | | | ✅ | Not viable for a native client |
| DRF `BasicAuthentication` fallback | | | | | | ✅ | Security anti-pattern for mobile |
| API layer (JSON contract, pagination, errors, versioning) | | | | ✅ | | | Does not exist for CRM; must be built new |
| Authentication (token/JWT) | | | | ✅ | | | Does not exist platform-wide; must be built once, shared |
| Object-level permission enforcement in the API | | | | ✅ | | | Gap exists platform-wide, not CRM-specific |
| Soft-delete on CRM models | | | | ✅ | | | Genuinely missing; additive migration |
| Push notifications | | | | ✅ | | | Net-new; extend `apps.communications` adapter pattern |
| File/attachment handling | | | | ✅ | | | Net-new; nothing to reuse |
| Automated test coverage for CRM | | | | ✅ | | | `crm/tests.py` is empty — must be written alongside the new API |
| `apps/documents` (billing docs) | | | | | | ✅ (for CRM) | Unrelated subsystem; not a CRM dependency despite superficially similar naming |

---

## 8. CRM Domain Reusability Assessment

**Business/domain assets (high reuse value, framework-independent):**
- Lead lifecycle: New → (configurable pipeline stages) → Converted/Lost, with mutual-exclusivity and per-tenant uniqueness rules on conversion/loss stages.
- Lead temperature/priority scoring algorithm (`crm/models.py:226-285`) — a genuinely useful piece of domain IP, trivially portable to any backend language if ever needed, and directly reusable as Python today.
- Conversion-to-Member workflow, including the business rule that phone is mandatory before conversion and that a converted enquiry becomes immutable (`crm/models.py:291-312`, `318-353`).
- Follow-up automation rules: auto-schedule +1 day on lead creation, +2 days after a logged call, immediate same-day on a missed session or failed payment (`crm/handlers.py`, `crm/services/enquiry_lifecycle_service.py:72-109`).
- The `EnquiryActivity` action taxonomy (11 typed events) — this *is* the CRM's institutional audit vocabulary and should be reused verbatim as the mobile app's activity-timeline data source.

**Technical implementation assets (low/no reuse value, framework-specific):**
- `EnquiryForm` (Django `ModelForm` + Bootstrap widget attrs) — reimplemented as DRF serializer validation.
- Django `messages` flash-message flow — reimplemented as client-side toasts/snackbars driven by API response codes.
- Template-level Kanban drag-and-drop — reimplemented as native touch/drag gestures.
- The three ad hoc `JsonResponse` "mini-endpoints" — superseded entirely by proper resource endpoints.

**Distinction that matters most for effort estimation:** the *rules* are done; the *interfaces* are not. A team scoping this work by "how much of CRM exists" would badly overestimate readiness by counting the service layer; a team scoping it by "does an API exist" would (correctly, per this assessment) conclude almost nothing is reusable. Both views are individually misleading — the accurate read is: **domain logic ≈ 70-80% reusable as-is; delivery mechanism ≈ 0% reusable.**

---

## 9. Backend Reusability Assessment

Reused as-is: `EnquiryLifecycleService`, `FollowUpService`, `enquiry_guard_service`, `crm/metrics.py`, `crm/handlers.py`, and the six CRM models. These require **zero modification** to be called from new DRF views — they take/return plain Python objects and querysets, with no `HttpRequest`, `HttpResponse`, or template dependency anywhere in their signatures.

Not reusable: `crm/views.py` (11 classes + 6 functions) and `crm/admin.py`'s custom conversion endpoint are Django-view/template-coupled and are superseded by new API views. They should **not be deleted** — the existing HTML UI keeps working for desktop/back-office use (see §22) — but they are not the code the mobile app talks to.

Needs rework, not rebuild: the duplicate-phone/duplicate-email validation currently living in `EnquiryForm.clean_phone`/`clean_email` (`crm/forms.py:78-121`) should be **extracted into a small validator function** callable from both the Django form (unchanged, for web) and the new DRF serializer (new, for mobile) — a single source of truth for that specific business rule, rather than reimplementing it twice by hand and risking drift. This is a small, low-risk, high-value refactor (see §21).

One code-quality finding worth fixing regardless of the mobile initiative: the bare `except Exception: pass` in `Enquiry.save()` (`crm/models.py:384-396`) around auto-follow-up creation should at minimum log the exception (matching the pattern already used correctly in `crm/handlers.py`), or a silently-failed auto-follow-up will be invisible to both the web UI and, once built, the mobile app's follow-up queue.

---

## 10. Database Reusability Assessment

**Reuse the existing PostgreSQL schema directly, behind the new API.** No new database, no partial migration, no schema fork. Reasoning:

- The schema's relationships and constraints are correct and would need to be reconstructed identically in any "clean" rebuild — there is no structural defect that argues for starting over. A rebuild would discard real historical `Enquiry`/`EnquiryActivity`/`FollowUp` data for zero architectural gain.
- The multi-tenancy implementation is **not** the platform's standard `TenantAwareModel` pattern — `Enquiry`, `LeadStage`, `EnquirySource`, `EnquiryLostReason`, `EnquiryActivity`, and `FollowUp` all inherit plain `models.Model`, not `TenantAwareModel` (`apps/core/models.py:201`). Every view and service manually threads `tenant=` through each query instead of relying on `TenantManager`'s automatic thread-local filtering. This is consistent with — not contradicted by — the root `CLAUDE.md`'s own disclosure that `crm` and `members` are "root-level apps (predates `apps/` convention, intentional)"; it is known, disclosed legacy positioning, not a hidden defect this assessment discovered. **It is, however, a real risk surface for a new API layer**: every new endpoint must explicitly and correctly filter by the authenticated user's tenant, because the model layer will not do it automatically and will not fail safe if a filter is forgotten (an unscoped `Enquiry.objects.all()` returns *all tenants'* data, not an empty set). This must be a hard code-review gate on every new CRM API view, and is exactly the kind of thing automated tests (currently absent — §16) should pin down permanently.
- `Member` (the conversion target) has the same characteristic — plain `models.Model`, manual tenant filtering — so this is a pattern shared across both apps predating the `apps/` convention, not something isolated to CRM.
- Two **additive, non-breaking** hardening migrations are recommended before/alongside the mobile build, not as a blocker to starting it:
  1. Add `is_deleted` (boolean, default `False`) to `Enquiry`, `FollowUp`, `LeadStage`, `EnquirySource`, `EnquiryLostReason`, mirroring `TenantAwareModel`'s soft-delete convention, so a mobile client's local cache never silently references a row that was hard-deleted server-side.
  2. Add a `public_id` (UUID, indexed, unique) to `Enquiry` for use as the API-facing identifier in place of the sequential integer PK, closing the IDOR-by-enumeration gap noted in §14, while leaving the integer PK in place internally to avoid touching every existing FK. `Member` already demonstrates this UUID-PK pattern platform-wide (`members/models.py:13`), so this is consistent with, not a deviation from, existing platform practice.
- Migrating CRM's models onto `TenantAwareModel` itself (rather than just adding `is_deleted`) is a larger, riskier change (manager semantics change platform-wide for every existing CRM query) and is **not recommended as part of the mobile initiative** — flagged in §26 as a separate, optional future hardening decision, not a mobile-blocking one.

---

## 11. API Reusability Assessment

| Existing CRM "API" surface | Classification |
|---|---|
| `crm/views.py` HTML views | Not applicable — not an API |
| `update-stage/`, `quick-call`, `quick-followup` (`JsonResponse`) | Missing — carries no resource data, cannot be extended into a real endpoint without a rewrite |
| Everything else CRM needs (list/detail/create/update/convert/assign/dashboard/followup-queue) | **Missing** — build new |

**Recommendation: introduce a new, dedicated CRM Mobile API app**, following the exact pattern already proven in this codebase by `members/api.py` + `members/serializers.py`, mounted at a **versioned** path (`/api/v1/crm/...`) — versioning the *whole* `/api/` surface is out of this assessment's CRM-only scope, but the CRM app should not repeat the platform's existing unversioned-`/api/` mistake; if platform-wide versioning is deferred, CRM's own routes should still be prefixed `v1` so it isn't the second module to require a breaking migration later.

Required, in order of dependency:
1. **Token auth** (shared platform work, §14) — nothing else can be meaningfully tested end-to-end without it.
2. **`crm/api/serializers.py`** — new, mobile-shaped (not 1:1 with the Django `ModelForm` field list — e.g., the dashboard/list views want `lead_temperature`/`lead_priority` as computed read-only fields, which the existing model properties already provide for free).
3. **`crm/api/permissions.py`** — new `EnquiryPermission`/`FollowUpPermission` DRF permission classes extending the `MemberPermission` pattern (`apps/core/drf_permissions.py`) with a real `has_object_permission()` implementation that calls `RBACService.has_permission(request.user, "CRM", action, obj=enquiry)`, closing the `OWN`-scope gap identified in §14.
4. **`crm/api/views.py`** — DRF `ModelViewSet`s wrapping `Enquiry`/`FollowUp`, plus explicit action endpoints for `convert`, `assign`, `change-stage`, `log-call`, `schedule-followup`, `mark-followup-done` that call the *existing* service-layer methods directly (`EnquiryLifecycleService.change_stage`, `.log_call`, `FollowUpService.mark_done`, etc.) — this is where the "reuse" in this assessment's central question actually pays off: the mutation logic is one line of delegation to already-correct, already-tested-by-the-web-UI code.
5. **`crm/api/urls.py`**, mounted from `config/urls.py` alongside the existing `crm/` (web) and `members/api.py` (DRF) mounts, matching the platform's own dual-mount convention already used for `bookings`, `attendance`, `intake`, and `payments` (`config/urls.py:169-234`).
6. A dedicated **dashboard/metrics endpoint** that thinly wraps `crm/metrics.py`'s existing pure functions — near-zero new logic.

Pagination: reuse the platform default (`PageNumberPagination`, `PAGE_SIZE=10`, `config/settings/base.py:223-230`) as the baseline, but expect to tune page size per-endpoint for mobile (a Kanban board wants "all active-stage enquiries," not 10-at-a-time; a follow-up queue wants a small page for fast initial paint).

Filtering/search/sorting: the query-param logic already in `EnquiryListView.get_queryset` (`crm/views.py:193-218`) translates directly into DRF `filterset`/`SearchFilter` configuration — the *filter semantics* (stage, assigned-to, name search) are reusable domain knowledge even though the Django `ListView` code itself is not.

Error contracts, idempotency, rate limiting, API observability: **none exist today and must be designed new**, consistent with §14's authentication findings — this is not a CRM-specific gap, it is a first-time API-maturity investment for the platform.

---

## 12. Frontend Reusability Assessment

Strict answer, as instructed: **essentially nothing visual or structural is reusable.**

| Asset | Reusable in mobile? | Why |
|---|:---:|---|
| Visual UI (templates, CSS) | No | HTML/CSS is not a mobile UI toolkit; native/cross-platform widgets are a different rendering model entirely |
| UX flows (screen sequence, what-happens-after-conversion) | **Partially** | The *sequence* (create → work pipeline → convert → hand off to intake/membership) is validated, real-world-tested UX and worth preserving conceptually — but the mobile *flow implementation* is new |
| Business logic embedded in views | Yes, conceptually | Already captured in §8/§9 — the logic is server-side and reusable regardless of frontend |
| Validation | Partially | Rules reusable (see §9's extraction recommendation); Django Forms mechanism is not |
| API clients | No | None exist to reuse |
| State management | No | None exists (stateless MPA) — the mobile app's state layer is a 100% new concern |
| Models/types | Partially | The *shape* of `Enquiry`/`FollowUp`/`LeadStage` (field names, relationships) is worth mirroring 1:1 in the mobile client's local types for conceptual consistency, even though the Python model classes themselves aren't portable |
| Utility functions (lead temperature, priority) | Yes | Model `@property` logic (`crm/models.py:226-285`) is simple enough to reasonably duplicate client-side for instant UI feedback, with the server remaining authoritative |
| Domain rules (stage transitions, conversion eligibility) | Conceptually yes, mechanically no | The *rule* is reused; it must be re-expressed as API validation, never trusted from a mobile client's own copy |

---

## 13. Mobile Gap Analysis

Evaluated against the actual CRM workflows, not a generic mobile checklist:

- **Small screens / touch:** Kanban board's drag-and-drop is currently a desktop-mouse interaction — the mobile equivalent should be a stage-picker action sheet or swipe gesture, not a literal drag-and-drop port. **Relevant.**
- **Camera / photo upload:** Not present today; genuinely useful for a field sales/front-desk context (capturing a walk-in's ID or a paper enquiry card) but is **net-new scope**, not a gap in something that already exists. Recommend as a fast-follow, not MVP (see §26).
- **GPS/location:** No evidence of location-based CRM workflows in the existing system (no branch-proximity lead routing, no check-in-based follow-up). **Not relevant** — do not add merely because it's possible.
- **Push notifications:** High relevance — the follow-up queue (overdue/today/upcoming) is exactly the kind of workflow push notifications exist for. **Recommended, net-new** (§4).
- **Deep links:** A push notification for "follow-up due" should deep-link into that specific `EnquiryDetail` screen — straightforward with the router choice in §4, no blocker.
- **Background processing:** The existing `FollowUpService.mark_overdue_as_missed` sweep currently runs inline on page load (`crm/views.py:807-829`) rather than as a scheduled job — this should be fixed **server-side** (a proper cron/management-command job) regardless of mobile, and the mobile app should never be the thing triggering that sweep as a side effect of opening a screen.
- **Intermittent connectivity / offline access:** Real and relevant for front-desk/gym-floor staff — addressed in depth in §15.
- **Synchronization conflicts:** Bounded by design (§15) — the append-only `EnquiryActivity` audit model already tolerates concurrent writes gracefully, which is a genuine architectural advantage to build the offline strategy around rather than fighting.
- **Secure storage / biometric auth:** New requirement (§4/§14) — nothing to reuse, nothing to migrate away from (no existing mobile app to compare against).
- **Session expiration / app lifecycle:** New concern — token refresh strategy must handle "app was backgrounded for 3 days" gracefully (silent refresh or forced re-login, not a crash).
- **Mobile permissions (camera, notifications):** Standard platform-level asks, only relevant once the corresponding features (photo capture, push) are actually built.
- **Network failures / battery:** Standard mobile engineering discipline, not CRM-specific; the local-cache/outbox design in §15 is what actually protects against this at the architecture level.
- **Large datasets / search performance:** Current tenants appear small-scale (fitness-studio CRM, not an enterprise sales org) — **UNKNOWN / REQUIRES VERIFICATION**: actual production enquiry-volume-per-tenant was not available in this repository scan (no seed/fixture data with realistic volume was inspected). If typical tenants carry low-thousands of enquiries, the existing pagination approach is sufficient; if any tenant is materially larger, this should be re-verified against real data before assuming DB-side pagination alone is enough for a snappy mobile list.

**Deliberately not recommended:** a bespoke conflict-resolution/merge engine, full bidirectional offline sync, or GraphQL — none are justified by this domain's actual complexity, and each would meaningfully increase build and maintenance cost for a CRM this size.

---

## 14. Security Gap Analysis

This is the section with the most consequential, concrete findings. Ordered by severity as they'd affect exposing CRM functionality through a mobile app specifically.

1. **No token-based authentication anywhere in the platform.** `REST_FRAMEWORK` in `config/settings/base.py:223-230` sets no `DEFAULT_AUTHENTICATION_CLASSES`, so DRF's own defaults apply: `SessionAuthentication` and `BasicAuthentication`. Neither is appropriate for a mobile client — session auth requires cookie-jar management and CSRF-token handling that mobile HTTP clients aren't built around, and `BasicAuthentication` implies the client would send raw credentials (base64-encoded, not encrypted by the encoding itself) on every request if ever actually used that way. **No `djangorestframework-simplejwt`, no `rest_framework.authtoken`, no OAuth2 library is present in `requirements.txt`.** This blocks *any* mobile client, not just CRM's — it must be designed and built as shared platform infrastructure (§4, §26 open question on JWT vs. opaque-token choice).
2. **Object-level authorization is not enforced anywhere in the existing DRF layer.** `apps/core/drf_permissions.py`'s `MemberPermission` — the one existing precedent — implements only `has_permission()` (view/method-level), never `has_object_permission()`. This means even the *existing* `members` API cannot currently enforce an `OWN`-scoped `RolePermission` at the object level; it can only gate the endpoint as a whole. This is a platform-wide gap the CRM Mobile API must not inherit uncritically — it should be the first module to close it, using `RBACService.has_permission(user, module, action, obj)` (`apps/authority/services.py`), which already computes the right answer and simply isn't being called from any DRF permission class yet.
3. **CRM's own authorization checks bypass the scope-aware service entirely.** Every permission check in `crm/views.py` and `crm/admin.py` calls `user.has_permission(module, action)` (`apps/accounts/models.py:152-172`), which only checks `RolePermission.objects.filter(..., is_allowed=True).exists()` — it has no `obj` parameter and cannot evaluate `SCOPE_OWN`. Concretely: if a tenant ever grants `CRM:convert_enquiry` with `scope="OWN"` intending "staff may only convert enquiries they personally created," that restriction is **silently never enforced** — any staff member with that permission at any scope can convert any enquiry in the tenant. This is a real, currently-live gap in the web app today, not a hypothetical mobile-only risk, and should be raised as its own finding regardless of the mobile decision. The new CRM Mobile API's permission classes must use `RBACService` correctly from the start (see recommendation in §11).
4. **Sequential integer primary keys on `Enquiry`/`FollowUp`/`LeadStage` invite ID enumeration** (`/api/v1/crm/enquiries/1/`, `/2/`, `/3/`...). Combined with finding #3, a permission misconfiguration would be trivially exploitable by simple ID incrementing. `Member` already demonstrates the platform's own fix for this (UUID PK) — recommended as an additive `public_id` field for `Enquiry` (§10), not necessarily a PK migration.
5. **No rate limiting anywhere observed** (no `django-ratelimit`, no DRF throttle classes configured in `REST_FRAMEWORK` settings). Login/refresh endpoints for the new mobile auth layer are the highest-value target for this and should get explicit throttling from day one — brute-force/credential-stuffing risk is meaningfully higher for a public mobile-app login surface than for a web app fronted by whatever network/WAF controls may already exist for the office-only web UI. **UNKNOWN / REQUIRES VERIFICATION:** whether any WAF/reverse-proxy-level rate limiting exists outside the Django application layer — not visible from the repository alone.
6. **CORS is not configured** (`django-cors-headers` absent from `requirements.txt`). Not a mobile blocker (native HTTP clients aren't subject to browser CORS enforcement) but flagged because it means the current API layer has effectively never been exercised from a separate origin/client at all — a further confirmation that "the API is ready, mobile just needs to consume it" is not an accurate characterization of the current state.
7. **No secrets/credential-storage concern was found specific to CRM** — `Enquiry`/`FollowUp` contain no payment data, no passwords; the sensitive fields are ordinary PII (name, phone, email, notes). Standard mobile secure-storage practice (§4) is sufficient; no CRM-specific encryption-at-rest requirement was identified beyond what any PII-handling app needs.
8. **Debug artifact:** `crm/forms.py:118` contains a stray `print("DEBUG DUPLICATE FOUND:", existing)` — writes to stdout/server logs on every duplicate-email detection, potentially exposing another lead's name/phone into application logs. Minor, but worth removing as part of the validator-extraction refactor in §9.
9. **`.env` is committed to the repository root** (confirmed present via `ls`, `Jul 27 07:18 .env`). **UNKNOWN / REQUIRES VERIFICATION:** whether this file contains real secrets or only local-dev placeholder values — the root `CLAUDE.md` states local dev needs no `.env` at all ("Credentials and settings are hardcoded in `config/settings/base.py` — no `.env` file required for local dev"), which makes the presence of a committed `.env` worth a direct look before any production credential is ever placed in it. This is flagged as a general repository-hygiene item, not evaluated further here as it is outside the CRM-only scope unless it turns out to hold shared-service credentials the mobile backend would also use.

**Net assessment:** existing web security does not automatically make the mobile application secure, and in this specific codebase, the gap is not "mobile needs slightly stricter versions of what exists" — it is "the mobile-relevant security primitives (token auth, object-level authorization, ID-enumeration resistance, rate limiting) do not exist yet at all, for any module." This is expected and normal for a platform whose only client so far has been a browser talking to server-rendered HTML; it is not a CRM-specific failure, and none of it is a reason to distrust the domain logic identified as reusable in §7-9.

---

## 15. Offline / Data Synchronization Assessment

**Recommended scope: read-cache + limited write-outbox. Not full bidirectional sync.**

Justification: this is a small-team CRM (front-desk/sales staff at a single or few-branch fitness business), not a field-sales org with days-long offline stretches or complex multi-party editing of the same record. A heavyweight sync engine (CRDT-based merge, vector clocks, etc.) would cost far more to build and maintain than the actual offline scenario — "spotty wifi/data at the gym for a few minutes" — justifies.

**Read side:** cache the follow-up queue and recently-viewed/recently-assigned enquiries locally (SQLite/drift). On reconnect, refresh silently. Stale-while-revalidate is an appropriate pattern — show cached data immediately, refresh in the background, never block the UI on network for read screens.

**Write side — explicitly bounded to four action types**, chosen because each is a single, small, structurally-independent mutation with a natural existing audit trail entry, not a multi-field edit of a shared record:
1. Log a call (`EnquiryLifecycleService.log_call`)
2. Mark a follow-up done (`FollowUpService.mark_done`)
3. Add a note (`AddEnquiryNoteView`'s underlying `EnquiryActivity.objects.create(action_type="NOTE_ADDED", ...)`)
4. Change stage (`EnquiryLifecycleService.change_stage`)

Each queued action is stored locally with a client-generated idempotency key, replayed in order on reconnect, and reflected optimistically in the UI in the meantime (with a visible "pending sync" indicator — never presented as already-confirmed). **Full enquiry create/edit is *not* queued offline in v1** — creating/editing a lead's core fields (phone/email/name) has real duplicate-detection business rules (§9) that must run server-side against live data; queuing that offline risks exactly the kind of silent-duplicate problem the existing `EnquiryForm` validation exists to prevent. This is a deliberate scope boundary, not an oversight — revisit only if real usage data shows staff frequently need to create leads in a dead-zone (§26 open question).

**Conflict handling:** because `EnquiryActivity` is append-only, two staff logging calls on the same lead while both were briefly offline do not "conflict" in the destructive sense — both activity rows land, both are visible in the timeline, nothing is lost. The only field with real last-write-wins exposure is `current_stage` (if two people change stage offline before either syncs) — acceptable, low-frequency risk for this domain, resolved as last-write-wins with the losing write still visible in the activity log as a "STAGE_CHANGED" entry that was subsequently overridden, so it's auditable even if not both applied.

**What is explicitly out of scope for v1, and why:** full offline creation of new enquiries (duplicate-detection risk, above); offline conversion-to-Member (a `Member` creation + downstream intake/membership hand-off is too consequential and too cross-module to safely queue); any merge UI for conflicting edits (the domain's actual conflict frequency doesn't justify building one).

---

## 16. Architecture Options

### Option A — New mobile frontend + existing CRM APIs/backend
**Not viable as stated.** There are no existing CRM APIs to sit on (§11). Included for completeness of scoring only.

### Option B — New mobile frontend + API modernization/adaptation layer + existing CRM backend
A thin adaptation/BFF layer wrapping the existing Django views' *logic* without a proper resource-oriented redesign (e.g., an adapter that scrapes/reshapes template context into JSON). **Not recommended** — the existing views are template-coupled specifically because they return `HttpResponse`/`render()`; "adapting" them is functionally equivalent to a rewrite, just a messier one, and it would carry forward the coarse permission checks (§14 finding #3) without a clean point to fix them.

### Option C — New mobile frontend + partially reused CRM domain/backend + redesigned API layer
**Recommended.** New DRF `ViewSet`s/serializers/permission classes, calling the *existing, unmodified* `EnquiryLifecycleService`/`FollowUpService`/`crm/metrics.py` directly. This is the option that actually reflects what the evidence supports: the domain layer is reusable, the delivery layer is not.

### Option D — New mobile frontend + substantially rebuilt CRM backend
Not justified. Nothing found in this scan indicates the domain/service layer is wrong or unsound — only that its *delivery mechanism* (HTML) doesn't fit mobile. Rebuilding the service layer would discard working, if untested, business logic for no evidenced benefit.

### Option E — Completely new CRM mobile stack while selectively migrating existing CRM data/business rules
A more extreme version of Option C where the database itself is also forked/migrated rather than reused live. **Not recommended** — §10 already establishes the schema is sound; a data migration introduces real risk (historical `EnquiryActivity` integrity, in-flight `FollowUp` rows) for no architectural gain, and would leave the existing web UI and the new mobile app reading from two different sources of truth, which is a worse outcome than the manual-tenant-filtering risk it would be trying to avoid.

---

## 17. Option Scoring Matrix

Scored 1 (poor) – 5 (excellent) against this specific CRM, not in the abstract.

| Criterion | A | B | C | D | E |
|---|:---:|:---:|:---:|:---:|:---:|
| Reusability of proven domain logic | 1 | 3 | 5 | 2 | 3 |
| Development effort (lower effort = higher score) | 1 (impossible) | 3 | 4 | 2 | 2 |
| Time to market | 1 | 3 | 4 | 2 | 2 |
| Technical debt introduced | 1 | 2 | 4 | 3 | 3 |
| Long-term maintainability | 1 | 2 | 5 | 3 | 3 |
| Security (ease of closing §14 gaps cleanly) | 1 | 2 | 5 | 4 | 4 |
| Performance (mobile-shaped payloads) | 1 | 2 | 5 | 4 | 4 |
| Scalability | 1 | 2 | 4 | 4 | 4 |
| Mobile suitability | 1 | 2 | 5 | 4 | 4 |
| Testability (clean seams to test against) | 1 | 2 | 5 | 3 | 3 |
| Operational complexity (lower complexity = higher score) | 1 | 3 | 4 | 2 | 2 |
| Migration risk (lower risk = higher score) | 5 (nothing to migrate) | 4 | 5 | 3 | 1 |
| Future extensibility | 1 | 2 | 5 | 4 | 3 |
| **Total (of 65)** | **17** | **32** | **60** | **40** | **38** |

**Option C is the clear, evidence-supported winner** — not by a narrow margin, and not because it was assumed going in (§4's target architecture was defined before this comparison, per the brief's own required process).

---

## 18. Recommended Architecture

**Option C**, concretely:

- **Keep, unmodified:** the PostgreSQL database and schema; `crm/models.py`; `crm/services/*`; `crm/metrics.py`; `crm/handlers.py`; `RolePermission`/`Role`/`PermissionAction`/`RBACService`.
- **Keep, running side-by-side, unmodified:** `crm/views.py`, `crm/urls.py`, `templates/crm/*` — the existing web/back-office CRM continues to serve desktop users exactly as today.
- **Add, additive-only migrations:** `is_deleted` on the six CRM models; `public_id` (UUID) on `Enquiry`.
- **Build new:** `crm/api/` (serializers, permissions, views, urls) mounted at a versioned path; a shared platform token-auth scheme (JWT, via `djangorestframework-simplejwt` — see §26 for the specific-library decision, which is a shared-platform choice, not a CRM-only one); a `push.py` adapter extending `apps/communications`; a small validator-extraction refactor so duplicate-phone/email rules are called from both the Django form and the new serializer; a CRM API test suite (currently absent entirely).
- **Build new, client-side:** the Flutter (recommended, §11 for justification) mobile app itself, per the target architecture in §4.

---

## 19. What to Reuse
- Database schema and all six CRM tables' data (§10)
- `EnquiryLifecycleService`, `FollowUpService`, `enquiry_guard_service`, `crm/metrics.py` (§7-9)
- `crm/handlers.py`'s cross-module signal integration (§2)
- `RolePermission`/`Role`/`PermissionAction` data model and `RBACService.has_permission` (§14)
- The `members/api.py` + `apps/core/drf_permissions.py` architectural pattern as the template for the new CRM API (§11)
- Lead temperature/priority scoring logic and the `EnquiryActivity` action taxonomy (§8)
- The existing filter/search semantics in `EnquiryListView.get_queryset` (translated into DRF filters) (§11)
- The `apps/communications` adapter/event/retry/rate-limit pattern, extended with a push channel (§4)

## 20. What to Adapt
- Duplicate-phone/duplicate-email validation — extract from `EnquiryForm` into a shared validator callable from both the web form and the new serializer (§9)
- `MemberPermission`'s pattern — extend with `has_object_permission()` rather than discard (§11, §14)
- The stage/assigned/search filter query-param semantics from `EnquiryListView` — same logic, new (DRF filterset) mechanism (§11)

## 21. What to Rebuild
- The entire API layer: serializers, permission classes with object-level checks, versioned URLs, error contract, pagination tuning (§11)
- Platform-wide token authentication (shared, not CRM-only) (§14)
- Push notification delivery for CRM events (§4)
- CRM's automated test suite, from zero (§16 target architecture, §14 finding on `crm/tests.py`)
- The Kanban interaction model, as native touch UI rather than a ported drag-and-drop (§13)
- The overdue-follow-up sweep, moved from request-time-inline to a proper scheduled job (§2, flagged for both web and mobile's benefit)

## 22. What to Leave Untouched
- `crm/views.py`, `crm/urls.py`, `templates/crm/*`, `crm/admin.py` — the existing web/back-office CRM UI, which keeps serving desktop staff unchanged and unaffected by any mobile work
- `apps/documents` — confirmed unrelated to CRM (§3), no reason to touch it as part of this initiative
- The core CRM database schema's existing tables and columns (only additive migrations, §10 — nothing renamed or removed)

---

## 23. Migration/Integration Considerations
- The new API layer and the existing web views will run **concurrently against the same database and the same service layer** — this is intentional (§18) and requires no data migration, no dual-write period, and no cutover event. There is no "migration" in the data sense at all, only additive schema changes.
- Any future `is_deleted` field must be respected by the *existing* web views too (they currently have no soft-delete concept and would need a small update to exclude soft-deleted rows from `EnquiryListView`/Kanban/dashboard queries) — a small, low-risk, CRM-only follow-up once the field is added.
- The intake-form and membership-assignment hand-off after conversion (`crm/views.py:584-599`) needs an explicit mobile-app decision: either replicate the redirect chain as a mobile deep-link sequence, or intentionally route "convert to member" completions back to a web hand-off for now (§26 open question) — do not let this be discovered late.

## 24. Risks and Mitigations
| Risk | Mitigation |
|---|---|
| Manual tenant-filtering pattern (§10) means a forgotten `tenant=` filter in a new API view leaks cross-tenant data | Mandatory code-review checklist item + automated tests asserting cross-tenant isolation on every new endpoint, from the first PR |
| Zero existing CRM test coverage means regressions in the reused service layer would go undetected | Write characterization tests for `EnquiryLifecycleService`/`FollowUpService`/`crm/metrics.py` *before* wiring them into new API views, establishing a safety net that also documents current behavior |
| Shared platform auth work (JWT) becomes a bottleneck blocking CRM API development | Sequence it first and treat it as its own short, focused workstream (§25) rather than building it opportunistically inside CRM's own PRs |
| Object-level permission fix, once correctly implemented for CRM, surfaces that some tenants are relying on the current (incorrect) coarse behavior | Audit existing `RolePermission` rows for any `scope=OWN` CRM grants before shipping the corrected check, so a fix doesn't unexpectedly lock staff out of enquiries they were previously (incorrectly) able to touch |
| Offline outbox replay ordering issues (e.g., a queued "mark done" replays after a queued "change stage" that logically should have come first) | Client-side outbox preserves and replays strict chronological order per enquiry; server-side actions are individually idempotent (re-marking an already-done follow-up as done is a no-op, not an error) |
| Scope creep into full offline CRUD or a generic sync engine | §15's explicit, justified scope boundary — revisit only with real usage evidence, not speculatively |

## 25. Recommended Implementation Phases
1. **Shared platform auth** — JWT (or chosen equivalent) issuance/refresh/revocation, wired into DRF settings platform-wide. *(Blocks everything else.)*
2. **CRM API foundation** — `crm/api/` app scaffold, serializers, versioned URL mount, permission classes with real object-level checks, characterization tests for the existing service layer.
3. **Core CRM API endpoints** — enquiry list/detail/create/update, lead-stage/source/lost-reason lookups, dashboard/metrics endpoint.
4. **Workflow endpoints** — convert, assign, change-stage, log-call, schedule-followup, mark-followup-done, add-note — each a thin wrapper over existing service methods.
5. **Additive DB hardening** — `is_deleted`, `public_id` migrations; update existing web views to respect `is_deleted`.
6. **Mobile app shell** — Flutter project scaffold, auth flow, navigation, local persistence layer (schema mirroring the API's read models).
7. **Mobile core screens** — Dashboard, Enquiry List, Enquiry Detail, Follow-Up Queue.
8. **Mobile pipeline/Kanban** — native touch-based stage management.
9. **Offline read-cache + write-outbox** — the four bounded write actions from §15.
10. **Push notifications** — `apps/communications` push adapter + mobile-side FCM/APNs integration + deep linking.
11. **(Fast-follow, not MVP)** Camera/photo capture, if validated by real usage need.

## 26. Open Questions / Unknowns
- **UNKNOWN / REQUIRES VERIFICATION:** Are the `CRM:manage_enquiries` / `CRM:convert_enquiry` `PermissionAction` rows actually seeded today, and for which roles/scopes? — inspect `apps/core/management/commands/seed_permissions.py` and the production `role_permissions` table directly.
- **UNKNOWN / REQUIRES VERIFICATION:** Real production enquiry volume per tenant — determines whether current pagination/list-query performance is sufficient for a mobile list screen or needs further tuning (§13).
- **UNKNOWN / REQUIRES VERIFICATION:** Contents of the committed `.env` file (§14, finding 9) — confirm it holds no live secret before any shared decision is made about how the mobile backend sources its own configuration.
- **Open decision:** JWT (via `djangorestframework-simplejwt`) vs. an opaque server-side token with a `Session`-like revocation table — both are workable; JWT is recommended for statelessness and offline-friendly expiry handling, but this is a genuine platform-level architectural choice that should be made deliberately, not defaulted into.
- **Open decision:** Should offline enquiry *creation* ever be supported (§15 explicitly scopes it out for v1) — revisit with real field-usage data after the app ships, not before.
- **Open decision:** Should the mobile "convert to member" flow replicate the full intake-form/membership-assignment hand-off (§23), or intentionally hand off to a web/desktop flow for that specific step in v1?
- **Open decision:** Push provider — direct FCM+APNs vs. a unified provider (OneSignal) — a build-cost/vendor-dependency tradeoff, not a technical blocker either way.

## 27. Final Go / No-Go Recommendation
**GO** — build the new mobile CRM on Option C. The domain and service layer earn real reuse; the delivery layer (API, auth, object-level authorization) requires genuine new engineering that is not CRM-specific and, once built, benefits every other module the platform later wants to mobile-enable. Nothing found in this assessment constitutes a reason to delay or to rebuild the domain layer from scratch.

---

### RECOMMENDED DECISION

**New Mobile CRM Architecture:**
Yes — new, clean architecture (native/cross-platform client + new versioned API layer), not a wrapper around the existing server-rendered CRM.

**Existing CRM Accommodation:**
Only through an adaptation layer — the domain/service layer and database are reused directly and without modification; the delivery mechanism (views, forms, templates, ad hoc JSON endpoints) is not, and is fully superseded by a new API layer for mobile purposes while continuing to serve the web UI unchanged.

**Existing Database:**
Reused directly via a redesigned API/domain layer, with two additive, non-breaking hardening migrations (`is_deleted`, `public_id`). No new database, no data migration, no fork.

**Existing Backend:**
The service layer (`crm/services/*`, `crm/metrics.py`, `crm/handlers.py`) is reused unmodified. The view/controller layer (`crm/views.py`, `crm/admin.py`'s custom endpoints) is left running for web use but is not the backend the mobile app talks to — a new API layer sits beside it, calling the same services.

**Existing APIs:**
None exist for CRM today; build new. The one existing platform-wide DRF precedent (`members/api.py`) is the architectural template to follow, extended to close its own object-level-permission gap in the process.

**Existing Frontend:**
Left running, unmodified, for desktop/back-office use. Not reused in any form for the mobile client — a full new presentation layer is required.

**Mobile Technology:**
**Flutter**, recommended over React Native, Kotlin Multiplatform, and fully-native Android+iOS. Reasoning: this CRM's actual complexity (list/detail/Kanban/dashboard/follow-up-queue screens, moderate offline needs, push notifications, no heavy native-hardware integration) does not justify KMP's or full-native's higher upfront cost of two native UI codebases; Flutter's single codebase, mature offline-first local-database tooling (`drift`/SQLite), and strong first-class push/background-task plugin ecosystem are a better fit than React Native's JS-bridge architecture for the outbox/local-cache-heavy design in §15, and neither Flutter nor RN has a language-continuity advantage over the other given the backend team's Python/Django background — the deciding factors are the offline-architecture fit and single-codebase delivery speed, both of which favor Flutter for this specific domain.

**Reuse Level:**
Approximately **60-65%** of the CRM module's *engineering value* (domain rules, service-layer logic, database schema, RBAC data model, and the existing API-architectural pattern to follow) carries forward into the new mobile architecture without modification or with only additive changes. This is an architectural estimate of what is *structurally reusable*, not a prediction of development-hours saved — the API layer, authentication, object-level authorization, and the entire mobile client are net-new engineering regardless of this percentage, and typically dominate total build effort for a mobile initiative even when the backend reuse fraction is high.

**Primary Architectural Strategy:**
Build a new, versioned CRM Mobile API (Option C) that calls the CRM module's existing, already-correct service layer directly, sitting on the existing PostgreSQL schema with only additive hardening migrations, secured by new platform-wide token authentication and newly-closed object-level RBAC enforcement, and served to a new Flutter mobile client with a deliberately bounded offline read-cache-plus-write-outbox design — while the existing server-rendered CRM continues to run unchanged for desktop users, sharing the same database and business logic as the new mobile surface.

### TOP 10 ACTIONS BEFORE DEVELOPMENT
1. Verify the `CRM:manage_enquiries`/`CRM:convert_enquiry` permission-action seed data and current tenant role-permission grants (§26) — confirms what the new API's permission classes must actually enforce on day one.
2. Decide the token-auth mechanism (JWT vs. opaque/revocable token) as an explicit platform-level architectural decision, not a default (§26).
3. Audit existing `RolePermission` rows for any `scope=OWN` CRM grants before shipping the corrected object-level permission check, to avoid an unexpected access regression for real users (§24).
4. Write characterization tests for `EnquiryLifecycleService`, `FollowUpService`, and `crm/metrics.py` before wiring them into any new API view — there is currently zero regression protection (§16, §24).
5. Extract duplicate-phone/duplicate-email validation out of `EnquiryForm` into a shared validator usable by both the web form and the new serializer (§9, §20).
6. Remove the debug `print()` in `crm/forms.py:118` and add logging (not silent pass) to the bare `except Exception` in `Enquiry.save()` (§14, §9) — both are quick, low-risk fixes worth doing before they're forgotten.
7. Design the `is_deleted`/`public_id` migrations and update the existing web views to respect `is_deleted` in the same change (§10, §23) — do this once, correctly, rather than twice.
8. Move `FollowUpService.mark_overdue_as_missed` off the request-time-inline trigger onto a real scheduled job (§2, §13) — benefits both the existing web app and the new mobile follow-up queue.
9. Decide the v1 scope boundary for the post-conversion intake/membership hand-off on mobile (§23, §26) — replicate it or intentionally defer to web — before the conversion screen is designed, not after.
10. Confirm the committed `.env` file contains no live secret, and establish how the new mobile-facing services will source their own configuration (§14 finding 9) — a five-minute check that is cheap now and expensive to discover late.
