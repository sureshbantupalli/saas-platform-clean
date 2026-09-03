# FOUNDATION_MIGRATION_PLAN.md

## ANJASI People Platform — Phased Extraction & Migration Strategy

**Purpose**: Provide a controlled, dependency-aware extraction schedule to migrate reusable components from saas-platform-clean into a new, independent ANJASI People platform codebase.

**Success Criteria**:
- Each phase has explicit validation gates before proceeding
- Dependencies are respected (no circular imports, forward compatibility)
- Gym-specific code is completely removed
- ANJASI People platform is standalone with zero git/code dependencies on gym platform
- Production migration path is documented and tested

---

## EXTRACTION PRINCIPLES

### 1. Dependency-First Ordering
Extract base infrastructure first; dependent layers follow. Example: Authority (RBAC) before Dashboard (uses permissions).

### 2. Zero Gym Coupling
At end of each phase, verify no gym imports exist in extracted code. Scan for:
- `from apps.sessions`, `from apps.bookings`, `from apps.memberships`, `from members`
- String references to gym entity names ("Trainer", "Yoga", "Class")
- Gym-specific status/state constants

### 3. Test-First Validation
Each phase includes test suite extraction and passing tests before production use.

### 4. Branding Completeness
Ensure all UI elements (admin, views, templates) are generic or rebranded to "ANJASI People."

---

## PHASE 1: FOUNDATION LAYER (Weeks 1-2)

**Goal**: Extract core multi-tenant SaaS infrastructure. This phase enables Phases 2+ to work.

**Risk Level**: LOW

### 1.1 Django Configuration & Deployment

**Components**:
- `config/` (entire directory with subdirectories)
- `requirements.txt` (copy as-is; adjust as needed)
- `manage.py`, `pytest.ini`, `.env.example`
- `.gitignore`, `.env` (create new with People secrets)

**Actions**:
1. Copy `config/` → new repository
2. Update `config/settings/base.py`:
   - Remove gym app references from `INSTALLED_APPS` (keep list of apps to add)
   - Verify middleware order (TenantMiddleware must stay in position)
   - Remove gym-specific settings variables
3. Update `config/urls.py`:
   - Remove gym URL patterns (`bookings/`, `sessions/`, `memberships/`, `attendance/`)
   - Keep DRF router; remove gym model registrations
   - Keep core routes (`auth/`, `admin/`, `api/`)
4. Copy `requirements.txt` → new repo; verify all dependencies needed

**Validation Gate**:
```bash
python manage.py check  # Should pass with missing gym apps (expected)
pytest config/tests --tb=short  # If any config tests exist
```

**Complexity**: LOW | **Effort**: 3-4 hrs | **Risk**: LOW

---

### 1.2 Core Models & Database Layer

**Components**:
- `apps/core/` (complete)
- Django migration framework

**Actions**:
1. Create `apps/core/` in new repo
2. Copy all files from `apps/core/`:
   - `models.py` (BaseModel, Tenant, TenantAwareModel, Branch)
   - `managers/` (TenantScopedManager, TenantManager)
   - `middleware.py` (TenantMiddleware)
   - `permissions/` (DRF permission classes)
   - `services/base_service.py` (service base class)
   - `admin_base.py`, `tenant_context.py`, `platform.py`
   - `migrations/` (copy all)
3. Verify no gym references in any file
4. Rename `Branch` → `Location` if more appropriate for People context (optional but recommended)

**Actions for Refactoring**:
- `tenant_provision_service.py` — Remove CRM LeadStage creation; replace with People-appropriate defaults (e.g., onboarding stages, team structures)

**Validation Gate**:
```bash
python manage.py makemigrations
python manage.py migrate core  # Should succeed
pytest apps/core/tests  # Run core tests
```

**Complexity**: MEDIUM | **Effort**: 4-5 hrs | **Risk**: LOW

---

### 1.3 Authentication Layer

**Components**:
- `apps/accounts/` (complete)
- `apps/authority/` (complete)
- Custom User model and RBAC system

**Actions**:
1. Create `apps/accounts/` and `apps/authority/` in new repo
2. Copy all files from both
3. Verify User model references only core and authority (no gym apps)
4. Update User documentation/comments if they reference gym roles

**Validation Gate**:
```bash
python manage.py migrate accounts authority  # Should succeed
pytest apps/accounts/tests apps/authority/tests  # RBAC tests must pass
```

**Complexity**: LOW | **Effort**: 2-3 hrs | **Risk**: LOW

---

### 1.4 Tenant Management & Invitations

**Components**:
- `apps/tenants/` (complete)
- Tenant provisioning and invitation system

**Actions**:
1. Copy `apps/tenants/` to new repo
2. Refactor `tenant_provision_service.py`:
   - Remove CRM LeadStage default creation
   - Add People-specific defaults (e.g., default roles: Admin, Manager, Employee)
3. Verify no gym service references
4. Test tenant creation flow end-to-end

**Validation Gate**:
```bash
python manage.py migrate tenants
# Test creating a new tenant via CLI
python manage.py provision_tenant --name "TestTenant" --subdomain "test"
# Verify tenant created with correct defaults
```

**Complexity**: MEDIUM | **Effort**: 3-4 hrs | **Risk**: MEDIUM (CRM removal)

---

### 1.5 Audit System

**Components**:
- `apps/audit/` (complete)
- Immutable audit trail, timeline service

**Actions**:
1. Copy `apps/audit/` to new repo
2. Verify no gym service references (should be none; audit is generic)
3. Copy all services, models, views

**Validation Gate**:
```bash
python manage.py migrate audit
pytest apps/audit/tests  # Extensive test suite
```

**Complexity**: LOW | **Effort**: 2 hrs | **Risk**: LOW

---

### 1.6 Monitoring & Health

**Components**:
- `apps/monitoring/` (complete)
- System health checks, operational dashboards

**Actions**:
1. Copy `apps/monitoring/` to new repo
2. Update UI templates for People context

**Validation Gate**:
```bash
python manage.py migrate monitoring
# Test health endpoint
curl http://localhost:8000/monitoring/health
```

**Complexity**: LOW | **Effort**: 1-2 hrs | **Risk**: LOW

---

### Phase 1 Summary

**After Phase 1 Completion**:
- ✅ Django multi-tenant SaaS foundation is in place
- ✅ User authentication and RBAC system functional
- ✅ Tenant provisioning works
- ✅ Audit trail system active
- ✅ No gym-specific code in codebase
- ✅ Basic Django admin works

**Test**: Start Django dev server; log in as admin; verify no 404s for missing gym routes.

**Database Schema**: ~20 tables (users, tenants, roles, permissions, audit, sessions/auth tables)

**Blockers for Phase 2**: None; all Phase 1 components are foundation-only.

---

## PHASE 2: COMMUNICATION & AUTOMATION (Weeks 3-4)

**Goal**: Extract event-driven systems (messaging, lifecycle automation, activity tracking).

**Risk Level**: MEDIUM

### 2.1 Communication System

**Components**:
- `apps/communications/` (models, services, views, management commands)
- Message templates, trigger rules, provider configuration

**Actions**:
1. Copy `apps/communications/` to new repo
2. Refactor event type definitions:
   - Remove gym events ("booking_confirmed", "attendance_marked")
   - Add People events ("onboarding_started", "training_completed", "assessment_passed", "team_invitation_sent")
3. Refactor default message templates (`seed_comms_defaults.py`, `seed_platform_comms.py`):
   - Replace gym-specific templates (cancellation reminders, renewal notices)
   - Create People onboarding welcome, training invitations, progress notifications
4. Audit provider integrations (MSG91, Razorpay SMS, WhatsApp)
   - Keep generic SMS/WhatsApp/Email infrastructure
   - Remove Razorpay-specific SMS (if used only for payments)

**Validation Gate**:
```bash
python manage.py migrate communications
python manage.py seed_platform_comms  # Should create People platform messages
pytest apps/communications/tests
# Verify template content contains no "Trainer", "Session", "Booking" references
```

**Complexity**: HIGH | **Effort**: 5-6 hrs | **Risk**: MEDIUM (event type replacement)

---

### 2.2 Lifecycle Automation Framework

**Components**:
- `apps/lifecycles/` (models, services, orchestration)
- Batch operation tracking, scheduler integration

**Actions**:
1. Copy `apps/lifecycles/` to new repo
2. Verify no gym service references (should be none; framework is generic)
3. Create People-specific lifecycle definitions:
   - Examples: Onboarding completeness check, Training progress calculation, Engagement scoring
   - Document as migration guide for People team

**Validation Gate**:
```bash
python manage.py migrate lifecycles
# Verify LifecycleRun table exists and is accessible
```

**Complexity**: LOW | **Effort**: 2-3 hrs | **Risk**: LOW

---

### 2.3 Activity Tracking

**Components**:
- `apps/activity/` (models, services)
- Generic event logging (separate from audit)

**Actions**:
1. Copy `apps/activity/` to new repo
2. Verify no domain-specific event types

**Validation Gate**:
```bash
python manage.py migrate activity
```

**Complexity**: LOW | **Effort**: 1-2 hrs | **Risk**: LOW

---

### 2.4 Engagement & Retention Framework

**Components**:
- `apps/engagement/` (models, services)
- Signal processing, retention/re-engagement logic

**Actions**:
1. Copy `apps/engagement/` to new repo
2. Refactor model fields and service logic:
   - Rename gym-specific fields ("member_gym_visits" → "user_engagement_score")
   - Replace gym signals ("low_attendance") with People signals ("inactive_status", "no_training_participation")
3. Update trigger definitions and actions
4. Verify retention signals are appropriate for People context

**Validation Gate**:
```bash
python manage.py migrate engagement
# Verify models don't reference gym entities
pytest apps/engagement/tests  # Update test data
```

**Complexity**: HIGH | **Effort**: 4-5 hrs | **Risk**: MEDIUM (signal replacement)

---

### Phase 2 Summary

**After Phase 2 Completion**:
- ✅ Event-driven communication system live
- ✅ Message templates adapted to People events
- ✅ Lifecycle automation framework ready for People workflows
- ✅ Activity tracking operational
- ✅ Engagement signal system in place (People-specific)

**Database Schema**: Add ~15 tables (communications, lifecycles, activity, engagement)

**Blockers for Phase 3**: None; Phase 2 components are independent layers.

---

## PHASE 3: ASSESSMENTS & LEARNING (Week 5)

**Goal**: Extract assessment and training framework.

**Risk Level**: LOW

### 3.1 Assessments Module

**Components**:
- `apps/assessments/` (complete)
- Models, services, certificate generation, grading engine

**Actions**:
1. Copy `apps/assessments/` to new repo
2. Verify no gym references (should be none; framework is domain-agnostic)
3. Copy all models: Assessment, Question, QuestionOption, StudentAssessment, AssessmentAttempt, AttemptAnswer, AssessmentScore, CertificateTemplate
4. Copy services: assessment_service, question_service, attempt_service, certificate_service, grading_service
5. Create People-appropriate assessment examples (onboarding knowledge check, skill assessment)
6. Test certificate generation

**Validation Gate**:
```bash
python manage.py migrate assessments
pytest apps/assessments/tests  # Extensive test suite (~20k lines)
# Create test assessment, attempt, verify grading works
```

**Complexity**: MEDIUM | **Effort**: 3-4 hrs | **Risk**: LOW

---

### 3.2 Intake Forms

**Components**:
- `apps/intake/` (complete)
- Form builder, submission handling, prefill logic

**Actions**:
1. Copy `apps/intake/` to new repo
2. Verify no gym references
3. Create People-appropriate intake forms (employee onboarding questionnaire, skills assessment)
4. Test form submission workflow

**Validation Gate**:
```bash
python manage.py migrate intake
pytest apps/intake/tests
# Create and submit test form
```

**Complexity**: MEDIUM | **Effort**: 3-4 hrs | **Risk**: LOW

---

### Phase 3 Summary

**After Phase 3 Completion**:
- ✅ Assessment/training system live
- ✅ Intake form builder functional
- ✅ Certificate generation working

**Database Schema**: Add ~10 tables (assessments, intake, certificates)

---

## PHASE 4: ENROLLMENT & BUSINESS STRUCTURE (Week 6)

**Goal**: Extract enrollment, verticals, and service catalog.

**Risk Level**: LOW

### 4.1 Verticals & Catalog

**Components**:
- `apps/verticals/` (business line configuration)
- `apps/catalog/` (service definitions)
- Enrollment model

**Actions**:
1. Copy `apps/verticals/` to new repo
2. Copy `apps/catalog/` to new repo
3. Copy `apps/enrollments/` to new repo
4. Verify all models are generic (should be completely generic)
5. Create People-appropriate verticals (e.g., "Engineering", "Design", "Operations")
6. Create Services per vertical (e.g., "Python Training", "UI/UX Workshop")

**Validation Gate**:
```bash
python manage.py migrate verticals catalog enrollments
# Create test vertical, service, enrollment
pytest apps/enrollments/tests
```

**Complexity**: LOW | **Effort**: 2-3 hrs | **Risk**: LOW

---

### Phase 4 Summary

**After Phase 4 Completion**:
- ✅ Business vertical/team structure configurable
- ✅ Service catalog in place
- ✅ Enrollment tracking for employees in programs

**Database Schema**: Add ~5 tables (verticals, catalog, enrollments)

---

## PHASE 5: PAYMENTS & FINANCIAL (Weeks 7-8)

**Goal**: Extract payment infrastructure and financial reporting.

**Risk Level**: HIGH

### 5.1 Payment Infrastructure

**Components**:
- `apps/payments/` (models, services, gateways, encryption)
- Payment processing, invoice generation, provider integration

**Actions**:
1. Copy `apps/payments/` to new repo
2. Audit Razorpay gateway integration:
   - Verify all assumptions about payment flow are People-compatible
   - Test payment creation, verification workflow
3. Audit encryption utils (`utils/encryption.py`):
   - Verify Fernet-based encryption implementation
   - Ensure credential storage is secure
4. Remove/add payment gateways based on People requirements (keep generic structure)
5. Update payment types/categories if gym-specific

**Validation Gate**:
```bash
python manage.py migrate payments
pytest apps/payments/tests_razorpay  # Extensive test suite with mocks
# Verify payment creation, webhook handling works
```

**Complexity**: HIGH | **Effort**: 6-8 hrs | **Risk**: HIGH (payment correctness critical)

---

### 5.2 Payouts & Financial Reporting

**Components**:
- `apps/payouts/` (payout tracking)
- `apps/reporting/` (GST, P&L reporting)
- Financial analytics

**Actions**:
1. Copy `apps/payouts/` to new repo
2. Audit payout models — verify applicability to People:
   - If People has instructor commissions/trainer payouts, keep as-is
   - If not applicable, mark as optional/future
3. Copy `apps/reporting/` to new repo
4. Audit financial reporting formulas:
   - Verify P&L calculation logic
   - Replace gym-specific revenue streams with People equivalents (e.g., course fees, subscription revenue)
   - Update GST rules if different for People business model
5. Create People financial report templates

**Validation Gate**:
```bash
python manage.py migrate payouts reporting
pytest apps/reporting/tests_realworld  # Real data test suite
# Generate test P&L report
```

**Complexity**: HIGH | **Effort**: 6-8 hrs | **Risk**: HIGH (financial correctness, GST compliance)

---

### Phase 5 Summary

**After Phase 5 Completion**:
- ✅ Payment processing operational
- ✅ Financial reporting (P&L, GST) working
- ✅ Payout system in place (if applicable to People)

**Database Schema**: Add ~10 tables (payments, invoices, transactions, reports)

**Critical Tests**: Payment gateway integration, financial report accuracy

---

## PHASE 6: DASHBOARD, ANALYTICS & ACTIONS (Weeks 9-10)

**Goal**: Extract customizable dashboard and analytics framework.

**Risk Level**: MEDIUM

### 6.1 Dashboard Framework

**Components**:
- `apps/dashboard/` (models, widget service, registry)
- Widget system, API layer

**Actions**:
1. Copy `apps/dashboard/models.py` (generic widget registry)
2. Copy `apps/dashboard/registry.py` (widget factory/plugin system)
3. Copy `apps/dashboard/services/widget_service.py` (composition logic)
4. Copy `apps/dashboard/api/` (API endpoints)
5. **DO NOT COPY** `apps/dashboard/widgets/` (all gym-specific widgets)
6. Create People-specific widgets:
   - Employee engagement dashboard
   - Training completion rates
   - Skills progress
   - Team participation metrics
7. Create widget examples and documentation

**Validation Gate**:
```bash
python manage.py migrate dashboard
pytest apps/dashboard/services/test_widget_service.py  # Core widget logic
# Test dashboard rendering with People widgets
```

**Complexity**: MEDIUM | **Effort**: 4-5 hrs | **Risk**: MEDIUM (widget replacement)

---

### 6.2 Analytics Framework

**Components**:
- `apps/analytics/` (services, views, API)
- Metrics calculation and dashboards

**Actions**:
1. Copy `apps/analytics/services/dashboard_service.py`
2. Refactor all metrics:
   - Remove gym metrics (class attendance %, session utilization, revenue trends)
   - Add People metrics (training completion %, skill acquisition, employee engagement, program ROI)
3. Copy `apps/analytics/views.py`
4. Update analytics UI templates for People context
5. Create People-specific metric definitions and KPIs

**Validation Gate**:
```bash
python manage.py migrate analytics
# Create test data and verify metric calculations
pytest apps/analytics/tests  # Update test cases for People metrics
```

**Complexity**: HIGH | **Effort**: 5-6 hrs | **Risk**: MEDIUM (metric definitions)

---

### 6.3 Next Best Actions Framework

**Components**:
- `apps/actions/` (recommendation engine)
- Action type definitions, trigger logic

**Actions**:
1. Copy `apps/actions/services/next_best_action_service.py`
2. Refactor action types and recommendations:
   - Remove gym actions ("Book a class", "Renew membership")
   - Add People actions ("Complete onboarding", "Register for training", "Join team", "Update skills")
3. Update action trigger conditions
4. Create People-specific action library

**Validation Gate**:
```bash
python manage.py migrate actions
# Test NBA recommendations for People context
```

**Complexity**: MEDIUM | **Effort**: 3-4 hrs | **Risk**: MEDIUM (action definition)

---

### Phase 6 Summary

**After Phase 6 Completion**:
- ✅ Customizable dashboard operational
- ✅ Analytics framework with People metrics
- ✅ Recommendation engine (next best actions) live

**Database Schema**: Add ~5 tables (dashboard widgets, analytics snapshots)

---

## PHASE 7: SETTINGS & CUSTOMIZATION (Week 11)

**Goal**: Extract tenant customization and settings frameworks.

**Risk Level**: LOW

### 7.1 Branding & Settings

**Components**:
- `apps/settings/branding/` (logo, colors, custom domain)
- `apps/settings/roles/` (role management)
- `apps/settings/vocabulary/` (field label customization)
- `apps/settings/context_processors.py` (template context)

**Actions**:
1. Copy entire `apps/settings/` directory
2. Verify no gym-specific settings
3. Update vocabulary mappings for People context:
   - "Member" → "Employee" / "Participant"
   - "Trainer" → "Mentor" / "Coach"
   - "Session" → "Training" / "Program"
4. Create People-appropriate role seed data
5. Test branding upload and application

**Validation Gate**:
```bash
python manage.py migrate settings
# Upload test logo and color palette
# Verify branding applied to UI
```

**Complexity**: LOW | **Effort**: 3-4 hrs | **Risk**: LOW

---

### Phase 7 Summary

**After Phase 7 Completion**:
- ✅ Multi-tenant branding (white-label) working
- ✅ Settings framework complete
- ✅ Field label customization functional

**Database Schema**: Add ~5 tables (branding, role configs, settings)

---

## PHASE 8: DOCUMENTS & UTILITIES (Week 12)

**Goal**: Extract document management and remaining utilities.

**Risk Level**: LOW

### 8.1 Document Management

**Components**:
- `apps/documents/` (file storage, metadata, management)

**Actions**:
1. Copy `apps/documents/` to new repo
2. Verify no gym-specific document types
3. Create People-appropriate document workflows (training materials, contracts, certificates)

**Validation Gate**:
```bash
python manage.py migrate documents
# Test document upload, download
```

**Complexity**: LOW | **Effort**: 2-3 hrs | **Risk**: LOW

---

### 8.2 Utilities & Helpers

**Components**:
- `apps/payments/utils/encryption.py` (already copied in Phase 5, but verify)
- `platform_core/` (if contains useful utilities)
- Test utilities

**Actions**:
1. Verify encryption utilities are in place
2. Copy any generic utilities from `platform_core/`
3. Review test utilities for reuse

**Complexity**: LOW | **Effort**: 1-2 hrs | **Risk**: LOW

---

### Phase 8 Summary

**After Phase 8 Completion**:
- ✅ Document management system live
- ✅ All utility functions available

---

## PHASE 9: TESTING, REFACTORING & VALIDATION (Weeks 13-14)

**Goal**: Ensure all phases work together; no gym code remains; comprehensive testing.

**Risk Level**: MEDIUM (Integration risk)

### 9.1 Integration Testing

**Actions**:
1. Run full test suite across all apps:
   ```bash
   pytest --cov=apps --cov=platform_core
   ```
2. Verify no import errors or missing dependencies
3. Test end-to-end flows:
   - Tenant creation → User provisioning → Assignment to program → Assessment → Certificate
   - Payment flow → Invoice generation → Financial reporting
   - Communication template → Message sending

**Validation Gate**:
```bash
# No gym references
grep -r "from apps.sessions\|from apps.bookings\|from apps.memberships\|from members" apps config
# Should return: (no results)

# No gym string references
grep -r "Session\|Booking\|Trainer\|Yoga\|Class\|Attendance" apps config | grep -v "# NOTE"
# Should return: (no results or only comments)
```

**Complexity**: HIGH | **Effort**: 6-8 hrs | **Risk**: MEDIUM

---

### 9.2 Codebase Cleanup

**Actions**:
1. Remove all legacy/old code
2. Clean up `config/settings/modules/` (remove gym module configs)
3. Update all UI templates for People branding
4. Remove gym-specific admin customizations
5. Verify all migrations are clean and sequential

**Complexity**: MEDIUM | **Effort**: 4-5 hrs | **Risk**: LOW

---

### 9.3 Documentation

**Actions**:
1. Create deployment guide for People platform
2. Document API endpoints for People context
3. Create data model diagrams
4. Document payment flow, financial reporting logic
5. Create admin runbooks (tenant provisioning, issue troubleshooting)

**Complexity**: MEDIUM | **Effort**: 4-6 hrs | **Risk**: LOW

---

### Phase 9 Summary

**After Phase 9 Completion**:
- ✅ All phases integrated and tested
- ✅ Zero gym code in codebase
- ✅ Comprehensive documentation complete
- ✅ Ready for staging deployment

---

## PHASE 10: STAGING DEPLOYMENT & CUTOVER (Weeks 15-16)

**Goal**: Deploy to staging; verify production readiness.

**Risk Level**: HIGH (Deployment)

### 10.1 Staging Environment Setup

**Actions**:
1. Deploy to staging with real infrastructure (PostgreSQL, Redis, etc.)
2. Run full test suite in staging
3. Create test tenants and test end-to-end workflows
4. Load test performance
5. Verify integrations (payment gateways, SMS/Email, etc.)

**Validation Gate**:
```bash
# Staging deployment healthy checks
- Django startup: OK
- Database migrations: OK
- All tests passing: OK
- Health endpoint: OK
- API endpoints responding: OK
- Payment gateway mock: OK
- Message delivery: OK
```

**Complexity**: HIGH | **Effort**: 8-10 hrs | **Risk**: HIGH

---

### 10.2 Production Readiness

**Actions**:
1. Security audit (credential handling, SQL injection, CSRF, etc.)
2. Performance baseline testing
3. Backup/restore procedures
4. Monitoring and alerting setup
5. Incident response runbooks

**Complexity**: HIGH | **Effort**: 10-12 hrs | **Risk**: HIGH

---

### Phase 10 Summary

**After Phase 10 Completion**:
- ✅ Staging environment live and tested
- ✅ Production-ready
- ✅ Deployment procedures documented
- ✅ Ready for production migration (if needed)

---

## TIMELINE SUMMARY

| Phase | Duration | Key Deliverable | Risk |
|---|---|---|---|
| 1. Foundation | Weeks 1-2 | Multi-tenant SaaS core | LOW |
| 2. Communications | Weeks 3-4 | Event-driven messaging | MEDIUM |
| 3. Assessments | Week 5 | Training framework | LOW |
| 4. Enrollment | Week 6 | Business structure | LOW |
| 5. Payments | Weeks 7-8 | Financial infrastructure | HIGH |
| 6. Dashboard | Weeks 9-10 | Analytics & customization | MEDIUM |
| 7. Settings | Week 11 | Branding & configuration | LOW |
| 8. Documents | Week 12 | Document management | LOW |
| 9. Integration | Weeks 13-14 | Testing & cleanup | MEDIUM |
| 10. Staging | Weeks 15-16 | Production readiness | HIGH |
| **TOTAL** | **~4 months** | **ANJASI People Platform** | |

---

## RISK MITIGATION STRATEGIES

### HIGH-RISK PHASES (5, 6, 9, 10)

**Risk: Payment Flow Correctness (Phase 5)**
- **Mitigation**: Extensive mock testing before real gateway; staged rollout with manual verification; payment reconciliation dashboard
- **Validation**: Real transaction test → Webhook verification → Settlement confirmation

**Risk: Metric Definition Accuracy (Phase 6)**
- **Mitigation**: Work with People stakeholders to define KPIs; pilot metrics with test data; A/B test recommendations
- **Validation**: Metric validation against manual calculations; stakeholder sign-off

**Risk: Integration Failures (Phase 9)**
- **Mitigation**: Comprehensive integration tests; staged integration (1 phase at a time); dependency injection to mock services
- **Validation**: Full test suite passing; manual end-to-end testing

**Risk: Production Deployment (Phase 10)**
- **Mitigation**: Staging environment mirror; gradual rollout; rollback procedures; real-time monitoring
- **Validation**: Health checks; smoke tests; performance baselines

---

## DEPENDENCY GRAPH

```
Phase 1 (Foundation)
├─→ Phase 2 (Communications) — depends on: Auth, Tenants, Audit
├─→ Phase 3 (Assessments) — depends on: Auth, Core
├─→ Phase 4 (Enrollment) — depends on: Auth, Core
├─→ Phase 5 (Payments) — depends on: Auth, Core
└─→ Phase 7 (Settings) — depends on: Auth, Core

Phase 2 (Communications)
└─→ Phase 6 (Dashboard/Analytics) — depends on: Communications, Assessments

Phase 3 (Assessments)
└─→ Phase 6 (Dashboard/Analytics)

Phase 4 (Enrollment)
└─→ Phase 6 (Dashboard/Analytics)

Phase 5 (Payments)
└─→ Phase 6 (Dashboard/Analytics)
└─→ Phase 9 (Reporting)

Phase 6 (Dashboard/Analytics)
└─→ Phase 9 (Integration Testing)

Phase 7-8 (Settings/Documents)
└─→ Phase 9 (Integration Testing)

Phase 9 (Integration Testing)
└─→ Phase 10 (Staging Deployment)
```

**Critical Path**: Phase 1 → Phase 2 → Phase 6 → Phase 9 → Phase 10

---

## VALIDATION CHECKPOINTS

### Pre-Phase Checklist

Each phase begins with:
- [ ] Dependency map reviewed (no circular imports)
- [ ] Gym code scan completed (zero gym references identified)
- [ ] Tests isolated and passing
- [ ] Refactoring list documented

### Post-Phase Checklist

Each phase ends with:
- [ ] All migrations applied successfully
- [ ] Full test suite passing
- [ ] Gym code scan: CLEAN (zero references)
- [ ] UI templates reviewed (no gym branding)
- [ ] Documentation updated
- [ ] Stakeholder sign-off (if needed)

---

## ROLLBACK PROCEDURES

**If Phase Validation Fails**:
1. Identify failure root cause
2. Revert git commits for the phase
3. Fix identified issues in saas-platform-clean (if applicable)
4. Restart phase after verification

**No cross-phase rollback needed** — each phase creates new database schema; safe to reset and retry.

---

## SUCCESS CRITERIA

### At Project Completion

- [ ] ANJASI People platform is fully independent (zero imports from gym platform)
- [ ] All phases pass validation gates
- [ ] Test coverage > 80%
- [ ] No production issues in staging
- [ ] Documentation complete
- [ ] Deployment procedures tested
- [ ] Team trained on new codebase

### Business Metrics

- [ ] Platform supports minimum 10 concurrent tenants
- [ ] Payment processing works end-to-end
- [ ] Response time < 500ms for 95% of API calls
- [ ] Zero unplanned downtime in staging
- [ ] Financial reporting accurate within 0.01%

---

## NEXT STEPS

1. **Immediate** (Today): Review this plan with tech and product teams; identify any phase adjustments
2. **Week 1**: Kick off Phase 1; create new People Platform repository with scaffolding
3. **Weekly**: Phase retrospectives; adjust timeline if needed
4. **Weeks 15-16**: Staging deployment and production readiness review

---

## APPENDIX: PEOPLE-SPECIFIC ENTITY MAPPING

### Terminology Mapping (for refactoring)

| Gym Concept | People Concept | Example |
|---|---|---|
| Member | Employee / Participant | "John is an employee" |
| Trainer | Mentor / Coach / Manager | "Hire a new mentor" |
| Session | Training / Workshop | "Attend the Python workshop" |
| Class Pack | Training Program | "Enroll in the Data Science program" |
| Studio | Department / Location | "Engineering team" |
| Booking | Registration | "Register for the workshop" |
| Attendance | Participation | "Mark participation" |
| Membership | Subscription / Contract | "Employee subscription" |
| Renewal | Contract renewal | "Renew annual contract" |

### Event Type Mapping

| Gym Event | People Event |
|---|---|
| booking_confirmed | training_registered |
| attendance_marked | participation_recorded |
| membership_renewed | subscription_renewed |
| payment_success | payment_processed |
| class_cancelled | training_cancelled |
| new_member_joined | new_employee_onboarded |
| low_attendance | low_participation |
| trainer_assigned | mentor_assigned |

### Role Mapping

| Gym Role | People Role |
|---|---|
| Owner | Owner / Admin |
| Manager | Manager / Team Lead |
| Trainer | Mentor / Trainer / Instructor |
| Front Desk | Coordinator / Administrator |
| Member | Employee / Participant |

---

## END OF MIGRATION PLAN

See `FOUNDATION_EXTRACTION_MATRIX.md` for detailed component analysis.
