# Assessment Module Documentation

**Complete Exam System for Setu Yoga Studio**

## Quick Start

```bash
# Run migrations
python manage.py migrate assessments

# Run tests
pytest apps/assessments/tests/

# Run specific test suite
pytest apps/assessments/tests/test_multi_tenancy.py -v  # CRITICAL tests
```

## Module Structure

```
apps/assessments/
├── models.py              # 7 database models
├── services/              # 5 business logic services
│   ├── assessment_service.py
│   ├── question_service.py
│   ├── attempt_service.py
│   ├── grading_service.py
│   └── certificate_service.py
├── serializers.py         # DRF API serializers
├── views.py              # 5 API ViewSets
├── urls.py               # URL routing
├── admin.py              # Django admin configuration
├── signals.py            # Signal handlers (auto-grading, certificates)
├── apps.py               # App configuration
├── migrations/           # Database migrations
└── tests/                # 100+ comprehensive tests
    ├── conftest.py       # Pytest fixtures
    ├── test_models.py    # 30+ unit tests
    ├── test_services.py  # 40+ integration tests
    └── test_multi_tenancy.py  # 15+ critical isolation tests
```

## Database Models (7 Models)

### 1. **Assessment** - Exam Template
The master exam definition with timing, questions count, and passing criteria.

```python
Assessment.objects.create(
    tenant=tenant,
    name="Yoga Fundamentals",
    total_questions=50,
    duration_minutes=60,
    passing_score=60,
    easy_percentage=30,
    medium_percentage=40,
    hard_percentage=30,
    status="draft"
)

assessment.publish()  # Move from draft to published
```

### 2. **Question** - Question Bank
Individual questions that make up the question bank for an assessment.

```python
Question.objects.create(
    tenant=tenant,
    assessment=assessment,
    text="What is yoga?",
    difficulty="easy",  # easy, medium, hard
    topic="Basics",
    explanation="Yoga means union",
    status="draft"
)

question.publish()  # Validate 4 options + 1 correct
```

### 3. **QuestionOption** - Multiple Choice Options
4 options per question, exactly 1 marked as correct.

```python
QuestionOption.objects.create(
    tenant=tenant,
    question=question,
    text="Union",
    is_correct=True,
    display_order=0
)
```

### 4. **StudentAssessment** - Enrollment
Student enrollment in an assessment with attempt tracking.

```python
StudentAssessment.objects.create(
    tenant=tenant,
    student=student,
    assessment=assessment,
    status="scheduled",
    max_attempts=3
)
```

### 5. **AssessmentAttempt** - Exam Session
Individual exam session/attempt with all answers.

```python
AssessmentAttempt.objects.create(
    tenant=tenant,
    student_assessment=enrollment,
    status="started"
)

attempt.submit()  # Mark as submitted when student finishes
```

### 6. **AttemptAnswer** - Individual Answer
Student's answer to each question.

```python
AttemptAnswer.objects.create(
    tenant=tenant,
    attempt=attempt,
    question=question,
    selected_option=option,
    is_correct=True,
    points_earned=1
)
```

### 7. **AssessmentScore** - Results & Grading
Final score, pass/fail, and topic breakdown.

```python
AssessmentScore.objects.create(
    tenant=tenant,
    student_assessment=enrollment,
    attempt=attempt,
    total_questions=50,
    correct_answers=35,
    percentage=70.0,
    is_passed=True,
    breakdown_by_topic={
        "Asanas": {"correct": 15, "total": 20, "percentage": 75.0},
        "Pranayama": {"correct": 12, "total": 15, "percentage": 80.0},
        "Philosophy": {"correct": 8, "total": 15, "percentage": 53.3}
    }
)
```

## Services (5 Services)

### 1. AssessmentService - Exam Management

```python
service = AssessmentService(tenant)

# Create assessment
assessment = service.create_assessment(
    name="Yoga Basics",
    duration_minutes=60,
    passing_score=60,
    total_questions=50
)

# Publish for students
service.publish_assessment(assessment)

# Enroll student
enrollment = service.enroll_student(assessment, student)
```

### 2. QuestionService - Question Bank

```python
service = QuestionService(tenant)

# Create question
question = service.create_question(
    assessment=assessment,
    text="What is yoga?",
    difficulty="easy"
)

# Add 4 options
service.add_options(question, [
    {"text": "Union", "is_correct": True},
    {"text": "Exercise", "is_correct": False},
    {"text": "Religion", "is_correct": False},
    {"text": "Dance", "is_correct": False}
])

# Publish question (validates 4 options + 1 correct)
service.publish_question(question)

# Bulk import from CSV
questions = service.bulk_import_questions(assessment, csv_content)

# Get random questions by difficulty
questions = service.get_random_questions(assessment, count=50)
```

### 3. AttemptService - Exam Taking

```python
service = AttemptService(tenant)

# Start exam attempt
attempt = service.start_attempt(enrollment)

# Save answer
service.save_answer(attempt, question_id, selected_option_id)

# Submit exam
service.submit_exam(attempt)

# Get progress
progress = service.get_attempt_progress(attempt)
# Returns: {total: 50, answered: 35, remaining: 15, percentage: 70}
```

### 4. GradingService - Auto-Grading

```python
service = GradingService(tenant)

# Grade submitted attempt (auto-calculates percentage, pass/fail)
score = service.grade_attempt(attempt)

# Get grade report for display
report = service.get_grade_report(score)
# Returns: {student_name, assessment_name, percentage, is_passed, breakdown_by_topic}

# Get student performance summary
summary = service.get_student_performance_summary(student, assessment)
# Returns: {attempts_total, attempts_passed, best_score, is_passed}
```

### 5. CertificateService - Certificate Generation

```python
service = CertificateService(tenant)

# Generate certificate (auto-triggered on passing)
cert = service.generate_certificate(score)

# Email certificate to student (auto-triggered by signal)
service.send_certificate_email(score)

# Revoke certificate if needed
service.revoke_certificate(score)
```

## API Endpoints (5 ViewSets)

### AssessmentViewSet
```
GET    /api/assessments/           # List exams
POST   /api/assessments/           # Create exam
GET    /api/assessments/{id}/      # Get exam details
PUT    /api/assessments/{id}/      # Update exam
DELETE /api/assessments/{id}/      # Delete exam
POST   /api/assessments/{id}/publish/        # Publish exam
POST   /api/assessments/{id}/add_questions/  # Add questions
```

### QuestionViewSet
```
GET    /api/questions/              # List questions
POST   /api/questions/              # Create question
GET    /api/questions/{id}/         # Get question
PUT    /api/questions/{id}/         # Update question
DELETE /api/questions/{id}/         # Delete question
POST   /api/questions/{id}/publish/ # Publish question
POST   /api/questions/bulk_import/  # Bulk import CSV
```

### StudentAssessmentViewSet
```
GET    /api/student-assessments/              # List enrollments
POST   /api/student-assessments/              # Enroll student
GET    /api/student-assessments/{id}/         # Get enrollment
POST   /api/student-assessments/{id}/start_exam/  # Start exam
```

### AssessmentAttemptViewSet
```
GET    /api/attempts/                      # List attempts
GET    /api/attempts/{id}/                 # Get attempt details
POST   /api/attempts/{id}/submit_answer/   # Save answer
POST   /api/attempts/{id}/submit_exam/     # Submit & grade
```

### AssessmentScoreViewSet
```
GET    /api/scores/        # List scores
GET    /api/scores/{id}/   # Get score details
```

## Critical Features

### ✅ Multi-Tenancy Isolation (GOTCHA #1)
Every model includes `tenant` field. All queries auto-filter by tenant.

```python
# Only see current tenant's assessments
assessments = Assessment.objects.filter(tenant=request.user.tenant)
```

**Tests verify Tenant A cannot see Tenant B data:**
```bash
pytest apps/assessments/tests/test_multi_tenancy.py -v
```

### ✅ Automatic Grading (Signal Handler)
When exam is submitted, auto-grade and generate certificate.

```python
# In signals.py
@receiver(post_save, sender=AssessmentAttempt)
def auto_grade_submitted_attempt(sender, instance, **kwargs):
    if instance.status == "submitted":
        grading_service.grade_attempt(instance)
```

### ✅ Topic Breakdown
Grade report includes score by topic for detailed feedback.

```python
score.breakdown_by_topic = {
    "Asanas": {"correct": 15, "total": 20, "percentage": 75.0},
    "Pranayama": {"correct": 12, "total": 15, "percentage": 80.0},
    "Philosophy": {"correct": 8, "total": 15, "percentage": 53.3}
}
```

### ✅ Bulk Question Import
Import questions from CSV for quick setup.

```
Question Text,Difficulty,Topic,Option 1,Option 2,Option 3,Option 4,Correct Option (1-4),Explanation
"What is yoga?",easy,"Basics","Union","Exercise","Religion","Dance",1,"Yoga means union"
"Name limbs",medium,"Philosophy","5","6","8","7",3,"Eight limbs"
```

### ✅ Role-Based Field Filtering (GOTCHA #9)
- **Students:** Never see `is_correct` in options or explanations during exam
- **Admins:** Always see complete data for review

```python
# In serializers
def to_representation(self, instance):
    data = super().to_representation(instance)
    user = self.context.get("request").user
    
    if not user.is_staff:
        data.pop("is_correct", None)  # Hide from students
    
    return data
```

## Testing (100+ Tests)

### Run All Tests
```bash
pytest apps/assessments/tests/
```

### Run Specific Test Suites
```bash
# Unit tests (30+ tests)
pytest apps/assessments/tests/test_models.py -v

# Service layer tests (40+ tests)
pytest apps/assessments/tests/test_services.py -v

# CRITICAL: Multi-tenancy isolation tests (15+ tests)
pytest apps/assessments/tests/test_multi_tenancy.py -v -m critical

# Coverage report
pytest apps/assessments/tests/ --cov=apps.assessments --cov-report=html
```

### Test Fixtures (conftest.py)
Comprehensive pytest fixtures for:
- Two tenants (Tenant A, Tenant B) for isolation testing
- Users (admin, staff, regular) for role testing
- Members/students
- Assessments (published and draft)
- Questions (easy, medium, hard)
- Options with correct answers
- Enrollments, attempts, scores

```python
# Example usage in tests
def test_something(tenant_a, tenant_b, student_a, assessment_a):
    # tenant_a, tenant_b for isolation
    # student_a for member
    # assessment_a for published exam
```

## Django Admin

Access admin at `/admin/` to:
- Create/manage assessments
- Create/manage questions and options
- View enrollments
- View scores and topic breakdowns
- Generate certificates
- Publish assessments and questions

All models registered with rich display options, filters, and inline editing.

## Integration with SaaS Platform

### Tenant Integration
```python
# Automatic tenant assignment on create
assessment.save(tenant=request.user.tenant)
```

### User/Member Integration
```python
# Uses existing Member model for students
# Uses existing User model for created_by tracking
```

### Signals Integration
```python
# Auto-grade when submitted (in signals.py)
# Auto-generate certificate on pass (in signals.py)
```

## Common Patterns

### ✅ GOTCHA #2: Always Set Tenant in Views
```python
def perform_create(self, serializer):
    serializer.save(
        tenant=self.request.user.tenant,  # Always set!
        created_by=self.request.user
    )
```

### ✅ GOTCHA #5: Services Take Explicit Tenant
```python
# Correct - tenant passed explicitly
service = AssessmentService(tenant=request.user.tenant)

# Wrong - relying on request context
service = AssessmentService()  # No tenant passed!
```

### ✅ GOTCHA #6: Validate Questions Before Publishing
```python
# Each question MUST have:
# - Exactly 4 options
# - Exactly 1 correct answer
question.publish()  # Raises ValidationError if invalid
```

### ✅ GOTCHA #7: Publish Requires Minimum Questions
```python
# Assessment MUST have at least total_questions published
# before you can publish it
assessment.publish()  # Raises ValidationError if not enough
```

### ✅ GOTCHA #10: Avoid N+1 Queries
```python
# Good - uses select_related for efficiency
qs = Assessment.objects.select_related(
    "tenant", "created_by"
).filter(tenant=user.tenant)

# Bad - will cause N+1 queries
qs = Assessment.objects.filter(tenant=user.tenant)
for a in qs:
    print(a.created_by.name)  # Query per assessment!
```

## Deployment Checklist

- [ ] Run all tests: `pytest apps/assessments/tests/`
- [ ] Verify multi-tenancy: `pytest apps/assessments/tests/test_multi_tenancy.py`
- [ ] Run migrations: `python manage.py migrate assessments`
- [ ] Create superuser: `python manage.py createsuperuser`
- [ ] Test admin interface
- [ ] Test API endpoints with API client
- [ ] Verify tenant isolation in staging
- [ ] Test certificate generation
- [ ] Load sample data for testing
- [ ] Document API for frontend team

## Support & Documentation

- **Models:** See docstrings in `models.py`
- **Services:** See docstrings in `services/`
- **API:** See docstrings in `views.py`
- **Tests:** See docstrings in `tests/`
- **Gotchas:** See `WATCH-OUT-FOR.md` in project root

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | 7 database models with validators |
| `services/assessment_service.py` | Exam creation, publishing, enrollment |
| `services/question_service.py` | Question bank management, bulk import |
| `services/attempt_service.py` | Exam session handling, answer recording |
| `services/grading_service.py` | Auto-grading and scoring |
| `services/certificate_service.py` | Certificate generation and emails |
| `serializers.py` | DRF serializers with role-based filtering |
| `views.py` | 5 ViewSets for REST API |
| `admin.py` | Django admin with rich interface |
| `signals.py` | Auto-grading and certificate generation |
| `tests/conftest.py` | Pytest fixtures and configuration |
| `tests/test_models.py` | Unit tests (30+) |
| `tests/test_services.py` | Integration tests (40+) |
| `tests/test_multi_tenancy.py` | CRITICAL isolation tests (15+) |

---

**Status:** ✅ Production Ready

Built with Django 6.0+, DRF, Pytest, and multi-tenant isolation as priority.
