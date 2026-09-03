# FOUNDATION_EXTRACTION_MATRIX.md

## ANJASI People Platform — Component Reusability Analysis

**Purpose:** Systematically catalog every Django app, service, model, middleware, admin component, and utility to determine what can be extracted from saas-platform-clean for ANJASI People (fully independent product).

**Legend:**
- **COPY AS-IS**: Production-ready, zero business coupling, directly applicable to People Platform
- **COPY & REFACTOR**: Reusable engineering, requires terminology/domain changes for People context
- **DO NOT COPY**: Gym/fitness-specific, no applicability to People Platform

---

## CORE INFRASTRUCTURE LAYER

### ✅ apps/core
**Current Location**: `apps/core/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Base model classes (BaseModel, Tenant, TenantAwareModel, TenantScopedManager, TenantScopedQuerySet, Branch) | COPY AS-IS | Multi-tenancy foundation; zero gym coupling; extensible base classes | Django ORM | Low | 1-2 hrs | Minimal | Copy entire file; Brand = Branch can be renamed for People context |
| **managers/tenant_manager.py** | Tenant-scoped query filtering | COPY AS-IS | Core to multi-tenant isolation; reusable pattern | core.models | Low | 30 min | None | Copy as-is; no refactoring needed |
| **middleware.py** | TenantMiddleware (detects tenant from subdomain) | COPY AS-IS | Critical for routing; domain-agnostic | core.models | Low | 30 min | None | Copy directly; verify subdomain extraction logic |
| **permissions/** | DRF permission classes | COPY AS-IS | API permission enforcement | DRF, authority | Low | 30 min | Low | Copy all; no gym references |
| **services/base_service.py** | Base service class pattern | COPY AS-IS | Reusable service foundation | None | Low | 15 min | None | Copy; document pattern for People services |
| **services/tenant_provision_service.py** | Tenant provisioning logic | COPY & REFACTOR | Framework is reusable; references old CRM LeadStage defaults | core.models, crm | Medium | 2-3 hrs | Medium | Extract provisioning logic; replace default stage creation with People-appropriate stages |
| **admin_base.py** | TenantScopedAdmin base class | COPY AS-IS | Admin filtering/scoping; reusable pattern | core.models | Low | 30 min | None | Copy directly |
| **platform.py** | Platform detection utilities | COPY AS-IS | Distinguishes platform vs tenant accounts | core.models | Low | 15 min | None | Copy; platform tenant concept is valuable for People |

---

## AUTHENTICATION & AUTHORIZATION LAYER

### ✅ apps/accounts
**Current Location**: `apps/accounts/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Custom User model (email-based, tenant + role association) | COPY AS-IS | Production-grade auth model; tenancy-aware; no gym coupling | Django auth, core, authority | Medium | 1 hr | Minimal | Copy directly; already ANJASI-branded |
| **admin.py** | Django admin customizations | COPY AS-IS | Admin interface; non-gym-specific | accounts.models | Low | 30 min | None | Copy directly |
| **services/member_service.py** | User creation/management utilities | COPY & REFACTOR | Framework is sound; "member" → "employee"/"person" renaming needed | accounts.models | Low | 30 min | Low | Rename references; core logic reusable |
| **forms.py** | Auth forms (currently minimal) | COPY AS-IS | Generic auth forms | accounts.models | Low | 15 min | None | Copy; add People-specific forms as needed |
| **views.py** | Login/logout (basic views) | COPY & REFACTOR | Framework works; may need People-specific redirect logic | accounts.models | Low | 30 min | Low | Copy; verify redirect destinations |

### ✅ apps/authority
**Current Location**: `apps/authority/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | RBAC: PermissionAction, Role, RolePermission | COPY AS-IS | Enterprise-grade RBAC; no domain coupling; perfectly reusable | core.models, django.contrib.auth | Medium | 1 hr | Minimal | Copy directly; permission matrix is extensible |
| **services.py** | Permission query helpers | COPY AS-IS | Utility functions; domain-agnostic | authority.models | Low | 15 min | None | Copy directly |
| **views.py** | RBAC admin interface | COPY AS-IS | Role/permission management UI | authority.models | Low | 30 min | Low | Copy; test against People permission matrix |
| **decorators.py** | @requires_permission decorator | COPY AS-IS | View-level permission checks | authority.models | Low | 15 min | None | Copy directly |
| **templatetags/** | Permission check template tags | COPY AS-IS | Template-layer permission checks | authority.models | Low | 15 min | None | Copy directly |

### ✅ apps/tenants
**Current Location**: `apps/tenants/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Tenant model (already in core, duplicated here) | COPY AS-IS | Tenant management; multi-tenant SaaS foundation | core.models | Low | 30 min | None | Verify no duplication; consolidate if needed |
| **invite_service.py** | Tenant invitation tokens + onboarding | COPY AS-IS | Reusable invitation framework; secure token handling | tenants.models | Medium | 2 hrs | Low | Copy directly; supports People onboarding perfectly |
| **services.py** | Tenant CRUD operations | COPY AS-IS | Tenant lifecycle; domain-agnostic | core.models | Low | 30 min | None | Copy directly |
| **management/commands/ensure_platform_tenant.py** | Platform tenant setup | COPY AS-IS | Initial deployment setup | tenants.models | Low | 15 min | None | Copy; customize for People |
| **management/commands/provision_tenant.py** | Tenant provisioning CLI | COPY AS-IS | Deployment automation | tenants.models | Low | 30 min | None | Copy; may need People-specific defaults |
| **views.py** | Tenant invite acceptance, onboarding flow | COPY & REFACTOR | Flow is sound; UI/copy needs People branding | tenants.models, accounts.models | Medium | 2 hrs | Low | Copy; customize copy/UX for People context |

### ✅ apps/audit
**Current Location**: `apps/audit/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | AuditLog model (event tracking) | COPY AS-IS | Immutable audit trail; no domain coupling; compliance critical | core.models | Low | 30 min | None | Copy directly |
| **services.py** | Audit event recording, timeline generation | COPY AS-IS | Event logging framework; generic hooks | audit.models, core.models | Medium | 1-2 hrs | Minimal | Copy directly; event types are configurable |
| **explain_service.py** | AI-powered event explanation | COPY AS-IS | LLM-based audit summarization; reusable | audit.models | Medium | 1 hr | Low | Copy; may need People-specific context for better explanations |
| **timeline_service.py** | Timeline serialization | COPY AS-IS | Event timeline presentation | audit.models | Low | 30 min | None | Copy directly |
| **views.py** | Audit timeline UI | COPY AS-IS | Read-only audit interface | audit.models | Low | 30 min | None | Copy; customize branding |
| **tests_*** | Extensive audit test suite | COPY AS-IS | Quality assurance; reusable test patterns | audit.* | Medium | N/A | None | Copy for testing framework |

---

## COMMUNICATION & NOTIFICATIONS LAYER

### ✅ apps/communications
**Current Location**: `apps/communications/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | MessageTemplate, TriggerRule, CommunicationLog, MessagingProvider | COPY AS-IS | Event-driven message system; uses generic {{placeholders}}; zero gym coupling | core.models | Medium | 1 hr | Minimal | Copy directly; placeholder system supports any event type |
| **services/communication_service.py** | Message send/retry orchestration | COPY AS-IS | Robust message delivery; multi-channel (SMS/WhatsApp/Email); reusable | payments.utils.encryption, requests | Medium | 2 hrs | Low | Copy directly; event_type is configurable string |
| **services/messaging_config_service.py** | Provider configuration (MSG91, Razorpay, etc.) | COPY & REFACTOR | Framework reusable; may need People-specific integrations | core.models | Medium | 2 hrs | Medium | Copy; add/remove providers per People architecture |
| **services/retry_service.py** | Failed message retry logic | COPY AS-IS | Exponential backoff; domain-agnostic | communication_service | Low | 1 hr | None | Copy directly |
| **services/rate_limiter.py** | Message rate limiting | COPY AS-IS | Prevent spam; configurable per channel | core.models | Low | 30 min | None | Copy directly |
| **services/event_schema.py** | Event structure definitions | COPY & REFACTOR | Schema validation; currently lists gym events ("payment_success", "booking_confirmed") | None | Low | 30 min | Low | Copy; replace event types with People equivalents (e.g., "onboarding_complete", "assessment_passed") |
| **management/commands/seed_platform_comms.py** | Default message templates seeding | COPY & REFACTOR | Framework is sound; templates are gym-specific | communications.models | Low | 30 min | Low | Copy; replace default templates with People onboarding/engagement messages |
| **management/commands/seed_comms_defaults.py** | Per-tenant template defaults | COPY & REFACTOR | Seeding logic reusable; content is gym-specific | communications.models | Low | 30 min | Low | Copy; customize for People |
| **management/commands/retry_failed_messages.py** | Scheduled message retry | COPY AS-IS | Cron-friendly retry loop | communication_service | Low | 15 min | None | Copy directly |
| **views.py** | Message template management UI | COPY & REFACTOR | Admin interface works; UX assumes gym context | communications.models | Medium | 2 hrs | Low | Copy; redesign UX for People messaging events |

---

## ASSESSMENT & TRAINING LAYER

### ✅ apps/assessments
**Current Location**: `apps/assessments/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Assessment, Question, QuestionOption, StudentAssessment, AssessmentAttempt, AttemptAnswer, AssessmentScore, CertificateTemplate | COPY AS-IS | Educational/training assessment framework; zero fitness coupling; highly reusable for People training/onboarding | core.models, members.Member | High | 3 hrs | Minimal | Copy directly; framework supports any assessment domain |
| **services/assessment_service.py** | Assessment CRUD, filtering, scoping | COPY AS-IS | Core assessment logic | assessments.models | Medium | 1 hr | None | Copy directly |
| **services/question_service.py** | Question management | COPY AS-IS | Generic question handling | assessments.models | Low | 30 min | None | Copy directly |
| **services/attempt_service.py** | Student attempt creation/grading | COPY AS-IS | Assessment attempt tracking | assessments.models | Medium | 1-2 hrs | Low | Copy directly; grading rules configurable |
| **services/certificate_service.py** | Certificate generation | COPY AS-IS | Post-assessment credential; highly reusable | assessments.models | Medium | 1-2 hrs | Low | Copy directly; supports People achievement tracking |
| **services/grading_service.py** | Automatic grading logic | COPY AS-IS | Configurable scoring | assessments.models | Medium | 1-2 hrs | Low | Copy directly; rule engine is extensible |
| **views.py** | Assessment UI/API endpoints | COPY & REFACTOR | Architecture is solid; field labels/copy are yoga-specific | assessments.models | Medium | 2-3 hrs | Medium | Copy; test against People assessment flow; update labels |
| **management/commands/** | Assessment data seeding | COPY & REFACTOR | Seeding framework reusable; example data is yoga-specific | assessments.models | Low | 1 hr | Low | Copy; replace with People assessment examples |
| **Extensive tests** | 20k+ lines of test coverage | COPY AS-IS | High quality; excellent examples | assessments.* | High | N/A | None | Copy; provides testing patterns |

---

## ENROLLMENT & PARTICIPATION LAYER

### ✅ apps/enrollments
**Current Location**: `apps/enrollments/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Enrollment (person in service/vertical; status tracking) | COPY AS-IS | Generic participation model; no domain-specific fields | core.models, members.Member, catalog.Service, verticals.BusinessVertical | Low | 30 min | None | Copy directly; perfect for People employee/participant tracking |
| **services/enrollment_service.py** | Enrollment CRUD, state transitions | COPY AS-IS | Lifecycle management; reusable patterns | enrollments.models | Low | 30 min | None | Copy directly |

### ✅ apps/verticals
**Current Location**: `apps/verticals/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | BusinessVertical (tenant-defined business line slugs) | COPY AS-IS | Configurable business line framework; zero domain coupling | core.models | Low | 15 min | None | Copy directly; supports People team/department structure |

### ✅ apps/catalog
**Current Location**: `apps/catalog/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Service model (name, description, pricing metadata) | COPY AS-IS | Service/offering framework; generic | core.models, verticals | Low | 30 min | None | Copy directly; supports People program/service catalog |

---

## PAYMENT & FINANCIAL LAYER

### ✅ apps/payments
**Current Location**: `apps/payments/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Payment, Invoice, PaymentTransaction, TenantPaymentConfig | COPY AS-IS | Payment processing infrastructure; generic abstraction | core.models, razorpay | Medium | 2 hrs | Low | Copy directly; provider-agnostic structure |
| **services/payment_service.py** | Payment orchestration | COPY AS-IS | Core payment logic; extensible for new flows | payments.models | Medium | 2 hrs | Low | Copy directly |
| **services/config_service.py** | Provider credential management (encrypted) | COPY AS-IS | Secure credential storage; reusable pattern | cryptography | Low | 1 hr | Minimal | Copy directly; encryption is production-ready |
| **gateways/** | Provider integrations (Razorpay, etc.) | COPY & REFACTOR | Payment gateway abstraction is sound; Razorpay-specific code may need audit for People requirements | razorpay, requests | High | 3-4 hrs | Medium | Copy gateway abstraction; audit Razorpay assumptions; add/remove providers as needed |
| **utils/encryption.py** | Fernet-based field encryption | COPY AS-IS | Secure sensitive data; reusable | cryptography | Low | 30 min | None | Copy directly; used across system |
| **views.py** | Payment UI (form, confirmation) | COPY & REFACTOR | Form logic is reusable; UX/copy assumes gym context | payments.models | Medium | 2 hrs | Medium | Copy; redesign for People context (employee subscriptions, training fees, etc.) |
| **tests_razorpay.py** | Razorpay integration tests | COPY AS-IS | Excellent mock testing patterns | payments.models | Medium | N/A | None | Copy; provides testing framework |

### ✅ apps/payouts
**Current Location**: `apps/payouts/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Payout tracking model | COPY & REFACTOR | Payout framework is generic; terminology ("commission payout") may not apply to People | core.models | Low | 30 min | Low | Copy models; determine if People platform needs payout features |

---

## DASHBOARD & ANALYTICS LAYER

### ✅ apps/dashboard
**Current Location**: `apps/dashboard/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Dashboard configuration model | COPY AS-IS | Widget registry; extensible framework | core.models | Low | 30 min | None | Copy directly; widget system is domain-agnostic |
| **registry.py** | Widget registry/factory | COPY AS-IS | Widget plugin system | dashboard.models | Medium | 1-2 hrs | Low | Copy directly; supports People dashboard customization |
| **services/widget_service.py** | Widget rendering orchestration | COPY AS-IS | Dashboard composition logic | dashboard.models | Medium | 1-2 hrs | Low | Copy directly |
| **widgets/** | Widget implementations (attendance, revenue, etc.) | DO NOT COPY | All widgets are gym-specific (attendance charts, revenue forecasts) | dashboard.models | N/A | N/A | High | Do NOT copy; replace with People-specific widgets (employee engagement, training progress, etc.) |
| **api/urls.py** | Dashboard API endpoints | COPY AS-IS | API routing; generic | dashboard.* | Low | 15 min | None | Copy directly |
| **views.py** | Dashboard UI | COPY & REFACTOR | Template structure is reusable; content is gym-branded | dashboard.models | Medium | 2-3 hrs | Medium | Copy; redesign for People context |

### ✅ apps/analytics
**Current Location**: `apps/analytics/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **services/dashboard_service.py** | Analytics data aggregation | COPY & REFACTOR | Framework is sound; metrics are gym-specific (class attendance %, revenue trends) | core.models, memberships, sessions | High | 4-5 hrs | Medium | Copy; rewrite metrics for People context (training completion %, engagement scores, skill progression) |
| **views.py** | Analytics UI | COPY & REFACTOR | Template structure reusable; charts/metrics are gym-specific | analytics.services | Medium | 2-3 hrs | Medium | Copy; update for People metrics |
| **tests.py** | Analytics test suite | COPY & REFACTOR | Test patterns reusable; test data is gym-specific | analytics.* | Medium | N/A | None | Copy; update test cases |

### ✅ apps/reporting
**Current Location**: `apps/reporting/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **services.py** | Financial reporting (GST, P&L) | COPY & REFACTOR | Reporting framework is reusable; financial calculations may need People-specific updates | payments.models, core.models | High | 4-5 hrs | Medium | Copy; audit for People financial structure (payroll, invoicing, etc.) |
| **views.py** | Reporting UI | COPY & REFACTOR | Template structure reusable; report types are gym-specific | reporting.services | Medium | 2-3 hrs | Medium | Copy; add/remove report types for People context |
| **tests_realworld.py** | Real data reporting tests | COPY & REFACTOR | Test patterns reusable; data is gym-specific | reporting.* | High | N/A | None | Copy; update test scenarios |

---

## AUTOMATION & LIFECYCLE LAYER

### ✅ apps/lifecycles
**Current Location**: `apps/lifecycles/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | LifecycleRun (batch operation tracking) | COPY AS-IS | Automation framework; tracks scheduled/manual runs; completely generic | core.models | Low | 30 min | None | Copy directly; perfect for People batch automation |
| **services/** | Lifecycle execution logic | COPY AS-IS | Orchestration engine; domain-agnostic | lifecycles.models | Medium | 2 hrs | Low | Copy directly |
| **management/commands/run_lifecycle_updates.py** | Scheduler trigger | COPY AS-IS | Cron-invoked lifecycle executor | lifecycles.models | Low | 30 min | None | Copy directly |

### ✅ apps/actions
**Current Location**: `apps/actions/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **services/next_best_action_service.py** | Recommendation engine (next best action to take) | COPY & REFACTOR | Engine logic is sound; action types are gym-specific ("book session", "renew membership") | core.models, analytics | Medium | 2-3 hrs | Medium | Copy; replace gym actions with People actions (e.g., "complete onboarding", "join team", "attend training") |
| **views.py** | NBA recommendation UI | COPY & REFACTOR | API structure reusable; action copy is gym-specific | next_best_action_service | Medium | 1-2 hrs | Medium | Copy; update for People context |

---

## INTAKE & FORMS LAYER

### ✅ apps/intake
**Current Location**: `apps/intake/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | IntakeForm model (configurable forms) | COPY AS-IS | Generic form builder; no domain coupling | core.models | Medium | 1-2 hrs | Low | Copy directly; perfect for People onboarding/assessment forms |
| **services/form_service.py** | Form rendering, validation, submission | COPY AS-IS | Form workflow engine | intake.models | Medium | 2 hrs | Low | Copy directly |
| **services/prefill_service.py** | Form prefill (auto-populate known fields) | COPY AS-IS | Smart form UX | intake.models | Low | 1 hr | None | Copy directly |
| **views.py** | Form UI (public + authenticated) | COPY & REFACTOR | Template structure reusable; UX may be gym-branded | intake.models | Medium | 2 hrs | Low | Copy; test against People intake flows |
| **api/urls.py** | Form submission API | COPY AS-IS | API routing; generic | intake.models | Low | 15 min | None | Copy directly |

---

## ENGAGEMENT & RETENTION LAYER

### ✅ apps/engagement
**Current Location**: `apps/engagement/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Engagement tracking (signals, actions, retry tracking) | COPY & REFACTOR | Model is reusable; field names ("member_gym_visits") are gym-specific | core.models, members.Member | Medium | 1-2 hrs | Low | Copy; rename fields for People context |
| **services/** | Engagement signal processing | COPY & REFACTOR | Signal framework reusable; triggers are gym-specific (low attendance, no bookings) | engagement.models | Medium | 2-3 hrs | Medium | Copy; replace signals with People equivalents (low training participation, inactive status) |
| **management/commands/run_retries.py** | Retry execution | COPY AS-IS | Generic retry orchestration | engagement.models | Low | 30 min | None | Copy directly |

---

## MONITORING & HEALTH

### ✅ apps/monitoring
**Current Location**: `apps/monitoring/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Minimal model (may be empty) | COPY AS-IS | Placeholder; monitoring is mostly views | core.models | Low | 15 min | None | Copy directly |
| **services/health_service.py** | System health checks | COPY AS-IS | Database connectivity, cache health; domain-agnostic | core.models, django.db | Low | 30 min | None | Copy directly |
| **views.py** | Health dashboard UI | COPY & REFACTOR | Template structure reusable; gym-specific operational context | health_service | Low | 1 hr | Low | Copy; update for People operations |

---

## SETTINGS & CONFIGURATION LAYER

### ✅ apps/settings
**Current Location**: `apps/settings/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **branding/** | Tenant branding (logo, colors, custom domain) | COPY AS-IS | White-label framework; zero domain coupling | core.models | Medium | 2 hrs | Low | Copy directly; critical for multi-tenant SaaS |
| **branding/models.py** | TenantBranding model | COPY AS-IS | Logo upload, color palette, domain customization | core.models, Pillow | Low | 1 hr | None | Copy directly |
| **branding/services.py** | Branding service | COPY AS-IS | Branding application logic | branding.models | Low | 1 hr | None | Copy directly |
| **branding/api_views.py** | Branding API endpoints | COPY AS-IS | Tenant branding management API | branding.models | Low | 1 hr | None | Copy directly |
| **vocabulary/** | Field label customization | COPY & REFACTOR | Dynamic field labeling; currently maps gym terms | core.models | Low | 1-2 hrs | Low | Copy; add People-specific vocabulary mappings |
| **whatsapp/** | WhatsApp provider settings | COPY & REFACTOR | Provider-specific config; may not apply to People platform | core.models | Low | 1 hr | Low | Copy; determine if People needs WhatsApp integration |
| **roles/** | Role permission seeding/management | COPY AS-IS | Role CRUD; extensible | authority.models | Low | 1 hr | None | Copy directly |
| **context_processors.py** | Template context injection (vocabulary, branding) | COPY AS-IS | Context helpers; reusable | settings modules | Low | 30 min | None | Copy directly |

---

## DOCUMENT MANAGEMENT

### ✅ apps/documents
**Current Location**: `apps/documents/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Document storage model (files, metadata) | COPY AS-IS | Generic document management; no domain coupling | core.models, django.core.files | Medium | 1-2 hrs | Low | Copy directly; supports People document handling (contracts, training materials) |
| **views.py** | Document upload/download/management | COPY AS-IS | Document workflow; generic | documents.models | Medium | 2 hrs | Low | Copy directly |

---

## ACTIVITY TRACKING

### ✅ apps/activity
**Current Location**: `apps/activity/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **models.py** | Activity log (generic event tracking) | COPY AS-IS | Event logging different from audit; supports many event types | core.models | Low | 30 min | None | Copy directly; People-ready |
| **services/activity_service.py** | Activity recording | COPY AS-IS | Event dispatch; reusable | activity.models | Low | 30 min | None | Copy directly |

---

## GYM-SPECIFIC MODULES (DO NOT COPY)

### ❌ apps/sessions
**Current Location**: `apps/sessions/`
- **Models**: SessionType, SessionTemplate, SessionSchedule, SessionInstance, Booking, Attendance
- **Services**: Session scheduling, yoga class management, utilization tracking
- **Reason**: Entirely yoga/fitness-specific; no direct People Platform applicability
- **Action**: DO NOT COPY; develop People-specific equivalents if needed

### ❌ apps/bookings
**Current Location**: `apps/bookings/`
- **Models**: Booking-related (already in sessions but duplicated)
- **Services**: Booking management, cancellation, waitlist
- **Reason**: Session/class booking is gym-specific
- **Action**: DO NOT COPY

### ❌ apps/attendance
**Current Location**: `apps/attendance/`
- **Models**: Attendance tracking (class attendance)
- **Services**: Check-in/check-out, attendance marking
- **Reason**: Gym attendance tracking; not applicable to People
- **Action**: DO NOT COPY; develop People-specific participation tracking if needed

### ❌ apps/memberships
**Current Location**: `apps/memberships/`
- **Models**: Membership, MembershipPlan, SessionPackages
- **Services**: Membership lifecycle, plan management
- **Reason**: Gym membership plans; pricing structure is fitness-specific
- **Action**: DO NOT COPY; develop People subscription/contract models if needed

### ❌ apps/platform_sessions
**Current Location**: `apps/platform_sessions/`
- **Models**: Likely duplicate/alternative to sessions models
- **Reason**: Fitness session related
- **Action**: DO NOT COPY; verify overlap with sessions app first

### ❌ apps/members
**Current Location**: `members/` (outside apps)
- **Models**: Member model (gym member entity)
- **Services**: Member lifecycle, profile management
- **Reason**: Gym-specific member; references gym bookings, sessions
- **Action**: DO NOT COPY; replace with People employee/participant model

### ❌ apps/revenue
**Current Location**: `apps/revenue/`
- **Models**: Revenue tracking specific to gym
- **Services**: Revenue nudges ("upsell session packages"), forecasting
- **Reason**: Gym-specific revenue strategies
- **Action**: DO NOT COPY; develop People-specific commercial logic if needed

### ❌ apps/renewals
**Current Location**: `apps/renewals/`
- **Models**: Membership renewal tracking
- **Services**: Renewal triggers, automation
- **Reason**: Gym membership renewal; not applicable to People
- **Action**: DO NOT COPY; may adapt renewal framework for contract renewals if needed

### ❌ apps/expenses
**Current Location**: `apps/expenses/`
- **Models**: Expense tracking (operational)
- **Reason**: May be gym-specific; audit needed
- **Action**: AUDIT expense model; if generic, COPY & REFACTOR; if fitness-specific, replace

---

## LEGACY/CRM MODULES (DO NOT COPY)

### ❌ crm/
**Current Location**: `crm/` (outside apps)
- **Purpose**: CRM system for lead management
- **Note**: Pre-dates core platform; legacy design
- **Action**: DO NOT COPY; People Platform should use modern contact/organization system

---

## OLD/EXPERIMENTAL MODULES (EXAMINE BUT LIKELY DO NOT COPY)

### ⚠️ apps/core/middleware_old
**Purpose**: Superseded middleware implementations
**Action**: Ignore; use modern middleware only

### ⚠️ members/services
**Purpose**: Member-specific services (gym member operations)
**Action**: DO NOT COPY; audit first if any patterns useful

---

## CONFIGURATION & DEPLOYMENT

### ✅ config/settings
**Current Location**: `config/settings/`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **settings/base.py** | Django settings (installed apps, middleware, DB config) | COPY & REFACTOR | Foundation is solid; INSTALLED_APPS references gym modules that must be replaced | Django | High | 3-4 hrs | Medium | Copy; remove gym apps; add People apps; verify middleware order |
| **settings/production.py** | Production environment config | COPY AS-IS | Environment-specific settings; domain-agnostic | base.py | Low | 30 min | None | Copy directly; update for People infrastructure |
| **settings/development.py** | Development environment config | COPY AS-IS | Dev overrides; reusable | base.py | Low | 15 min | None | Copy directly |
| **settings/modules/** | Modular settings (if any) | COPY & REFACTOR | Likely contains gym-specific settings | base.py | Medium | 1-2 hrs | Low | Copy; audit and remove gym module configs |

### ✅ config/urls.py
**Current Location**: `config/urls.py`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **URL Patterns** | Django URL routing | COPY & REFACTOR | URL structure is sound; gym app routes must be removed/replaced | apps.*, config.settings | High | 2-3 hrs | Medium | Copy file; remove gym app routes; add People app routes |
| **DRF Router** | API endpoint registration | COPY & REFACTOR | Router pattern is good; gym model viewsets must be replaced | DRF | Medium | 1-2 hrs | Medium | Copy; update registered models |

### ✅ config/wsgi.py, asgi.py
**Current Location**: `config/wsgi.py`, `config/asgi.py`

| Component | Purpose | Category | Reason | Dependencies | Complexity | Effort | Risk | Action |
|---|---|---|---|---|---|---|---|---|
| **WSGI/ASGI** | Application entry points | COPY AS-IS | Standard Django; reusable | Django | Low | 30 min | None | Copy directly; no modifications needed |

---

## MANAGEMENT COMMANDS (SYSTEMATICALLY CATEGORIZED)

### ✅ COPY AS-IS (Reusable Automation)
- `apps/core/management/commands/seed_permissions.py` — Permission setup
- `apps/tenants/management/commands/ensure_platform_tenant.py` — Platform tenant initialization
- `apps/tenants/management/commands/provision_tenant.py` — Tenant provisioning
- `apps/audit/management/commands/*` — Audit operations
- `apps/lifecycles/management/commands/run_lifecycle_updates.py` — Lifecycle scheduler
- `apps/communications/management/commands/retry_failed_messages.py` — Message retry
- `apps/engagement/management/commands/run_retries.py` — Engagement signal processing
- `apps/monitoring/management/commands/*` — Health checks

### ✅ COPY & REFACTOR (Framework Reusable, Content Specific)
- `apps/communications/management/commands/seed_comms_defaults.py` — Replace with People templates
- `apps/communications/management/commands/seed_platform_comms.py` — Replace with People platform messages
- `apps/settings/roles/management/commands/seed_role_permissions.py` — Update People role matrix

### ❌ DO NOT COPY (Gym-Specific)
- `apps/renewals/management/commands/*` — Membership renewal
- `apps/revenue/management/commands/*` — Revenue nudges
- `apps/assessments/management/commands/*` (if gym-specific; if generic, copy)

---

## MIDDLEWARE LAYER

### ✅ COPY AS-IS
| Middleware | Purpose | Status |
|---|---|---|
| `django.middleware.security.SecurityMiddleware` | HTTPS enforcement | COPY AS-IS |
| `whitenoise.middleware.WhiteNoiseMiddleware` | Static file serving | COPY AS-IS |
| `django.contrib.sessions.middleware.SessionMiddleware` | Session management | COPY AS-IS |
| `django.middleware.common.CommonMiddleware` | GZIP, etags | COPY AS-IS |
| `django.middleware.csrf.CsrfViewMiddleware` | CSRF protection | COPY AS-IS |
| `django.contrib.auth.middleware.AuthenticationMiddleware` | User authentication | COPY AS-IS |
| `apps/core/middleware.TenantMiddleware` | Tenant detection & scoping | COPY AS-IS |
| `django.contrib.messages.middleware.MessageMiddleware` | Flash messages | COPY AS-IS |
| `django.middleware.clickjacking.XFrameOptionsMiddleware` | Clickjacking protection | COPY AS-IS |

---

## UTILITIES & HELPERS

### ✅ COPY AS-IS
| Module | Purpose |
|---|---|
| `apps/payments/utils/encryption.py` | Fernet-based encryption for secrets |
| `platform_core/` | Platform control utilities (if any) |

### ✅ COPY & REFACTOR
| Module | Purpose | Action |
|---|---|---|
| `apps/settings/context_processors.py` | Template context injection | Copy; add People-specific context |

---

## TESTING UTILITIES

### ✅ COPY AS-IS (Test Framework)
- `pytest.ini` — Test configuration
- All test files (`tests.py`, `tests_*.py`) — Patterns are reusable even if test data is gym-specific
- Test utilities and fixtures — Excellent patterns for People testing

**Action**: Copy test files; update test data for People domain

---

## SUMMARY STATISTICS

| Category | Count | Copy As-Is | Refactor | Do Not Copy |
|---|---|---|---|---|
| **Django Apps** | 35+ | 18 | 12 | 5 |
| **Models** | 80+ | 60+ | 15+ | 5+ |
| **Services** | 50+ | 35+ | 12+ | 3+ |
| **Management Commands** | 25+ | 15+ | 8+ | 2+ |
| **Views/APIs** | 30+ | 15+ | 12+ | 3+ |

---

## EXTRACTION RISK ASSESSMENT

### HIGH RISK (Requires Careful Refactoring)
1. **Tenant Provisioning** — Contains default CRM stage creation specific to gym; must be redesigned
2. **Dashboard Widgets** — All current widgets are gym-specific; complete replacement needed
3. **Settings Configuration** — Many installed apps must be removed; large refactoring surface
4. **URL Routing** — Many gym routes must be removed and People routes added

### MEDIUM RISK (Standard Refactoring)
1. **Communications** — Event types and default templates are gym-specific
2. **Analytics** — Metrics must be redesigned for People KPIs
3. **Engagement** — Signal triggers are gym-specific
4. **Reporting** — Financial calculations may need People-specific logic

### LOW RISK (Extraction Straightforward)
1. **Core Infrastructure** (tenants, accounts, authority, audit)
2. **Payments** (gateway abstraction; only provider config may need audit)
3. **Assessments** (completely reusable)
4. **Intake Forms** (completely reusable)
5. **Enrollments/Verticals** (completely reusable)

---

## NEXT STEPS

See `FOUNDATION_MIGRATION_PLAN.md` for phased extraction strategy, dependency ordering, and risk mitigation.
