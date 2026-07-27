# Strategy B Execution Roadmap: Automated Tests → Setu → Expand

**Document Version:** 1.0  
**Last Updated:** June 28, 2026  
**Timeline:** 10-14 weeks (70 days)  
**Status:** Ready for execution  

---

## TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [Phase 1: Test Infrastructure (Week 1-2)](#phase-1-test-infrastructure-week-1-2)
3. [Phase 2: Exam System Development (Week 3-8)](#phase-2-exam-system-development-week-3-8)
4. [Phase 3: Staging & Testing (Week 9)](#phase-3-staging--testing-week-9)
5. [Phase 4: Deploy to Setu (Week 10)](#phase-4-deploy-to-setu-week-10)
6. [Phase 5: Iterate & Monitor (Week 11-12)](#phase-5-iterate--monitor-week-11-12)
7. [Phase 6: Expand to Other Gyms (Week 13-14)](#phase-6-expand-to-other-gyms-week-13-14)
8. [External Resources Readiness](#external-resources-readiness)
9. [Success Criteria & Metrics](#success-criteria--metrics)
10. [Risk Register & Mitigation](#risk-register--mitigation)

---

## EXECUTIVE SUMMARY

### Timeline Overview

```
Week 1-2   │ Test Infrastructure Setup
Week 3-8   │ Exam System Development (with TDD)
Week 9     │ Staging Environment & Final Testing
Week 10    │ Production Deployment to Setu Yoga Studio
Week 11-12 │ Monitor, Iterate, Gather Feedback
Week 13-14 │ Expand to 2-3 Additional Gym Customers
───────────┴──────────────────────────────────────
TOTAL: 70 days (10 weeks minimum, 14 weeks maximum)
```

### Resource Requirements

```
PERSONNEL:
├── 1 Full-stack Developer (primary)
├── 1 DevOps/Deployment Engineer (part-time, weeks 8-10)
└── 1 QA/Tester (optional, for staging validation)

INFRASTRUCTURE:
├── Current: PostgreSQL, Django, DRF (running)
├── New: GitHub Actions (free)
├── New: Sentry (error tracking, free tier available)
├── New: Testing tools (pytest, coverage, factory-boy)
└── New: Staging server (can be same as dev initially)

TIMELINE COMMITMENT:
├── Developer: 100% for weeks 1-10, 70% for weeks 11-14
├── Deployment: 10-15 hours per deployment (week 10)
└── Monitoring: 2 hours/day first month after deployment
```

### Success Criteria (Define Before Starting)

```
GO/NO-GO BEFORE PRODUCTION DEPLOYMENT:
├── ✅ 75%+ code coverage (automated tests)
├── ✅ All critical tests passing (multi-tenancy, auth, payments)
├── ✅ Staging deployment successful + stable for 48 hours
├── ✅ Setu team trained on new features
├── ✅ Database backup & rollback procedures tested
├── ✅ Error monitoring (Sentry) configured and tested
├── ✅ Load test passed (100 concurrent exams)
├── ✅ Security review passed (no data leaks, auth bypass)
├── ✅ Performance acceptable (exam start < 2 seconds)
└── ✅ Rollback procedure documented and tested
```

---

## PHASE 1: TEST INFRASTRUCTURE (Week 1-2)

### Objectives
- Set up pytest + testing framework
- Write 50-70 critical tests for existing platform
- Configure CI/CD pipeline
- Establish testing standards for exam system

### Week 1 (Days 1-5): Setup & Initial Tests

#### Day 1-2: Environment Setup

**Prerequisites:**
```
├── ✅ Python 3.10+ (verify: python --version)
├── ✅ Django 6.0+ (verify: python -c "import django; print(django.VERSION)")
├── ✅ PostgreSQL running (verify: psql -U postgres -d saas_platform_dev)
└── ✅ Git repository with proper .gitignore
```

**Checklist:**

```
MONDAY (Day 1):
─────────────
☐ Create new branch: git checkout -b feature/test-suite-setup
☐ Install testing packages:
  pip install pytest==7.4.0
  pip install pytest-django==4.5.2
  pip install pytest-cov==4.1.0
  pip install factory-boy==3.3.0
  pip install faker==19.0.0
  
☐ Create pytest.ini configuration file:
  [pytest]
  DJANGO_SETTINGS_MODULE = config.settings.development
  python_files = tests.py test_*.py *_tests.py
  addopts = --cov=apps --cov=crm --cov=members --cov-report=html --cov-report=term-missing
  testpaths = tests

☐ Create tests/ directory structure:
  tests/
  ├── __init__.py
  ├── conftest.py (fixtures & setup)
  ├── factories.py (factory-boy models)
  ├── test_auth.py
  ├── test_multi_tenancy.py
  ├── test_memberships.py
  ├── test_attendance.py
  ├── test_payments.py
  ├── test_rbac.py
  └── test_communications.py

☐ Create conftest.py with pytest fixtures:
  @pytest.fixture
  def tenant(db):
      return Tenant.objects.create(name="Test Gym")
  
  @pytest.fixture
  def user(db, tenant):
      return User.objects.create_user(
          email="user@test.com",
          password="Test@1234",
          tenant=tenant
      )

☐ Run initial test (should pass empty):
  pytest tests/ -v

TUESDAY (Day 2):
──────────────
☐ Create factories.py for test data generation:
  class TenantFactory(factory.django.DjangoModelFactory):
      class Meta:
          model = Tenant
      name = factory.Faker('company')
      subdomain = factory.Faker('slug')
  
  class UserFactory(factory.django.DjangoModelFactory):
      class Meta:
          model = User
      email = factory.Faker('email')
      first_name = factory.Faker('first_name')
      tenant = factory.SubFactory(TenantFactory)

☐ Verify factories work:
  pytest tests/test_factories.py -v

☐ Document testing patterns in README:
  cat > TESTING.md << 'EOF'
  # Testing Guide
  
  ## Running Tests
  pytest tests/ -v                    # Run all tests
  pytest tests/test_auth.py -v        # Run single file
  pytest tests/ --cov                 # With coverage
  
  ## Writing Tests
  Use factories for test data
  Use @pytest.fixture for reusable fixtures
  Use parametrize for multiple scenarios
  EOF

☐ Commit progress:
  git add tests/ pytest.ini conftest.py TESTING.md
  git commit -m "Setup pytest infrastructure with fixtures and factories"
```

#### Day 3-5: Write Critical Tests (Multi-Tenancy)

**Highest Priority: Multi-Tenancy Isolation (15 tests)**

```
WEDNESDAY (Day 3):
──────────────────
☐ Create test_multi_tenancy.py with 15 critical tests:

  # Test 1: User can only see own tenant's data
  def test_user_cannot_see_other_tenant_data(db):
      tenant1 = TenantFactory(name="Gym A")
      tenant2 = TenantFactory(name="Gym B")
      
      user1 = UserFactory(tenant=tenant1)
      user2 = UserFactory(tenant=tenant2)
      
      # Set request context for user1
      assert user1.tenant == tenant1
      assert user2.tenant == tenant2
      
      # User1's members should not include User2's data
      # (Implementation depends on your filter logic)
  
  # Test 2: Query filtering respects tenant
  def test_members_queryset_filtered_by_tenant(db):
      tenant1 = TenantFactory()
      tenant2 = TenantFactory()
      
      member1 = MemberFactory(tenant=tenant1)
      member2 = MemberFactory(tenant=tenant2)
      
      members_t1 = Member.base_objects.filter(tenant=tenant1)
      members_t2 = Member.base_objects.filter(tenant=tenant2)
      
      assert member1 in members_t1
      assert member2 not in members_t1
  
  # Test 3: Membership data isolated
  def test_memberships_isolated_by_tenant(db):
      tenant1 = TenantFactory()
      tenant2 = TenantFactory()
      
      member1 = MemberFactory(tenant=tenant1)
      member2 = MemberFactory(tenant=tenant2)
      
      plan1 = MembershipPlanFactory(tenant=tenant1)
      plan2 = MembershipPlanFactory(tenant=tenant2)
      
      membership1 = MembershipFactory(member=member1, plan=plan1)
      membership2 = MembershipFactory(member=member2, plan=plan2)
      
      # Verify isolation
      t1_memberships = Membership.base_objects.filter(tenant=tenant1)
      assert membership1 in t1_memberships
      assert membership2 not in t1_memberships
  
  # Test 4: Attendance isolated
  def test_attendance_isolated_by_tenant(db):
      # Similar pattern...
  
  # ... 11 more tests covering all major models

☐ Run tests:
  pytest tests/test_multi_tenancy.py -v
  
  Expected: Some might fail (if existing code not fully isolated)
  Action: Fix the code, not the tests!

THURSDAY (Day 4):
─────────────────
☐ Create test_auth.py with 10 tests:
  - User login success
  - User login with wrong password fails
  - User registration
  - Email activation
  - Token generation
  - Token validation
  - Token expiration
  - Multi-factor auth (if applicable)
  - Password reset flow
  - Session timeout

☐ Create test_rbac.py with 10 tests:
  - User can access allowed module
  - User blocked from disallowed module
  - Role creation
  - Permission assignment
  - Role inheritance
  - Admin bypass rules
  - Scope (ANY vs OWN) enforcement
  - Permission removal
  - Multiple roles per user
  - Dynamic permission checks

FRIDAY (Day 5):
───────────────
☐ Create test_memberships.py with 10 tests:
  - Membership creation
  - Status transitions (pending→active→expired)
  - Partial payment handling
  - CLASS_PACK vs DURATION types
  - Remaining sessions decrement
  - Membership expiration
  - Grace period handling
  - Renewal logic
  - Cancellation
  - Refund handling

☐ Coverage report:
  pytest tests/ --cov=apps --cov=crm --cov=members --cov-report=html
  open htmlcov/index.html
  
  Target: 50%+ coverage after Week 1

☐ Commit all tests:
  git add tests/test_*.py
  git commit -m "Add 45 critical tests for multi-tenancy, auth, RBAC, memberships"
```

### Week 2 (Days 6-10): Expand Tests & Set Up CI/CD

#### Day 6-7: Add Remaining Critical Tests

```
MONDAY (Day 6):
───────────────
☐ Create test_attendance.py with 8 tests:
  - Attendance marking
  - Session code validation
  - Capacity enforcement
  - Status transitions (booked→present→absent)
  - Remaining sessions decrement
  - Multiple attendances per session
  - Attendance history
  - Attendance report generation

☐ Create test_payments.py with 8 tests:
  - Payment creation
  - Payment status transitions (unpaid→partial→paid)
  - Invoice generation
  - Receipt generation
  - Refund processing
  - Tax calculation
  - Currency handling
  - Payment reconciliation

TUESDAY (Day 7):
────────────────
☐ Create test_communications.py with 5 tests:
  - Email sending
  - Email template rendering
  - SMS sending
  - WhatsApp message sending
  - Communication log creation

☐ Create test_api.py with 10 tests:
  - API authentication (JWT/token)
  - API error responses (400, 403, 404, 500)
  - Pagination
  - Filtering
  - Sorting
  - Rate limiting (if applicable)
  - CORS headers
  - Request validation
  - Response format validation
  - Serializer validation

☐ Total tests now: 100+ tests
☐ Coverage target: 70%+ on critical paths

☐ Run full test suite:
  pytest tests/ -v --cov=apps --cov=crm --cov=members

☐ Fix any failing tests (prioritize by criticality)
```

#### Day 8-10: CI/CD Setup

```
WEDNESDAY (Day 8):
───────────────────
☐ Set up GitHub Actions CI/CD:
  Create: .github/workflows/tests.yml
  
  name: Run Tests
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      services:
        postgres:
          image: postgres:15
          env:
            POSTGRES_PASSWORD: postgres
          options: >-
            --health-cmd pg_isready
            --health-interval 10s
            --health-timeout 5s
            --health-retries 5
      steps:
        - uses: actions/checkout@v3
        - name: Set up Python
          uses: actions/setup-python@v4
          with:
            python-version: '3.10'
        - name: Install dependencies
          run: |
            pip install -r requirements.txt
            pip install pytest pytest-django pytest-cov
        - name: Run tests
          run: pytest tests/ -v --cov=apps --cov=crm --cov=members --cov-report=xml
        - name: Upload coverage
          uses: codecov/codecov-action@v3
          with:
            files: ./coverage.xml

☐ Verify GitHub Actions runs on next push:
  git push origin feature/test-suite-setup
  Check: https://github.com/[repo]/actions

THURSDAY (Day 9):
──────────────────
☐ Set up code coverage tracking:
  - Sign up for codecov.io (free)
  - Connect to GitHub repository
  - Add codecov.io badge to README

☐ Create pre-commit hook to run tests locally:
  Create: .git/hooks/pre-commit
  
  #!/bin/bash
  pytest tests/ -v
  if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
  fi

☐ Document test running in CLAUDE.md:
  # Running Tests
  pytest tests/ -v                    # Run all
  pytest tests/test_auth.py -v        # Run single file
  pytest tests/ --cov                 # With coverage

FRIDAY (Day 10):
────────────────
☐ Final audit of test suite:
  - All critical tests passing? YES/NO
  - Coverage >= 70% on critical paths? YES/NO
  - CI/CD running successfully? YES/NO
  - Pre-commit hook working? YES/NO

☐ Create test documentation:
  Create: docs/TESTING.md with:
  - Test structure overview
  - How to run tests
  - How to write new tests
  - Fixtures available
  - Factories available
  - Common test patterns

☐ Commit and create pull request:
  git add .github/ docs/TESTING.md
  git commit -m "Setup GitHub Actions CI/CD pipeline with automated test running"
  git push origin feature/test-suite-setup
  
  Create PR: "Feat: Automated Test Suite & CI/CD Pipeline"

☐ Review & merge PR:
  ✅ Ensure all checks pass
  ✅ All tests run successfully
  ✅ Coverage report generated
  ✅ Merge to main branch
```

### Phase 1 Completion Checklist

```
WEEK 1-2 COMPLETION CRITERIA:
─────────────────────────────
☐ 100+ automated tests written
☐ 70%+ code coverage on critical modules
☐ All tests passing locally
☐ GitHub Actions CI/CD configured
☐ Tests run automatically on every push
☐ Pre-commit hooks working
☐ Team trained on test structure
☐ Documentation complete
☐ Test patterns established for exam system
└── Phase 1 COMPLETE when ALL boxes checked

METRICS TO TRACK:
├── Number of tests: Target 100+ ✅
├── Code coverage: Target 70%+ ✅
├── Test pass rate: Target 100% ✅
├── CI/CD execution time: Target < 5 minutes
└── False positives: Target 0%

HANDOFF TO PHASE 2:
├── All PR merged to main
├── Test suite running in GitHub Actions
├── Team familiar with test patterns
└── Ready to start exam system development with TDD
```

---

## PHASE 2: EXAM SYSTEM DEVELOPMENT (Week 3-8)

### Objectives
- Implement 7 core models for exam system
- Implement 5 service classes with business logic
- Implement 5 API ViewSets with complete CRUD operations
- Maintain 75%+ code coverage throughout
- TDD approach: Write tests first, implement second

### Week 3 (Days 11-15): Models & Unit Tests

#### Architecture Overview

```
DATABASE MODELS (7 total):
├── Assessment (exam template)
│   ├── id (UUID)
│   ├── tenant_id
│   ├── name
│   ├── description
│   ├── passing_score (e.g., 60)
│   ├── total_questions (e.g., 20)
│   ├── duration_minutes (e.g., 60)
│   ├── difficulty_distribution (JSON: {easy: 0.4, medium: 0.4, hard: 0.2})
│   ├── status (draft/published)
│   └── created_at, updated_at
│
├── AssessmentQuestion (join: Assessment → Question)
│   ├── id (UUID)
│   ├── assessment_id
│   ├── question_id
│   ├── display_order
│   └── created_at
│
├── Question (question bank)
│   ├── id (UUID)
│   ├── tenant_id
│   ├── text
│   ├── topic (e.g., "asana", "pranayama", "philosophy")
│   ├── difficulty (easy/medium/hard)
│   ├── explanation (optional)
│   ├── created_by (user_id)
│   ├── status (active/archived)
│   └── created_at, updated_at
│
├── QuestionOption (4 per question, 1 correct)
│   ├── id (UUID)
│   ├── question_id
│   ├── text
│   ├── display_order (A/B/C/D)
│   ├── is_correct (boolean)
│   └── created_at
│
├── StudentAssessment (enrollment in exam)
│   ├── id (UUID)
│   ├── student_id (Member)
│   ├── assessment_id
│   ├── tenant_id
│   ├── status (eligible/scheduled/in_progress/completed)
│   ├── scheduled_date
│   ├── scheduled_time
│   ├── trigger_condition (e.g., "attended_20_classes")
│   ├── max_attempts (default 1)
│   └── created_at, updated_at
│
├── AssessmentAttempt (each exam attempt)
│   ├── id (UUID)
│   ├── student_assessment_id
│   ├── student_id
│   ├── assessment_id
│   ├── tenant_id
│   ├── status (in_progress/submitted)
│   ├── started_at
│   ├── submitted_at
│   ├── time_spent_seconds
│   ├── answers_count
│   └── created_at
│
├── AttemptAnswer (each answer to question)
│   ├── id (UUID)
│   ├── attempt_id
│   ├── question_id
│   ├── selected_option_id (QuestionOption)
│   ├── is_correct (computed at submit time)
│   ├── points_earned (computed at submit time)
│   └── answered_at
│
└── AssessmentScore (result after exam submitted)
    ├── id (UUID)
    ├── student_id
    ├── attempt_id
    ├── assessment_id
    ├── tenant_id
    ├── total_points
    ├── max_points
    ├── percentage
    ├── status (pass/fail)
    ├── breakdown_by_topic (JSON)
    ├── certificate_generated (boolean)
    ├── certificate_id (Document UUID, nullable)
    └── created_at

RELATIONSHIPS:
Assessment ──┬─→ AssessmentQuestion ──→ Question
             ├─→ StudentAssessment ──→ AssessmentAttempt ──→ AttemptAnswer
             └─→ StudentAssessment ──→ AssessmentScore

TOTAL FIELDS: ~120 fields across 8 models
MIGRATIONS: 2-3 migrations
```

#### Day 11: Design & Models

```
MONDAY (Day 11):
────────────────
☐ Create apps/assessments/ app:
  mkdir -p apps/assessments
  mkdir -p apps/assessments/migrations
  mkdir -p apps/assessments/services
  mkdir -p apps/assessments/tests
  
  touch apps/assessments/__init__.py
  touch apps/assessments/models.py
  touch apps/assessments/admin.py
  touch apps/assessments/serializers.py
  touch apps/assessments/views.py
  touch apps/assessments/urls.py
  touch apps/assessments/services/__init__.py

☐ Add to INSTALLED_APPS in config/settings/base.py:
  INSTALLED_APPS = [
      ...
      'apps.assessments',
  ]

☐ Create models.py with Assessment model:
  from apps.core.models import TenantAwareModel
  
  class Assessment(TenantAwareModel):
      STATUS_CHOICES = [
          ('draft', 'Draft'),
          ('published', 'Published'),
          ('archived', 'Archived'),
      ]
      
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      name = models.CharField(max_length=200)
      description = models.TextField(blank=True)
      passing_score = models.PositiveIntegerField(default=60)
      total_questions = models.PositiveIntegerField(default=20)
      duration_minutes = models.PositiveIntegerField(default=60)
      
      difficulty_distribution = models.JSONField(
          default=dict,
          help_text="e.g., {'easy': 0.4, 'medium': 0.4, 'hard': 0.2}"
      )
      
      status = models.CharField(
          max_length=20,
          choices=STATUS_CHOICES,
          default='draft'
      )
      
      created_by = models.ForeignKey(
          settings.AUTH_USER_MODEL,
          on_delete=models.SET_NULL,
          null=True,
          blank=True
      )
      
      class Meta:
          ordering = ['-created_at']
      
      def __str__(self):
          return self.name

☐ Create Question model:
  class Question(TenantAwareModel):
      DIFFICULTY_CHOICES = [
          ('easy', 'Easy'),
          ('medium', 'Medium'),
          ('hard', 'Hard'),
      ]
      
      STATUS_CHOICES = [
          ('active', 'Active'),
          ('archived', 'Archived'),
      ]
      
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      text = models.TextField()
      topic = models.CharField(max_length=100)  # e.g., "asana", "pranayama"
      difficulty = models.CharField(
          max_length=20,
          choices=DIFFICULTY_CHOICES
      )
      explanation = models.TextField(blank=True)
      status = models.CharField(
          max_length=20,
          choices=STATUS_CHOICES,
          default='active'
      )
      created_by = models.ForeignKey(
          settings.AUTH_USER_MODEL,
          on_delete=models.SET_NULL,
          null=True, blank=True
      )
      
      class Meta:
          ordering = ['-created_at']
      
      def __str__(self):
          return self.text[:100]

☐ Create QuestionOption model:
  class QuestionOption(models.Model):
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      question = models.ForeignKey(
          Question,
          on_delete=models.CASCADE,
          related_name='options'
      )
      text = models.CharField(max_length=500)
      display_order = models.PositiveIntegerField()
      is_correct = models.BooleanField(default=False)
      
      class Meta:
          ordering = ['display_order']
          constraints = [
              UniqueConstraint(fields=['question', 'display_order'], name='unique_question_option_order'),
              # Ensure exactly one correct answer per question
          ]
      
      def __str__(self):
          return f"{self.question.id} - Option {self.display_order}"

☐ Create StudentAssessment model:
  class StudentAssessment(TenantAwareModel):
      STATUS_CHOICES = [
          ('eligible', 'Eligible'),
          ('scheduled', 'Scheduled'),
          ('in_progress', 'In Progress'),
          ('completed', 'Completed'),
          ('expired', 'Expired'),
      ]
      
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      student = models.ForeignKey(
          'members.Member',
          on_delete=models.CASCADE,
          related_name='assessments'
      )
      assessment = models.ForeignKey(
          Assessment,
          on_delete=models.CASCADE,
          related_name='student_assessments'
      )
      status = models.CharField(
          max_length=20,
          choices=STATUS_CHOICES,
          default='eligible'
      )
      scheduled_date = models.DateField(null=True, blank=True)
      scheduled_time = models.TimeField(null=True, blank=True)
      trigger_condition = models.CharField(
          max_length=100,
          blank=True,
          help_text="e.g., 'attended_20_classes' or 'days_elapsed_30'"
      )
      max_attempts = models.PositiveIntegerField(default=1)
      
      class Meta:
          unique_together = [['tenant', 'student', 'assessment']]
          ordering = ['scheduled_date', 'scheduled_time']
      
      def __str__(self):
          return f"{self.student.name} - {self.assessment.name}"

☐ Create AssessmentAttempt model:
  class AssessmentAttempt(TenantAwareModel):
      STATUS_CHOICES = [
          ('in_progress', 'In Progress'),
          ('submitted', 'Submitted'),
          ('graded', 'Graded'),
      ]
      
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      student_assessment = models.ForeignKey(
          StudentAssessment,
          on_delete=models.CASCADE,
          related_name='attempts'
      )
      student = models.ForeignKey(
          'members.Member',
          on_delete=models.CASCADE
      )
      assessment = models.ForeignKey(
          Assessment,
          on_delete=models.CASCADE
      )
      status = models.CharField(
          max_length=20,
          choices=STATUS_CHOICES,
          default='in_progress'
      )
      started_at = models.DateTimeField(auto_now_add=True)
      submitted_at = models.DateTimeField(null=True, blank=True)
      time_spent_seconds = models.PositiveIntegerField(default=0)
      answers_count = models.PositiveIntegerField(default=0)
      
      class Meta:
          ordering = ['-started_at']
      
      def __str__(self):
          return f"Attempt: {self.student.name} - {self.assessment.name}"

☐ Create AttemptAnswer model:
  class AttemptAnswer(TenantAwareModel):
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      attempt = models.ForeignKey(
          AssessmentAttempt,
          on_delete=models.CASCADE,
          related_name='answers'
      )
      question = models.ForeignKey(
          Question,
          on_delete=models.CASCADE
      )
      selected_option = models.ForeignKey(
          QuestionOption,
          on_delete=models.SET_NULL,
          null=True, blank=True,
          related_name='attempt_answers'
      )
      is_correct = models.BooleanField(default=False)
      points_earned = models.PositiveIntegerField(default=0)
      answered_at = models.DateTimeField(auto_now_add=True)
      
      class Meta:
          unique_together = [['attempt', 'question']]
          ordering = ['answered_at']
      
      def __str__(self):
          return f"{self.attempt.id} - Q{self.question.id}"

☐ Create AssessmentScore model:
  class AssessmentScore(TenantAwareModel):
      STATUS_CHOICES = [
          ('pass', 'Pass'),
          ('fail', 'Fail'),
      ]
      
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      student = models.ForeignKey(
          'members.Member',
          on_delete=models.CASCADE,
          related_name='assessment_scores'
      )
      attempt = models.OneToOneField(
          AssessmentAttempt,
          on_delete=models.CASCADE,
          related_name='score'
      )
      assessment = models.ForeignKey(
          Assessment,
          on_delete=models.CASCADE
      )
      total_points = models.PositiveIntegerField(default=0)
      max_points = models.PositiveIntegerField(default=100)
      percentage = models.DecimalField(
          max_digits=5,
          decimal_places=2,
          default=0
      )
      status = models.CharField(
          max_length=20,
          choices=STATUS_CHOICES
      )
      breakdown_by_topic = models.JSONField(
          default=dict,
          help_text="e.g., {'asana': {'correct': 5, 'total': 10}, ...}"
      )
      certificate_generated = models.BooleanField(default=False)
      certificate = models.OneToOneField(
          'documents.Document',
          on_delete=models.SET_NULL,
          null=True, blank=True,
          related_name='assessment_score'
      )
      
      class Meta:
          ordering = ['-created_at']
      
      def __str__(self):
          return f"{self.student.name} - {self.assessment.name}: {self.percentage}%"

☐ Create AssessmentQuestion model (join table):
  class AssessmentQuestion(models.Model):
      id = models.UUIDField(primary_key=True, default=uuid.uuid4)
      assessment = models.ForeignKey(
          Assessment,
          on_delete=models.CASCADE,
          related_name='assessment_questions'
      )
      question = models.ForeignKey(
          Question,
          on_delete=models.CASCADE
      )
      display_order = models.PositiveIntegerField()
      
      class Meta:
          ordering = ['display_order']
          unique_together = [['assessment', 'question']]
      
      def __str__(self):
          return f"{self.assessment.name} - Q{self.display_order}"

☐ Create migrations:
  python manage.py makemigrations assessments
  
  Expected: 0001_initial.py created

☐ Verify migrations:
  python manage.py migrate --plan
  
  Should show: assessments 0001

COMMIT:
  git add apps/assessments/
  git commit -m "Create Assessment models (7 models, initial migration)"
```

#### Day 12-15: Write Unit Tests for Models

```
TUESDAY (Day 12):
──────────────────
☐ Create apps/assessments/tests/__init__.py
☐ Create apps/assessments/tests/test_models.py
☐ Create factories for test data:

  from apps.assessments.models import *
  import factory
  
  class AssessmentFactory(factory.django.DjangoModelFactory):
      class Meta:
          model = Assessment
      tenant = factory.SubFactory(TenantFactory)
      name = factory.Faker('word')
      passing_score = 60
      total_questions = 20
      duration_minutes = 60
      status = 'published'
  
  class QuestionFactory(factory.django.DjangoModelFactory):
      class Meta:
          model = Question
      tenant = factory.SubFactory(TenantFactory)
      text = factory.Faker('sentence')
      topic = 'asana'
      difficulty = 'medium'
  
  class QuestionOptionFactory(factory.django.DjangoModelFactory):
      class Meta:
          model = QuestionOption
      question = factory.SubFactory(QuestionFactory)
      text = factory.Faker('sentence')
      display_order = factory.Sequence(lambda n: n + 1)
      is_correct = False

☐ Write 30 unit tests:

  Test Assessment Model (5 tests):
  ├── test_assessment_creation
  ├── test_assessment_name_required
  ├── test_assessment_defaults
  ├── test_assessment_status_choices
  └── test_assessment_string_representation
  
  Test Question Model (5 tests):
  ├── test_question_creation
  ├── test_question_difficulty_choices
  ├── test_question_topic_categorization
  ├── test_question_status_active_by_default
  └── test_question_string_representation
  
  Test QuestionOption Model (5 tests):
  ├── test_option_creation
  ├── test_option_is_correct_flag
  ├── test_option_display_order
  ├── test_unique_option_order_per_question
  └── test_option_string_representation
  
  Test StudentAssessment Model (5 tests):
  ├── test_student_assessment_creation
  ├── test_status_transitions
  ├── test_scheduled_date_nullable
  ├── test_unique_student_per_assessment
  └── test_string_representation
  
  Test AssessmentAttempt Model (5 tests):
  ├── test_attempt_creation
  ├── test_attempt_started_at_auto_set
  ├── test_attempt_status_in_progress_default
  ├── test_attempt_time_spent_tracking
  └── test_attempt_string_representation
  
  Test AssessmentScore Model (5 tests):
  ├── test_score_creation
  ├── test_score_calculation
  ├── test_score_pass_fail_logic
  ├── test_score_percentage_calculation
  └── test_certificate_link

WEDNESDAY-FRIDAY (Day 13-15):
────────────────────────────────
☐ Implement unit tests one category at a time
☐ Fix any validation issues in models
☐ Ensure all tests pass:
  pytest apps/assessments/tests/test_models.py -v
  
☐ Coverage check:
  pytest apps/assessments/tests/ --cov=apps.assessments
  
  Target: 85%+ coverage for assessments app

☐ Commit model tests:
  git add apps/assessments/tests/test_models.py
  git commit -m "Add 30 unit tests for Assessment models"
```

### Week 4 (Days 16-20): Services & Integration Tests

#### Day 16-17: Core Services

```
MONDAY-TUESDAY (Day 16-17):
───────────────────────────
☐ Create apps/assessments/services/assessment_service.py:

  from apps.assessments.models import *
  from django.utils import timezone
  from decimal import Decimal
  
  class AssessmentService:
      """Service for managing assessment lifecycle."""
      
      @staticmethod
      def create_assessment(tenant, name, description, passing_score, 
                           total_questions, duration_minutes):
          """Create a new assessment."""
          assessment = Assessment.objects.create(
              tenant=tenant,
              name=name,
              description=description,
              passing_score=passing_score,
              total_questions=total_questions,
              duration_minutes=duration_minutes,
              status='draft'
          )
          return assessment
      
      @staticmethod
      def publish_assessment(assessment):
          """Publish assessment (makes it available for students)."""
          assessment.status = 'published'
          assessment.save()
          return assessment
      
      @staticmethod
      def add_questions_to_assessment(assessment, question_ids):
          """Add questions to assessment with proper difficulty distribution."""
          AssessmentQuestion.objects.filter(assessment=assessment).delete()
          
          for order, q_id in enumerate(question_ids, start=1):
              AssessmentQuestion.objects.create(
                  assessment=assessment,
                  question_id=q_id,
                  display_order=order
              )
      
      @staticmethod
      def get_assessment_for_student(student, assessment_id):
          """Get assessment questions randomized by student."""
          # Implement question randomization logic here
          pass

☐ Create apps/assessments/services/grading_service.py:

  class GradingService:
      """Service for grading exams and calculating scores."""
      
      @staticmethod
      def grade_attempt(attempt):
          """Grade a submitted attempt and create score record."""
          answers = attempt.answers.all()
          total_points = 0
          max_points = attempt.assessment.total_questions * 5  # 5 points per question
          topic_breakdown = {}
          
          for answer in answers:
              # Check if answer is correct
              is_correct = answer.selected_option and answer.selected_option.is_correct
              points = 5 if is_correct else 0
              
              answer.is_correct = is_correct
              answer.points_earned = points
              answer.save()
              
              total_points += points
              
              # Track by topic
              topic = answer.question.topic
              if topic not in topic_breakdown:
                  topic_breakdown[topic] = {'correct': 0, 'total': 0}
              topic_breakdown[topic]['total'] += 1
              if is_correct:
                  topic_breakdown[topic]['correct'] += 1
          
          # Calculate percentage
          percentage = Decimal(total_points) / Decimal(max_points) * 100
          
          # Determine pass/fail
          status = 'pass' if percentage >= attempt.assessment.passing_score else 'fail'
          
          # Create score record
          score = AssessmentScore.objects.create(
              tenant=attempt.tenant,
              student=attempt.student,
              attempt=attempt,
              assessment=attempt.assessment,
              total_points=total_points,
              max_points=max_points,
              percentage=percentage,
              status=status,
              breakdown_by_topic=topic_breakdown
          )
          
          return score
      
      @staticmethod
      def calculate_score_breakdown(attempt):
          """Get detailed score breakdown."""
          # Implementation...
          pass

☐ Create apps/assessments/services/attempt_service.py:

  class AttemptService:
      """Service for managing exam attempts."""
      
      @staticmethod
      def start_attempt(student_assessment):
          """Start a new exam attempt."""
          attempt = AssessmentAttempt.objects.create(
              tenant=student_assessment.tenant,
              student=student_assessment.student,
              assessment=student_assessment.assessment,
              student_assessment=student_assessment,
              status='in_progress'
          )
          return attempt
      
      @staticmethod
      def save_answer(attempt, question_id, selected_option_id):
          """Save student's answer to a question."""
          answer, created = AttemptAnswer.objects.update_or_create(
              attempt=attempt,
              question_id=question_id,
              defaults={'selected_option_id': selected_option_id}
          )
          return answer
      
      @staticmethod
      def submit_attempt(attempt):
          """Submit exam and trigger grading."""
          attempt.submitted_at = timezone.now()
          attempt.status = 'submitted'
          attempt.time_spent_seconds = calculate_time_spent(attempt)
          attempt.answers_count = attempt.answers.count()
          attempt.save()
          
          # Grade the attempt
          score = GradingService.grade_attempt(attempt)
          
          # Generate certificate if passed
          if score.status == 'pass':
              CertificateService.generate_certificate(score)
          
          return score
      
      @staticmethod
      def get_current_attempt(student_assessment):
          """Get in-progress attempt or None."""
          return student_assessment.attempts.filter(
              status='in_progress'
          ).first()

☐ Create apps/assessments/services/certificate_service.py:

  from apps.documents.models import Document
  from apps.documents.services import DocumentService
  from reportlab.lib.pagesizes import letter
  from reportlab.pdfgen import canvas
  import io
  
  class CertificateService:
      """Service for generating exam certificates."""
      
      @staticmethod
      def generate_certificate(score):
          """Generate and save PDF certificate for passed exam."""
          if score.status != 'pass':
              return None
          
          # Create PDF content
          pdf_content = CertificateService.generate_pdf_content(score)
          
          # Create Document record
          document = Document.objects.create(
              tenant=score.tenant,
              person=score.student,
              document_type='exam_certificate',
              issued_date=timezone.now().date(),
              status='issued'
          )
          
          # Link to assessment score
          score.certificate = document
          score.certificate_generated = True
          score.save()
          
          # Save PDF file (implementation depends on file storage)
          # ...
          
          return document
      
      @staticmethod
      def generate_pdf_content(score):
          """Generate PDF content as bytes."""
          buffer = io.BytesIO()
          p = canvas.Canvas(buffer, pagesize=letter)
          
          # Add certificate design
          p.setFont("Helvetica-Bold", 28)
          p.drawString(100, 700, "Certificate of Completion")
          
          p.setFont("Helvetica", 14)
          p.drawString(100, 650, f"This certifies that {score.student.name}")
          p.drawString(100, 630, f"has successfully completed {score.assessment.name}")
          p.drawString(100, 610, f"with a score of {score.percentage}%")
          
          p.save()
          return buffer.getvalue()

☐ Create apps/assessments/services/question_service.py:

  class QuestionService:
      """Service for managing question bank."""
      
      @staticmethod
      def create_question(tenant, text, topic, difficulty, options, 
                         correct_option_index):
          """Create question with options."""
          question = Question.objects.create(
              tenant=tenant,
              text=text,
              topic=topic,
              difficulty=difficulty
          )
          
          for order, option_text in enumerate(options, start=1):
              QuestionOption.objects.create(
                  question=question,
                  text=option_text,
                  display_order=order,
                  is_correct=(order - 1 == correct_option_index)
              )
          
          return question
      
      @staticmethod
      def bulk_import_questions(tenant, questions_data):
          """Bulk import questions from CSV."""
          created_count = 0
          for row in questions_data:
              question = QuestionService.create_question(
                  tenant=tenant,
                  text=row['text'],
                  topic=row['topic'],
                  difficulty=row['difficulty'],
                  options=[row['option_a'], row['option_b'], 
                          row['option_c'], row['option_d']],
                  correct_option_index=row['correct_option_index']
              )
              created_count += 1
          
          return created_count
      
      @staticmethod
      def get_random_questions(assessment, difficulty):
          """Get random questions of specific difficulty for exam."""
          # Implementation...
          pass

☐ Update services/__init__.py:
  from .assessment_service import AssessmentService
  from .grading_service import GradingService
  from .attempt_service import AttemptService
  from .certificate_service import CertificateService
  from .question_service import QuestionService
  
  __all__ = [
      'AssessmentService',
      'GradingService',
      'AttemptService',
      'CertificateService',
      'QuestionService',
  ]

☐ Commit services:
  git add apps/assessments/services/
  git commit -m "Create 5 core services for assessment lifecycle"
```

#### Day 18-20: Integration Tests

```
WEDNESDAY-FRIDAY (Day 18-20):
────────────────────────────────
☐ Create apps/assessments/tests/test_services.py
☐ Write 40 integration tests:

  Test AssessmentService (8 tests):
  ├── test_create_assessment
  ├── test_publish_assessment
  ├── test_add_questions_to_assessment
  ├── test_assessment_requires_name
  ├── test_assessment_default_status_draft
  ├── test_assessment_validation
  ├── test_get_assessment_for_student
  └── test_assessment_multi_tenant_isolation
  
  Test GradingService (8 tests):
  ├── test_grade_attempt_all_correct
  ├── test_grade_attempt_all_wrong
  ├── test_grade_attempt_mixed
  ├── test_pass_fail_determination
  ├── test_percentage_calculation
  ├── test_topic_breakdown_calculation
  ├── test_score_creation
  └── test_score_saved_to_database
  
  Test AttemptService (8 tests):
  ├── test_start_attempt_creates_record
  ├── test_save_answer
  ├── test_answer_update
  ├── test_submit_attempt
  ├── test_submit_triggers_grading
  ├── test_submit_triggers_certificate
  ├── test_time_spent_calculation
  └── test_answers_count_accurate
  
  Test CertificateService (8 tests):
  ├── test_generate_certificate_on_pass
  ├── test_no_certificate_on_fail
  ├── test_certificate_pdf_generated
  ├── test_certificate_document_created
  ├── test_certificate_linked_to_score
  ├── test_certificate_filename
  └── test_certificate_multi_tenant
  
  Test QuestionService (8 tests):
  ├── test_create_question
  ├── test_create_question_with_options
  ├── test_correct_option_marked
  ├── test_bulk_import_questions
  ├── test_get_random_questions
  ├── test_difficulty_distribution
  └── test_question_validation

☐ Run all integration tests:
  pytest apps/assessments/tests/test_services.py -v
  
  Expected: 40/40 passing

☐ Coverage check:
  pytest apps/assessments/tests/ --cov=apps.assessments.services
  
  Target: 80%+ coverage

☐ Commit:
  git add apps/assessments/tests/test_services.py
  git commit -m "Add 40 integration tests for assessment services"
```

### Week 5 (Days 21-25): API ViewSets & API Tests

#### Day 21-22: ViewSets

```
MONDAY-TUESDAY (Day 21-22):
───────────────────────────
☐ Create apps/assessments/serializers.py:

  from rest_framework import serializers
  from apps.assessments.models import *
  
  class QuestionOptionSerializer(serializers.ModelSerializer):
      class Meta:
          model = QuestionOption
          fields = ['id', 'text', 'display_order']
          # Don't expose is_correct in API (would let students see answers)
  
  class QuestionSerializer(serializers.ModelSerializer):
      options = QuestionOptionSerializer(many=True, read_only=True)
      
      class Meta:
          model = Question
          fields = ['id', 'text', 'topic', 'difficulty', 'options']
  
  class AssessmentSerializer(serializers.ModelSerializer):
      class Meta:
          model = Assessment
          fields = ['id', 'name', 'description', 'passing_score', 
                   'total_questions', 'duration_minutes', 'status']
  
  class StudentAssessmentSerializer(serializers.ModelSerializer):
      assessment = AssessmentSerializer(read_only=True)
      
      class Meta:
          model = StudentAssessment
          fields = ['id', 'assessment', 'status', 'scheduled_date', 
                   'scheduled_time']
  
  class AttemptAnswerSubmitSerializer(serializers.Serializer):
      """Serializer for submitting an answer."""
      question_id = serializers.UUIDField()
      selected_option_id = serializers.UUIDField(required=False, allow_null=True)
  
  class AttemptSerializer(serializers.ModelSerializer):
      class Meta:
          model = AssessmentAttempt
          fields = ['id', 'status', 'started_at', 'time_spent_seconds']
  
  class AssessmentScoreSerializer(serializers.ModelSerializer):
      breakdown_by_topic = serializers.JSONField(read_only=True)
      
      class Meta:
          model = AssessmentScore
          fields = ['id', 'total_points', 'max_points', 'percentage', 
                   'status', 'breakdown_by_topic', 'certificate_generated']

☐ Create apps/assessments/views.py:

  from rest_framework import viewsets, status
  from rest_framework.decorators import action
  from rest_framework.response import Response
  from apps.assessments.models import *
  from apps.assessments.serializers import *
  from apps.assessments.services import *
  from apps.authority.decorators import require_permission
  
  class AssessmentViewSet(viewsets.ModelViewSet):
      """API endpoints for assessments."""
      serializer_class = AssessmentSerializer
      permission_classes = [IsAuthenticated]
      
      def get_queryset(self):
          """Filter by tenant and user role."""
          return Assessment.objects.filter(tenant=self.request.tenant)
      
      @require_permission('assessments', 'create')
      def create(self, request):
          """Create a new assessment."""
          serializer = self.get_serializer(data=request.data)
          serializer.is_valid(raise_exception=True)
          
          assessment = AssessmentService.create_assessment(
              tenant=request.tenant,
              **serializer.validated_data
          )
          
          return Response(
              AssessmentSerializer(assessment).data,
              status=status.HTTP_201_CREATED
          )
      
      @action(detail=True, methods=['post'])
      def publish(self, request, pk=None):
          """Publish assessment."""
          assessment = self.get_object()
          AssessmentService.publish_assessment(assessment)
          return Response({'status': 'published'})
      
      @action(detail=True, methods=['post'])
      def add_questions(self, request, pk=None):
          """Add questions to assessment."""
          assessment = self.get_object()
          question_ids = request.data.get('question_ids', [])
          
          AssessmentService.add_questions_to_assessment(assessment, question_ids)
          
          return Response({'status': 'questions_added'})
  
  class QuestionViewSet(viewsets.ModelViewSet):
      """API endpoints for questions."""
      serializer_class = QuestionSerializer
      permission_classes = [IsAuthenticated]
      
      def get_queryset(self):
          return Question.objects.filter(tenant=self.request.tenant)
      
      @require_permission('questions', 'create')
      def create(self, request):
          """Create question."""
          text = request.data.get('text')
          topic = request.data.get('topic')
          difficulty = request.data.get('difficulty')
          options = request.data.get('options')
          correct_option = request.data.get('correct_option_index')
          
          question = QuestionService.create_question(
              tenant=request.tenant,
              text=text,
              topic=topic,
              difficulty=difficulty,
              options=options,
              correct_option_index=correct_option
          )
          
          return Response(
              QuestionSerializer(question).data,
              status=status.HTTP_201_CREATED
          )
      
      @action(detail=False, methods=['post'])
      def bulk_import(self, request):
          """Bulk import questions from CSV."""
          # Implementation...
          pass
  
  class StudentAssessmentViewSet(viewsets.ModelViewSet):
      """API for student assessments."""
      serializer_class = StudentAssessmentSerializer
      permission_classes = [IsAuthenticated]
      
      def get_queryset(self):
          return StudentAssessment.objects.filter(tenant=self.request.tenant)
      
      @action(detail=True, methods=['post'])
      def start_exam(self, request, pk=None):
          """Start taking exam."""
          student_assessment = self.get_object()
          
          attempt = AttemptService.start_attempt(student_assessment)
          
          # Return exam questions
          questions = Question.objects.filter(
              assessmentquestion__assessment=student_assessment.assessment
          ).values('id', 'text', 'difficulty', 'topic')
          
          return Response({
              'attempt_id': str(attempt.id),
              'duration_minutes': student_assessment.assessment.duration_minutes,
              'total_questions': student_assessment.assessment.total_questions,
              'questions': list(questions)
          })
  
  class AttemptViewSet(viewsets.ViewSet):
      """API for exam attempts."""
      permission_classes = [IsAuthenticated]
      
      @action(detail=False, methods=['post'])
      def submit_answer(self, request):
          """Submit answer to a question."""
          attempt_id = request.data.get('attempt_id')
          question_id = request.data.get('question_id')
          selected_option_id = request.data.get('selected_option_id')
          
          attempt = AssessmentAttempt.objects.get(id=attempt_id)
          
          # Verify ownership
          if attempt.student_id != request.user.member_id:
              return Response(
                  {'error': 'Unauthorized'},
                  status=status.HTTP_403_FORBIDDEN
              )
          
          answer = AttemptService.save_answer(
              attempt, question_id, selected_option_id
          )
          
          return Response({'status': 'saved'})
      
      @action(detail=False, methods=['post'])
      def submit_exam(self, request):
          """Submit completed exam."""
          attempt_id = request.data.get('attempt_id')
          attempt = AssessmentAttempt.objects.get(id=attempt_id)
          
          # Verify ownership
          if attempt.student_id != request.user.member_id:
              return Response(
                  {'error': 'Unauthorized'},
                  status=status.HTTP_403_FORBIDDEN
              )
          
          score = AttemptService.submit_attempt(attempt)
          
          return Response(
              AssessmentScoreSerializer(score).data,
              status=status.HTTP_200_OK
          )
  
  class AssessmentScoreViewSet(viewsets.ViewSet):
      """API for exam scores."""
      permission_classes = [IsAuthenticated]
      
      def list(self, request):
          """Get all scores for authenticated user."""
          scores = AssessmentScore.objects.filter(
              tenant=request.tenant,
              student__user=request.user
          )
          return Response(
              AssessmentScoreSerializer(scores, many=True).data
          )
      
      def retrieve(self, request, pk=None):
          """Get specific score."""
          score = AssessmentScore.objects.get(id=pk)
          return Response(
              AssessmentScoreSerializer(score).data
          )

☐ Register viewsets in apps/assessments/urls.py:

  from django.urls import path, include
  from rest_framework.routers import DefaultRouter
  from apps.assessments.views import *
  
  router = DefaultRouter()
  router.register(r'assessments', AssessmentViewSet, basename='assessment')
  router.register(r'questions', QuestionViewSet, basename='question')
  router.register(r'student-assessments', StudentAssessmentViewSet, basename='student-assessment')
  router.register(r'attempts', AttemptViewSet, basename='attempt')
  router.register(r'scores', AssessmentScoreViewSet, basename='score')
  
  urlpatterns = [
      path('', include(router.urls)),
  ]

☐ Add to config/urls.py:

  urlpatterns = [
      ...
      path('api/assessments/', include('apps.assessments.urls')),
  ]

☐ Commit ViewSets:
  git add apps/assessments/serializers.py apps/assessments/views.py apps/assessments/urls.py
  git commit -m "Create API ViewSets and serializers for exam system"
```

#### Day 23-25: API Tests

```
WEDNESDAY-FRIDAY (Day 23-25):
────────────────────────────────
☐ Create apps/assessments/tests/test_api.py
☐ Write 35 API tests:

  Test Assessment API (7 tests):
  ├── test_create_assessment
  ├── test_list_assessments
  ├── test_retrieve_assessment
  ├── test_update_assessment
  ├── test_publish_assessment
  ├── test_add_questions_to_assessment
  └── test_permission_denied_for_other_tenant
  
  Test Question API (7 tests):
  ├── test_create_question
  ├── test_list_questions
  ├── test_retrieve_question
  ├── test_bulk_import_questions
  ├── test_question_options_included
  ├── test_correct_answer_not_exposed
  └── test_multi_tenant_isolation
  
  Test Attempt API (7 tests):
  ├── test_start_exam
  ├── test_submit_answer
  ├── test_answer_saved_correctly
  ├── test_cannot_modify_submitted_answer
  ├── test_submit_exam
  ├── test_grading_triggered
  └── test_certificate_generated_on_pass
  
  Test Score API (7 tests):
  ├── test_list_scores
  ├── test_retrieve_score
  ├── test_score_includes_breakdown
  ├── test_student_can_only_see_own_scores
  ├── test_permission_checks
  ├── test_certificate_available_on_pass
  └── test_admin_can_see_all_scores
  
  Test Error Handling (7 tests):
  ├── test_unauthorized_access_403
  ├── test_invalid_question_400
  ├── test_invalid_assessment_404
  ├── test_attempt_timeout
  ├── test_duplicate_submission
  ├── test_invalid_option_400
  └── test_rate_limiting

☐ Run all API tests:
  pytest apps/assessments/tests/test_api.py -v -s
  
  Expected: 35/35 passing

☐ Coverage check:
  pytest apps/assessments/tests/ --cov=apps.assessments.views
  
  Target: 75%+ coverage on views

☐ Commit:
  git add apps/assessments/tests/test_api.py
  git commit -m "Add 35 API integration tests"
```

### Week 6 (Days 26-30): Frontend & E2E Tests

```
Days 26-30: Frontend Development
├── Day 26-27: Exam-taking UI component
│   ├── Question display
│   ├── Timer
│   ├── Navigation (Previous/Next)
│   └── Auto-save mechanism
│
├── Day 28: Scorecard display
│   ├── Show results
│   ├── Breakdown by topic
│   └── Certificate download
│
├── Day 29-30: E2E tests
│   ├── Complete exam flow test
│   ├── Timer test
│   ├── Auto-save test
│   └── Submission test

Target: 50+ E2E tests
Coverage: 70%+ on frontend
```

### Week 7 (Days 31-35): Performance & Edge Cases

```
Days 31-35: Testing Edge Cases & Performance
├── Day 31-32: Load testing
│   ├── 100 concurrent exams
│   ├── Database query optimization
│   └── Cache implementation
│
├── Day 33-34: Edge cases
│   ├── Page refresh during exam
│   ├── Browser back button
│   ├── Time expiration
│   ├── Connection loss
│   └── Multiple attempts
│
├── Day 35: Final bug fixes
    └── Address any issues found

Target: 100% test pass rate
Coverage: 75%+ overall
Performance: <2 seconds exam start
```

### Week 8 (Days 36-40): Polish & Documentation

```
Days 36-40: Final Polish
├── Day 36-37: Code review & refactoring
├── Day 38: Documentation
├── Day 39: Performance optimization
└── Day 40: Final testing & cleanup

Deliverables:
├── ✅ 200+ automated tests
├── ✅ 75%+ code coverage
├── ✅ Complete API documentation
├── ✅ Admin guide
├── ✅ Developer guide
└── ✅ Student guide
```

### Phase 2 Completion Checklist

```
WEEK 3-8 COMPLETION CRITERIA:
────────────────────────────
☐ 7 core models created
☐ 5 service classes implemented
☐ 5 API ViewSets created
☐ 200+ automated tests written
☐ 75%+ code coverage achieved
☐ All tests passing (100% pass rate)
☐ Performance targets met
☐ Security review passed
☐ API documentation complete
☐ Code review completed
☐ PR merged to main branch
└── Phase 2 COMPLETE

METRICS:
├── Models: 7/7 ✅
├── Services: 5/5 ✅
├── ViewSets: 5/5 ✅
├── Tests: 200+/200+ ✅
├── Coverage: 75%+/75%+ ✅
├── Pass rate: 100%/100% ✅
└── Ready for staging deployment
```

---

## PHASE 3: STAGING & TESTING (Week 9)

### Objectives
- Deploy to staging environment
- Run smoke tests
- Security validation
- Performance testing
- Final UAT

### Staging Environment Setup

```
SETUP CHECKLIST:
├── Staging database (copy of production, anonymized data)
├── Staging server (can be same as dev if isolated)
├── Staging domain (optional, but recommended)
├── HTTPS/SSL certificate
├── Error tracking (Sentry staging)
├── Monitoring (basic logging)
└── Backup procedures

DEPLOYMENT STEPS:
1. Pull latest code from main branch
2. Run migrations on staging database
3. Collect static files
4. Restart application server
5. Run smoke tests
6. Verify error tracking is working
7. Monitor for 2 hours for any issues
```

### Week 9 Checklist

```
MONDAY (Day 36):
─────────────────
☐ Set up staging environment
☐ Configure staging database
☐ Configure error tracking (Sentry)
☐ Configure email (use staging domain)
☐ Configure file storage (staging bucket)
☐ SSL certificate for staging domain

TUESDAY (Day 37):
──────────────────
☐ Deploy to staging:
  git pull origin main
  python manage.py migrate
  python manage.py collectstatic
  
☐ Smoke tests:
  ├── Admin login works
  ├── Create assessment
  ├── Create question
  ├── Start exam
  ├── Submit exam
  ├── View scorecard
  └── Download certificate

☐ Security validation:
  ├── Multi-tenant data isolation
  ├── Permission checks working
  ├── No sensitive data in logs
  ├── HTTPS enforced
  └── CORS configured correctly

WEDNESDAY-FRIDAY (Days 38-40):
──────────────────────────────
☐ Performance testing:
  ├── Load test: 100 concurrent exams
  ├── Stress test: Database under load
  ├── Latency test: Response times
  └── Memory test: No memory leaks

☐ UAT with team:
  ├── Test all user flows
  ├── Document any issues
  ├── Create bug fix list
  └── Fix critical bugs before production

☐ Final checklist before production:
  ├── All tests passing ✅
  ├── Coverage 75%+ ✅
  ├── Staging stable for 48+ hours ✅
  ├── Security review passed ✅
  ├── Performance acceptable ✅
  ├── Backups working ✅
  ├── Rollback procedure documented ✅
  └── Setu team trained ✅
```

---

## PHASE 4: DEPLOY TO SETU (Week 10)

### Pre-Deployment Checklist

```
48 HOURS BEFORE DEPLOYMENT:
───────────────────────────
☐ Final security review
☐ Final performance review
☐ Backup production database
☐ Test rollback procedure
☐ Notify Setu team of deployment window
☐ Prepare rollback plan
☐ Prepare deployment checklist
☐ Get sign-off from stakeholders

DEPLOYMENT WINDOW:
├── Duration: 2-3 hours
├── Timing: Off-peak (e.g., 2 AM)
├── Team: Minimum 2 people
├── Support: On-call immediately post-deployment
└── Communicate: Notify users of maintenance
```

### Deployment Procedure

```
STEP 1: PRE-DEPLOYMENT (30 minutes before)
───────────────────────────────────────────
☐ Notify team and users
☐ Verify backup is complete
☐ Stop background jobs (if any)
☐ Verify staging deployment one more time

STEP 2: DATABASE BACKUP
───────────────────────
☐ Create database snapshot
☐ Verify backup is complete
☐ Document backup location and timestamp

STEP 3: CODE DEPLOYMENT
───────────────────────
☐ Pull latest code from main branch
☐ Run migrations:
  python manage.py migrate
  
☐ Collect static files:
  python manage.py collectstatic --noinput
  
☐ Restart application server:
  systemctl restart gunicorn  # or equivalent

STEP 4: POST-DEPLOYMENT VERIFICATION
──────────────────────────────────────
☐ Test homepage loads
☐ Test login works
☐ Test creating assessment
☐ Test taking exam
☐ Test scorecard display
☐ Test certificate download
☐ Check error logs (Sentry)
☐ Monitor performance metrics

STEP 5: SMOKE TESTS (Automated)
─────────────────────────────────
☐ Run production smoke tests
  pytest tests/smoke_tests/ -v
  
☐ All tests should pass:
  ├── Admin login
  ├── User login
  ├── Create assessment
  ├── Take exam
  ├── View scores
  └── Download certificate

STEP 6: MONITORING & ALERTING
──────────────────────────────
☐ Monitor error rate (should be < 0.1%)
☐ Monitor response time (should be < 2 seconds)
☐ Monitor database queries
☐ Monitor server resources (CPU, memory)
☐ Monitor error tracking (Sentry)

STEP 7: COMMUNICATION
──────────────────────
☐ Notify team deployment is complete
☐ Notify Setu team to start testing
☐ Provide support contact info
☐ Ask for feedback
```

### Rollback Procedure

```
IF CRITICAL ISSUE FOUND:
────────────────────────
1. Identify issue severity
2. If P0 (data loss, security): Rollback immediately
3. Rollback steps:
   ☐ Restore database from backup
   ☐ Revert code to previous version
   ☐ Restart application server
   ☐ Verify system is back to normal
   ☐ Notify Setu team
   ☐ Schedule post-mortem

ROLLBACK TIMELINE: < 30 minutes from detection

POST-ROLLBACK:
└── Investigate root cause
    Fix issue in staging
    Wait 48 hours for stability
    Redeploy to production
```

### Week 10 Checklist

```
MONDAY (Day 41):
─────────────────
☐ Final pre-deployment review
☐ Get sign-off from all stakeholders
☐ Prepare deployment scripts
☐ Train Setu support team
☐ Prepare support documentation

TUESDAY (Day 42):
──────────────────
☐ Execute deployment (as per Deployment Procedure above)
☐ Run smoke tests
☐ Monitor for 4 hours
☐ Get sign-off from Setu team

WEDNESDAY (Day 43):
────────────────────
☐ Monitor system health
☐ Gather initial feedback
☐ Fix any minor issues
☐ Update documentation based on feedback

THURSDAY-FRIDAY (Days 44-45):
──────────────────────────────
☐ Full monitoring and support
☐ Collect feedback from Setu
☐ Document lessons learned
☐ Plan Phase 5 iterations
```

---

## PHASE 5: ITERATE & MONITOR (Week 11-12)

### Monitoring Strategy

```
AUTOMATED MONITORING:
├── Error rate dashboard (Sentry)
├── Performance dashboard (response times)
├── Database query monitoring
├── Server resource monitoring (CPU, memory, disk)
├── Email delivery monitoring
├── User activity logs
└── Business metrics (exams taken, completion rate, etc.)

DAILY STANDUP (First 2 weeks post-deployment):
├── Status: Any errors overnight?
├── Metrics: Performance looking good?
├── Feedback: Any issues reported?
├── Action items: What needs fixing today?
└── Next steps: What's the priority for today?
```

### Week 11-12 Checklist

```
WEEK 11:
────────
MONDAY (Day 46):
☐ Daily monitoring
☐ Daily standup with Setu team
☐ Review error logs
☐ Address any critical issues

TUESDAY-FRIDAY (Days 47-50):
☐ Daily monitoring
☐ Fix bugs found by Setu
☐ Gather feedback on UX
☐ Document issues and fixes
☐ Plan improvements for next release

WEEK 12:
────────
MONDAY-FRIDAY (Days 51-55):
☐ Continue monitoring
☐ Iterate based on feedback
☐ Deploy hotfixes as needed
☐ Measure engagement metrics
└── By end of week 12: System is stable and Setu is happy
```

### Success Metrics for Phase 5

```
MUST HAVE:
├── Zero data loss incidents ✅
├── Error rate < 0.1% ✅
├── Average response time < 2 seconds ✅
├── 99% uptime ✅
└── No security issues ✅

NICE TO HAVE:
├── Setu team satisfied with UX
├── Student feedback positive
├── No performance degradation
└── Adoption metrics promising
```

---

## PHASE 6: EXPAND TO OTHER GYMS (Week 13-14)

### Onboarding New Customers

```
FOR EACH NEW GYM CUSTOMER:
├── Day 1: Setup tenant in system
├── Day 2-3: Configure initial assessments
├── Day 3-4: Train admin team
├── Day 5-7: Soft launch (internal testing)
├── Day 8: Public launch
└── Days 9-14: Support and monitoring

ONBOARDING CHECKLIST:
├── Create tenant record
├── Set up domain/subdomain
├── Configure email
├── Create admin user
├── Import questions/assessments template
├── Train admins (1-2 hours)
├── Set up monitoring for this tenant
├── Prepare support escalation path
└── Schedule 1-week follow-up
```

### Week 13-14 Checklist

```
WEEK 13:
────────
MONDAY-FRIDAY (Days 56-60):
☐ Onboard Gym #2
☐ Onboard Gym #3 (optional, parallel onboarding)
☐ Monitor both new tenants
☐ Fix any tenant-specific issues
☐ Gather feedback for improvements

WEEK 14:
────────
MONDAY-WEDNESDAY (Days 61-63):
☐ Monitor new tenants
☐ Support as needed
☐ Gather success metrics

THURSDAY-FRIDAY (Days 64-65):
☐ Document lessons learned
☐ Create playbook for future onboardings
☐ Plan next feature iterations
└── Phase 6 COMPLETE
```

---

## EXTERNAL RESOURCES READINESS

### Infrastructure Requirements

```
HOSTING:
├── Current: Server already running Django application
├── Database: PostgreSQL (already deployed)
├── Email: SMTP service (already configured)
├── File storage: Local or S3 bucket (for certificates)
└── Monitoring: Sentry (free tier available)

THIRD-PARTY SERVICES:
├── Sentry (error tracking)
│   └── Setup: https://sentry.io/
│       Cost: Free tier sufficient for MVP
│       Time to setup: 30 minutes
│
├── SendGrid or Mailgun (email if SMTP fails)
│   └── Optional backup
│       Cost: Free tier available
│       Time to setup: 15 minutes
│
└── Datadog or New Relic (performance monitoring)
    └── Optional, for advanced monitoring
        Cost: Free tier + paid
        Time to setup: 1-2 hours

CHECKLIST:
☐ Sentry account created
☐ Sentry project created
☐ SENTRY_DSN configured in Django settings
☐ Error tracking tested
☐ Alert rules configured
☐ Slack integration (if desired)
└── All setup complete
```

### Team & Skills Readiness

```
REQUIRED TEAM:
├── 1 Full-stack Developer
│   └── Skills: Python/Django, REST APIs, Testing
│
├── 1 DevOps Engineer (part-time)
│   └── Skills: Linux, PostgreSQL, Nginx/Apache, Deployment
│
└── 1 QA/Tester (optional)
    └── Skills: Manual testing, test automation, bug reporting

TRAINING NEEDED:
├── Exam system architecture (1-2 hours)
├── Testing practices (2-3 hours)
├── Deployment procedures (1-2 hours)
└── Monitoring & alerting (1 hour)

ONBOARDING DOCUMENTS:
├── ✅ CLAUDE.md (project overview)
├── ✅ TESTING.md (test running guide)
├── ✅ STRATEGY-B-EXECUTION-ROADMAP.md (this document)
├── 📝 DEPLOYMENT.md (deployment procedures)
├── 📝 API_DOCUMENTATION.md (API reference)
├── 📝 MONITORING.md (how to monitor system)
└── 📝 TROUBLESHOOTING.md (common issues & fixes)
```

### Customer Readiness (Setu Yoga Studio)

```
PRE-DEPLOYMENT:
├── ☐ Setu team trained on new features
├── ☐ Setu team has access to staging
├── ☐ Admin has created test assessments
├── ☐ Admin has taken test exam
├── ☐ Setu team comfortable with feature
└── ☐ Go/no-go decision made

POST-DEPLOYMENT:
├── ☐ Setu admin creates real assessments
├── ☐ Setu admin invites first students
├── ☐ First students take exams
├── ☐ Setu team comfortable with system
├── ☐ Collect feedback for improvements
└── ☐ Ready to expand to other gyms
```

---

## SUCCESS CRITERIA & METRICS

### Phase-by-Phase Success Criteria

```
PHASE 1 (Test Infrastructure):
├── 100+ tests written ✅
├── 70%+ coverage achieved ✅
├── CI/CD pipeline running ✅
├── All tests passing ✅
└── Team comfortable with testing approach ✅

PHASE 2 (Exam System Development):
├── 7 models created ✅
├── 5 services implemented ✅
├── 5 ViewSets created ✅
├── 200+ tests written ✅
├── 75%+ coverage achieved ✅
└── All tests passing ✅

PHASE 3 (Staging & Testing):
├── Staging deployment successful ✅
├── Smoke tests all passing ✅
├── Performance acceptable ✅
├── Security review passed ✅
├── Team UAT completed ✅
└── Go/no-go decision: GO ✅

PHASE 4 (Deploy to Setu):
├── Deployment procedure executed successfully ✅
├── Post-deployment smoke tests passing ✅
├── System stable for 48 hours ✅
├── Setu team can access features ✅
├── Error rate < 0.1% ✅
└── Go/no-go decision: GO ✅

PHASE 5 (Iterate & Monitor):
├── Zero data loss ✅
├── 99%+ uptime ✅
├── Error rate < 0.1% ✅
├── Response time < 2 seconds ✅
├── Setu team satisfied ✅
└── Ready to expand ✅

PHASE 6 (Expand):
├── 2-3 new gyms onboarded ✅
├── All tenants stable ✅
├── Playbook documented ✅
└── Process repeatable ✅
```

### Key Metrics to Track

```
CODE QUALITY:
├── Code coverage: Target 75%+
├── Test pass rate: Target 100%
├── Code review: 0 critical findings
├── Technical debt: Minimal
└── Performance: < 2 second response time

OPERATIONAL:
├── Deployment time: < 30 minutes
├── Rollback time: < 10 minutes (if needed)
├── MTTR (Mean Time to Repair): < 2 hours
├── Uptime: 99.5%+
├── Error rate: < 0.1%
├── Response time: < 2 seconds
├── Database query time: < 100ms average
└── Memory usage: Stable

BUSINESS:
├── Setu satisfaction: 4.5+/5.0
├── Student feedback: Positive
├── Exam completion rate: > 80%
├── Certificate downloads: > 70% of passed exams
├── Time to market: 10 weeks
└── ROI: Positive by month 3
```

---

## RISK REGISTER & MITIGATION

### High-Risk Items

```
RISK #1: Test Suite Takes Longer Than Expected
──────────────────────────────────────────────
Impact: Delays exam system development
Likelihood: Medium (30%)
Mitigation:
├── Start with critical tests only
├── Don't write tests for UI styling
├── Reuse test patterns from core platform
├── Pair programming to speed up
└── Prioritize: Multi-tenancy > Auth > Business logic

RISK #2: Exam System Introduces Data Corruption
───────────────────────────────────────────────
Impact: Critical (potential data loss)
Likelihood: Low (10% if proper isolation tests)
Mitigation:
├── Extensive multi-tenant isolation tests
├── Test every data model
├── Code review by experienced developer
├── Staging deployment with real data
├── Database backups before every deployment
└── Rollback procedure tested and ready

RISK #3: Performance Degradation Under Load
────────────────────────────────────────────
Impact: Users can't take exams, system slow
Likelihood: Medium (25%)
Mitigation:
├── Load test with 100 concurrent exams
├── Database query optimization
├── Implement caching (Redis if needed)
├── Database indexing on key fields
└── Staging performance testing

RISK #4: Deployment Issues/Downtime
──────────────────────────────────────
Impact: Setu can't access system
Likelihood: Low (15%)
Mitigation:
├── Dry-run deployment in staging
├── Document all deployment steps
├── Rollback procedure tested
├── Deploy during low-traffic hours
├── Team available for troubleshooting
└── Communication plan for users

RISK #5: API Security Issues
────────────────────────────
Impact: Critical (data breach, unauthorized access)
Likelihood: Low (5% if proper RBAC testing)
Mitigation:
├── Permission tests for every endpoint
├── Penetration testing in staging
├── Security review before production
├── Rate limiting implemented
├── HTTPS enforced
└── Regular security audits

RISK #6: Certificate Generation Fails
──────────────────────────────────────
Impact: Students don't get certificates
Likelihood: Low (10%)
Mitigation:
├── Test PDF generation with sample data
├── Test certificate storage
├── Test email delivery
├── Error handling implemented
└── Manual certificate generation fallback
```

### Medium-Risk Items

```
RISK #7: Admin UI Confusing for Setu Team
──────────────────────────────────────────
Impact: Setu team struggles to set up assessments
Likelihood: Medium (40%)
Mitigation:
├── User testing with Setu team before deployment
├── Clear documentation
├── Admin training (1-2 hours)
├── Support available first week
└── UI improvements in Phase 2

RISK #8: Email Delivery Issues
──────────────────────────────
Impact: Students don't receive exam invites/results
Likelihood: Low (15%)
Mitigation:
├── Test email sending in staging
├── Configure mail server backup
├── Error tracking for failed emails
├── Fallback: Manual email sending
└── Monitor email delivery rate

RISK #9: Difficulty Distribution Incorrect
──────────────────────────────────────────
Impact: Exams too hard or too easy
Likelihood: Medium (30%)
Mitigation:
├── Setu reviews sample exams before deployment
├── Question difficulty validation
├── Easy to adjust distribution after deployment
├── Monitor exam completion rates
└── Gather feedback for adjustment
```

### Low-Risk Items

```
RISK #10: Student Finds Exam UI Confusing
──────────────────────────────────────────
Impact: Poor student experience
Likelihood: Medium (35%)
Mitigation:
├── UI testing with a few students before expansion
├── Clear instructions on exam page
├── Help text for navigation
├── Easy UI improvements after feedback
└── Support available during exams

RISK #11: Browser Compatibility Issues
──────────────────────────────────────
Impact: Some students can't access exams
Likelihood: Low (10%)
Mitigation:
├── Test on Chrome, Firefox, Safari, Edge
├── Responsive design verified
├── Fallback UI for older browsers
└── Support different devices
```

---

## WEEKLY CHECKLIST & TRACKING

### Week 1-2: Test Infrastructure

```
[ ] Day 1-2: Pytest setup
[ ] Day 3-5: Multi-tenancy tests (15 tests)
[ ] Day 6-7: Auth, RBAC, Membership tests (30 tests)
[ ] Day 8-10: CI/CD setup & remaining tests
Status: _____ / 100% Complete
```

### Week 3-8: Exam System Development

```
Week 3:
[ ] Day 11-15: Models & unit tests (30 tests)

Week 4:
[ ] Day 16-20: Services & integration tests (40 tests)

Week 5:
[ ] Day 21-25: ViewSets & API tests (35 tests)

Week 6:
[ ] Day 26-30: Frontend & E2E tests (50+ tests)

Week 7:
[ ] Day 31-35: Performance & edge cases

Week 8:
[ ] Day 36-40: Polish & documentation

Status: _____ / 100% Complete
```

### Week 9: Staging & Testing

```
[ ] Day 36: Staging environment setup
[ ] Day 37: Smoke tests
[ ] Day 38-40: Performance testing & UAT
[ ] Go/No-go: ______ (GO / NO-GO)
Status: _____ / 100% Complete
```

### Week 10: Production Deployment

```
[ ] Day 41: Pre-deployment review
[ ] Day 42: Deployment execution
[ ] Day 43-45: Post-deployment monitoring
[ ] Deployment successful: YES / NO
Status: _____ / 100% Complete
```

### Week 11-12: Iterate & Monitor

```
[ ] Daily monitoring
[ ] Daily standup
[ ] Bug fixes as needed
[ ] Gather feedback
[ ] Document lessons learned
Status: _____ / 100% Complete
```

### Week 13-14: Expand

```
[ ] Onboard Gym #2
[ ] Onboard Gym #3 (optional)
[ ] Monitor new tenants
[ ] Document playbook
Status: _____ / 100% Complete
```

---

## DOCUMENT SIGN-OFF

**Project:** Exam System for Setu Yoga Studio  
**Version:** Strategy B (Automated Tests → Setu → Expand)  
**Document:** Execution Roadmap  
**Date:** June 28, 2026  
**Duration:** 10-14 weeks (70 days)  

**Approved By:**  
- [ ] Development Lead: _______________ Date: ________
- [ ] Project Manager: _______________ Date: ________
- [ ] Setu Studio Manager: _______________ Date: ________

**Next Steps:**
1. ☐ Review this document with team
2. ☐ Get approval from all stakeholders
3. ☐ Start Week 1 (Test Infrastructure)
4. ☐ Daily standup tracking progress
5. ☐ Weekly check-ins on roadmap

---

## QUICK REFERENCE: KEY DATES

```
PHASE 1: Week 1-2 (Days 1-10)
Phase 1 Complete: Day 10 (July 8, 2026)

PHASE 2: Week 3-8 (Days 11-40)
Phase 2 Complete: Day 40 (August 7, 2026)

PHASE 3: Week 9 (Days 41-45)
Phase 3 Complete: Day 45 (August 12, 2026)

PHASE 4: Week 10 (Days 46-50)
Phase 4 Complete: Day 50 (August 17, 2026)

PHASE 5: Week 11-12 (Days 51-60)
Phase 5 Complete: Day 60 (August 27, 2026)

PHASE 6: Week 13-14 (Days 61-70)
Phase 6 Complete: Day 70 (September 6, 2026)

TOTAL DURATION: 70 days (~10 weeks)
```

---

**END OF STRATEGY B EXECUTION ROADMAP**

For questions or clarifications, refer to:
- Project Overview: CLAUDE.md
- Testing Guide: docs/TESTING.md
- API Documentation: (to be created Week 5)
- Deployment Guide: (to be created Week 8)
