# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-tenant SaaS platform for fitness/gym/wellness businesses. Built with Django 6 + DRF, PostgreSQL. Core features: membership management, session booking, attendance tracking, CRM pipeline, and role-based access control — all tenant-isolated in a single database.

## Development Setup

```bash
# Start PostgreSQL
docker-compose up -d

# Run dev server
python manage.py runserver

# Apply migrations
python manage.py migrate
```

Database: PostgreSQL on `localhost:5433` (not default 5432). Credentials and settings are hardcoded in `config/settings/base.py` — no `.env` file required for local dev.

## Commands

```bash
# Run all tests
python manage.py test

# Run a specific app's tests
python manage.py test apps.accounts

# Run a specific test class/method
python manage.py test apps.bookings.tests.BookingTestCase.test_create_booking

# Run lifecycle automation manually
python manage.py <lifecycle_command>  # see apps/lifecycles/management/commands/
```

## Architecture

### Multi-Tenancy

Every tenant-scoped model inherits from `TenantAwareModel` (`apps/core/models.py`). This base class:
- Provides a `TenantManager` on `objects` that auto-filters to the current tenant (set by `TenantMiddleware` on `request.tenant`)
- Exposes `base_objects` for unfiltered cross-tenant queries (admin/platform use only)
- Soft-deletes via `is_deleted` flag — never hard-deletes tenant data

`TenantMiddleware` resolves tenant from the authenticated user and attaches it to the request. Platform admins (`user.platform_admin = True`) have no tenant and bypass tenant filtering.

### RBAC

`User` → `Role` → `RolePermission` → `PermissionAction`

- `PermissionAction`: Global permission definitions in `module:action` format
- `RolePermission`: Maps roles to permitted actions with scope (`ANY` or `OWN`)
- Tenant staff must have both a tenant and a role; platform admins have neither

### Membership Lifecycle

`MembershipPlan` (plan template) → `Membership` (member subscription)

- Plan types: `FIXED` (date-range), `CLASS_PACK` (session count)
- `remaining_sessions` on Membership tracks usage for CLASS_PACK plans
- Lifecycle management jobs (`apps/lifecycles/`) auto-expire memberships and update statuses

### Session → Booking → Attendance Flow

```
SessionType → SessionInstance → Booking → Attendance
```

- `SessionInstance`: A specific scheduled occurrence with capacity limits
- `Booking`: Member reservation (pending → confirmed → cancelled)
- `Attendance`: Marks presence; `present` status auto-decrements `remaining_sessions` and validates active membership

### Key Apps

| App | Purpose |
|-----|---------|
| `apps/core` | `BaseModel`, `TenantAwareModel`, `TenantManager`, middleware |
| `apps/accounts` | Custom `User` model (email-based auth) |
| `apps/authority` | Roles and permission matrix |
| `apps/tenants` | `Tenant` model and tenant services |
| `apps/memberships` | `MembershipPlan`, `Membership`, usage tracking |
| `apps/platform_sessions` | `SessionType`, `SessionInstance` |
| `apps/bookings` | `Booking` model and booking service |
| `apps/attendance` | Attendance engine (bulk API, session codes, location) |
| `apps/lifecycles` | Automated membership status management |
| `apps/dashboard` | Widget engine aggregating data across modules |
| `crm` | `Lead`, `Deal`, `LeadStage` CRM pipeline |
| `members` | `Member` model (the person, separate from `User`) |
| `platform_core` | Platform-admin-only management layer |

### API Layer

DRF with routers in `config/urls.py`. ViewSets use DRF's standard router conventions. Pagination defaults to 10 items. Serializers are co-located in each app (`serializers.py`). Business logic lives in `services/` subdirectories (e.g., `apps/bookings/services/booking_service.py`), not in views or models.

### Settings

Split settings in `config/settings/`: `base.py` → `development.py` / `production.py`. `DJANGO_SETTINGS_MODULE` defaults to development. Timezone: `Asia/Kolkata`.
