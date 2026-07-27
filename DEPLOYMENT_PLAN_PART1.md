# SaaS Platform Complete Deployment Plan

**Project:** Multi-Tenant SaaS Platform  
**Analysis Date:** 2026-06-28  
**Total Apps:** 37 (33 main + 4 in non-standard locations)  
**Code Coverage:** 78% (29/37 apps have tests)  

---

## EXECUTIVE SUMMARY

This SaaS platform is a comprehensive multi-tenant system with 37 Django apps. The platform uses PostgreSQL, Django REST Framework, and a sophisticated multi-tenancy model. Current test coverage is 78% with 8 apps lacking test coverage.

**Key Findings:**
- Well-structured codebase with clear separation of concerns
- Multi-tenant architecture (accounts/tenants/members foundation)
- Strong financial system (payments, payouts, revenue, expenses)
- Advanced features (assessments, communications, engagement, reporting)
- Missing test coverage in 8 apps (critical blocker for production)
- No conftest.py fixtures defined (test infrastructure needs enhancement)

---

## PART 1: CODEBASE AUDIT RESULTS

### 1.1 Apps Overview Summary

**Total Metrics:**
- Total Models: 31
- Total Views: 30
- Total Services: 17
- Total Migrations: 103
- Apps with Tests: 29 (78%)
- Apps WITHOUT Tests: 8 (22%)

### 1.2 Apps Without Test Coverage (CRITICAL)

1. **activity** (2 migrations) - Activity tracking/logging
2. **catalog** (2 migrations) - Product/Service catalog
3. **documents** (2 migrations) - Document management system
4. **expenses** (2 migrations) - Expense tracking/management
5. **payouts** (2 migrations) - Payout processing
6. **platform_sessions** (2 migrations) - Session management
7. **settings.whatsapp** (1 migration) - WhatsApp integration config
8. **verticals** (1 migration) - Business verticals/segments

### 1.3 Test Infrastructure Status

```
conftest.py:           NOT FOUND (⚠️ Needs implementation)
pytest.ini:            EXISTS ✓
Test discovery:        apps/assessments/tests only (⚠️ Limited scope)
Markers defined:       4 (slow, integration, multi_tenancy, critical)
```

Issue: pytest.ini testpaths limited to `apps/assessments/tests` - needs expansion

### 1.4 Critical Dependency Chain

**Tier 0: Foundation (NO DEPENDENCIES)**
- core.Tenant
- settings.roles.Role
- authority.PermissionAction

**Tier 1: Depends on Tier 0**
- accounts.User (→ Tenant, Role)
- members.Member (→ Tenant)
- crm.models (→ Tenant, settings)

**Tier 2: Depends on Tier 0-1**
- sessions.SessionType/SessionTemplate
- memberships.Membership (→ Member, Tenant)
- bookings.Booking (→ SessionInstance, Member)
- attendance.Attendance (→ Member, Tenant)
- engagement.Engagement (→ Member, communications)
- enrollments.Enrollment (→ Member, Vertical, Catalog)

**Tier 3: Financial/Advanced**
- payments.Payment (→ Member, Vertical, Tenant)
- revenue.Revenue (→ Member)
- expenses.Expense (→ Vertical, Member)
- payouts.Payout (→ Vertical)
- renewals.Renewal (→ Membership)

**Tier 4: Cross-cutting**
- documents.Document (→ Member, Vertical, Catalog, Payments)
- assessments.Assessment (→ Member, various)
- communications.Message (→ MessageTemplate, Member)
- reporting.Report (→ Analytics)

---

## PART 2: PHASED DEPLOYMENT STRATEGY

### Phase 1: CORE INFRASTRUCTURE (Week 1)

**Objective:** Establish foundation systems, security, and multi-tenancy

**Apps to Deploy (in order):**

1. **apps/core** - Tenant model, BaseModel, Middleware
   - Models: 1 (Tenant)
   - Dependencies: Django built-ins
   - Migrations: 6
   - Status: ✓ Has tests
   - Deployment time: ~2-4 hours

2. **apps/authority** - Roles & RBAC foundation
   - Models: 1 (PermissionAction)
   - Dependencies: None
   - Migrations: 4
   - Status: ✓ Has tests
   - Deployment time: ~2 hours

3. **apps/tenants** - Tenant management
   - Dependencies: core
   - Status: ✓ Has tests
   - Deployment time: ~1 hour

4. **apps/accounts** - Custom User model, auth
   - Dependencies: core.Tenant, authority.Role
   - Migrations: 4
   - Status: ✓ Has tests
   - Deployment time: ~3-4 hours
   - ⚠️ CRITICAL: Changes AUTH_USER_MODEL - requires careful migration

5. **settings.roles** - Role permissions, RBAC configuration
   - Models: 3 (Role, Permission, RolePermission)
   - Dependencies: authority, accounts
   - Migrations: 1
   - Status: ✓ Has tests (21 tests)
   - Deployment time: ~2 hours

6. **settings.vocabulary** - Label/text configuration
   - Dependencies: core
   - Status: ✓ Has tests (16 tests)
   - Deployment time: ~1 hour

7. **settings.branding** - Brand configuration per tenant
   - Models: 1
   - Dependencies: core
   - Status: ✓ Has tests (61 tests)
   - Deployment time: ~2 hours

**Phase 1 Summary:**
- Effort: 15-17 hours
- Risk Level: MEDIUM-HIGH (affects entire system)
- Go/No-Go Criteria:
  - All migrations apply cleanly
  - User creation tests pass
  - RBAC tests pass
  - Tenant isolation verified
  - Middleware integration working

---

### Phase 2: USER & MEMBER MANAGEMENT (Week 1-2)

**Objective:** Enable user authentication and member entity management

**Apps to Deploy (in order):**

1. **members** - Member model (core business entity)
   - Models: 1 (Member)
   - Dependencies: core.Tenant
   - Migrations: 4
   - Status: ✓ Has tests (22 tests)
   - Deployment time: ~2-3 hours

2. **apps/audit** - Audit logging
   - Models: 1
   - Dependencies: core
   - Status: ✓ Has tests (8 tests)
   - Deployment time: ~1-2 hours

3. **apps/monitoring** - System monitoring
   - Dependencies: None
   - Status: ✓ Has tests
   - Deployment time: ~1 hour

**Phase 2 Summary:**
- Effort: 6-7 hours
- Risk Level: LOW
- Go/No-Go Criteria:
  - Member CRUD operations work
  - Audit logging captures events
  - Multi-tenant isolation verified

---

### Phase 3: BUSINESS SESSIONS & BOOKINGS (Week 2)

**Objective:** Enable session/class management and member booking/attendance

**Apps to Deploy (in order):**

1. **apps/sessions** - Session types, templates, schedules, instances
   - Models: 1+ (SessionType, SessionTemplate, SessionSchedule, SessionInstance)
   - Dependencies: core.Tenant, members.Member
   - Migrations: 9
   - Status: ✓ Has tests
   - Deployment time: ~3-4 hours

2. **apps/platform_sessions** - Alternative/complementary sessions module
   - Dependencies: core.Tenant, members.Member, sessions
   - Migrations: 2
   - Status: ❌ NO TESTS (CRITICAL)
   - Deployment time: ~2-4 hours (+ test implementation)
   - ⚠️ MUST implement tests before production deployment

3. **apps/bookings** - Member booking sessions
   - Dependencies: sessions.SessionInstance, members.Member, core.Tenant
   - Migrations: 2
   - Status: ✓ Has tests (8 tests)
   - Deployment time: ~2 hours

4. **apps/attendance** - Attendance tracking
   - Dependencies: members.Member, sessions.SessionInstance, bookings.Booking
   - Migrations: 2
   - Status: ✓ Has tests
   - Deployment time: ~2 hours

**Phase 3 Summary:**
- Effort: 11-14 hours (+ platform_sessions tests)
- Risk Level: MEDIUM
- Go/No-Go Criteria:
  - Session creation and scheduling works
  - Booking workflow (member books → booking created)
  - Attendance capture and rollup works
  - Time-based validations enforced

---

### Phase 4: SUBSCRIPTION & FINANCIAL SYSTEMS (Week 2-3)

**Objective:** Enable membership subscriptions and payment processing

**Apps to Deploy (in order):**

1. **apps/memberships** - Member subscriptions/plans
   - Models: Multiple (Membership, MembershipTier, etc.)
   - Dependencies: members.Member, core.Tenant, settings
   - Migrations: 2
   - Status: ✓ Has tests (13 tests)
   - Deployment time: ~3-4 hours

2. **apps/renewals** - Subscription renewals
   - Dependencies: memberships.Membership
   - Migrations: 1
   - Status: ✓ Has tests (35 tests)
   - Deployment time: ~2-3 hours

3. **apps/payments** - Payment processing (CRITICAL)
   - Models: 1+ (Payment)
   - Dependencies: members.Member, core.Tenant, settings
   - Migrations: 9
   - Services: PaymentService (Razorpay integration)
   - Status: ✓ Has tests (23 tests)
   - Deployment time: ~5-6 hours
   - ⚠️ CRITICAL: Requires Razorpay configuration, webhook setup

4. **apps/revenue** - Revenue tracking
   - Models: 2 (Revenue, RevenueAllocation)
   - Dependencies: members.Member
   - Migrations: 3
   - Status: ✓ Has tests (17 tests)
   - Deployment time: ~2-3 hours

5. **apps/expenses** - Expense tracking
   - Dependencies: members.Member, verticals.Vertical
   - Migrations: 2
   - Status: ❌ NO TESTS (CRITICAL)
   - Deployment time: ~3-4 hours (+ test implementation)
   - ⚠️ MUST implement tests before production

6. **apps/payouts** - Payout processing
   - Dependencies: verticals.Vertical
   - Migrations: 2
   - Status: ❌ NO TESTS (CRITICAL)
   - Deployment time: ~3-4 hours (+ test implementation)
   - ⚠️ MUST implement tests before production

**Phase 4 Summary:**
- Effort: 21-25 hours (+ test implementation for expenses/payouts)
- Risk Level: HIGH (financial data critical)
- Go/No-Go Criteria:
  - Membership signup/activation works
  - Payment processing works (test mode)
  - Renewal system functions correctly
  - Revenue tracking accurate
  - Financial reports correct
  - No orphaned transactions
  - Data integrity constraints enforced

