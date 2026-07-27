# Modular Deployment Quick Start Guide

## Overview

This guide helps you deploy the Setu SaaS platform with different feature combinations to different studios.

---

## 5-Minute Quick Start

### 1. Choose Your Scenario

| Scenario | Use Case | Modules | Time |
|----------|----------|---------|------|
| **Full Platform** | Complete yoga studio system | All 7 | 120-180m |
| **CRM-Only** | Sales & lead management | core + communication | 30-45m |
| **Fitness Studio** | Classes & bookings & payments | core + fitness + financial | 60-90m |
| **Academy** | Online learning | core + learning + communication | 45-60m |
| **WhatsApp-Only** | Messaging only | core + communication | 20-30m |
| **Financial-Only** | Payments & reporting | core + financial | 25-40m |

### 2. Set Deployment Scenario

```bash
export DEPLOYMENT_SCENARIO=crm_only
# or
export DEPLOYMENT_SCENARIO=fitness_only
# or
export DEPLOYMENT_SCENARIO=full_platform
```

### 3. Run Validation Gates

```bash
# Full validation
python scripts/validate_deployment.py crm_only

# Quick validation
pytest -m critical --scenario=crm_only
```

### 4. Deploy

```bash
# Create backup
./scripts/backup_database.sh staging

# Run migrations
python manage.py migrate

# Run tests
pytest -m critical

# Deploy code
git push production main
```

### 5. Verify

```bash
# Post-deployment checks
python scripts/post_deployment_verify.py crm_only
```

---

## Detailed Deployment Process

### Step 1: Pre-Deployment Planning (5 min)

1. **Choose scenario** from table above
2. **Review checklist** in `/deployment/checklists/pre_deployment_checklist.md`
3. **Get approvals** from tech lead and business owner

### Step 2: Dependency Validation (5 min)

```bash
# Validate all dependencies are met
python scripts/validate_deployment.py $SCENARIO

# Expected output:
# ✅ Dependency Check passed
# ✅ Circular Dependency Check passed
# ✅ Configuration Check passed
# ✅ Database Check passed
# ✅ Security Check passed
```

### Step 3: Test Coverage Validation (15 min)

```bash
# Run all tests for your scenario
pytest -m "critical or scenario_$SCENARIO" -v

# For CRM-only:
pytest -m "critical or scenario_crm_only" -v

# Expected: All tests passing, 85%+ coverage
```

### Step 4: Database Backup (5 min)

```bash
# Create backup
./scripts/backup_database.sh staging

# Verify backup
ls -lh backups/database_*.sql.gz
```

### Step 5: Migrations (10 min)

```bash
# Run migrations
python manage.py migrate

# Check for pending migrations
python manage.py showmigrations
```

### Step 6: Code Deployment (5 min)

```bash
# Push code
git push production main

# Restart services (run on server)
systemctl restart django-app
systemctl restart celery
```

### Step 7: Post-Deployment Verification (10 min)

```bash
# Run health checks
python scripts/post_deployment_verify.py $SCENARIO

# Smoke tests
pytest -m smoke

# Check key operations
curl https://api.example.com/health/
```

### Step 8: Monitoring & Alerts (5 min)

```bash
# Enable monitoring
python scripts/enable_monitoring.py $SCENARIO

# Check logs
tail -f logs/django.log

# Verify alerts
# Check Datadog/NewRelic dashboard
```

---

## Scenario-Specific Guides

### Deploying CRM-Only

```bash
# Set scenario
export DEPLOYMENT_SCENARIO=crm_only

# Validate
python scripts/validate_deployment.py crm_only
# ✅ All checks should pass quickly

# Test
pytest -m "critical or scenario_crm_only" -v
# Expected: ~150 tests in ~10 minutes

# Deploy
./scripts/deploy_scenario.sh crm_only staging

# Verify
python scripts/post_deployment_verify.py crm_only
# Check that:
# - Users can login ✓
# - Communications send ✓
# - WhatsApp integration works ✓
# - Fitness URLs return 404 ✓
```

### Deploying Fitness Studio

```bash
# Set scenario
export DEPLOYMENT_SCENARIO=fitness_only

# Validate
python scripts/validate_deployment.py fitness_only
# ✅ Check includes PCI compliance

# Test
pytest -m "critical or scenario_fitness_only" -v
# Expected: ~400 tests in ~20 minutes

# Deploy
./scripts/deploy_scenario.sh fitness_only staging

# Verify specific features
# - Session creation ✓
# - Booking workflow ✓
# - Payment processing ✓
# - Attendance tracking ✓
# - CRM disabled (return 404) ✓
```

### Deploying Full Platform

```bash
# Set scenario
export DEPLOYMENT_SCENARIO=full_platform

# Validate
python scripts/validate_deployment.py full_platform
# ✅ All 7 modules present

# Test
pytest -m "critical or scenario_full_platform" -v
# Expected: ~1000 tests in ~35 minutes
# This is CRITICAL - don't skip

# Deploy
./scripts/deploy_scenario.sh full_platform production
# Takes 2-3 hours with all validations

# Verify all features
# - Fitness operations ✓
# - Payment processing ✓
# - Communications ✓
# - Assessments ✓
# - Reporting ✓
# - Analytics ✓
```

---

## Troubleshooting

### Dependency Error
```
❌ Module 'fitness_studio' requires 'user_management'

Solution:
- Add user_management module
- Or choose different scenario (fitness_only already includes it)
```

### Test Coverage Too Low
```
❌ Coverage 78% < minimum 85%

Solution:
- Only deploy if you've fixed the missing coverage
- Can override with: --cov-fail-under=70
```

### Database Migration Pending
```
❌ Pending migrations exist

Solution:
- Run: python manage.py migrate
- Verify: python manage.py showmigrations
```

### WhatsApp Not Working
```
✅ Tests pass but WhatsApp integration fails

Solution:
- Check WHATSAPP_API_TOKEN configured
- Verify webhook URL accessible
- Check logs: tail logs/whatsapp.log
```

### Payments Not Processing
```
✅ Tests pass but payments fail in production

Solution:
- Verify PAYMENT_GATEWAY configured
- Check PCI compliance: openssl s_client -connect api.payment.com
- Verify webhook: curl -X POST https://yourapp.com/webhooks/payment
```

---

## Rollback Procedures

### Quick Rollback (< 5 minutes)

```bash
# If something is obviously broken:

# 1. Stop new requests
nginx off

# 2. Restore database
./scripts/restore_database.sh database_backup_YYYYMMDD.sql.gz

# 3. Revert code
git revert HEAD
git push production main

# 4. Restart
systemctl restart django-app

# 5. Verify
python scripts/post_deployment_verify.py $SCENARIO
```

### Detailed Rollback Plan

See: `/deployment/ROLLBACK_PROCEDURES.md`

---

## Common Commands

```bash
# Validate deployment
python scripts/validate_deployment.py full_platform

# Run critical tests only
pytest -m critical -v

# Run scenario-specific tests
pytest -m scenario_crm_only -v

# Run integration tests
pytest -m integration -v

# Check coverage
pytest --cov=apps --cov-report=html

# Deploy with validation
./scripts/deploy_scenario.sh crm_only staging

# Verify post-deployment
python scripts/post_deployment_verify.py crm_only

# Create backup
./scripts/backup_database.sh production

# Restore backup
./scripts/restore_database.sh database_backup_20240628.sql.gz

# Check deployment status
python scripts/deployment_status.py

# View logs
tail -f logs/django.log
tail -f logs/celery.log
tail -f logs/payment.log
```

---

## Success Criteria

✅ Deployment successful when:

- [ ] All validation gates passed
- [ ] Test suite passed (90%+ tests)
- [ ] Coverage ≥ 85%
- [ ] Health checks passing
- [ ] Smoke tests passing
- [ ] Key features working:
  - [ ] User login
  - [ ] Core operations (based on scenario)
  - [ ] Database connectivity
  - [ ] Payment processing (if financial)
  - [ ] Communications (if enabled)
- [ ] Monitoring & alerts active
- [ ] Logs clean (no errors/warnings)
- [ ] Performance acceptable
- [ ] Team notified

---

## Getting Help

**Questions?**
- Docs: See `/deployment/` directory
- Scripts: See `scripts/` directory
- Code: See module configs in `config/deployments/`

**Issues?**
- Check logs: `tail -f logs/*.log`
- Run validation: `python scripts/validate_deployment.py`
- Post in #deployments Slack channel

**Emergency?**
- Call on-call: `grep ONCALL ops/contacts.txt`
- Rollback immediately: `./scripts/rollback.sh`
- Post mortem in 24h

---

## Module Reference

### Core Infrastructure (Required)
- core: Multi-tenant foundation
- tenants: Tenant management
- accounts: User authentication
- authority: Role-based access control
- audit: Activity logging (optional)

### User Management
- memberships: Member types & lifecycle
- platform_sessions: Session management
- activity: Activity tracking
- lifecycles: Member lifecycle stages

### Fitness Studio
- sessions: Class scheduling
- bookings: Booking management
- attendance: Attendance tracking
- catalog: Course catalog
- verticals: Studio types

### Financial
- payments: Payment processing
- revenue: Revenue tracking
- expenses: Expense management
- payouts: Payout management
- renewals: Membership renewals

### Communication
- communications: Message templates
- settings.whatsapp: WhatsApp config
- engagement: Message delivery & retry
- actions: Next-best-action engine

### Analytics & Reporting
- analytics: Dashboards
- reporting: Financial reports (GST, P&L)
- documents: Document generation
- dashboard: Admin dashboard

### Learning & Assessment
- assessments: Student assessments
- intake: Intake forms
- enrollments: Course enrollments

---

**Quick Links:**
- Full Documentation: `MODULAR_PACKAGING_STRATEGY.md`
- Deployment Checklist: `/deployment/checklists/pre_deployment_checklist.md`
- Module Catalog: `/deployment/MODULE_CATALOG.md`
- Testing Guide: `/deployment/TESTING_GUIDE.md`
- Rollback Guide: `/deployment/ROLLBACK_PROCEDURES.md`
