"""
Pytest Configuration and Fixtures (FIXED)
"""

import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

from apps.core.models import Tenant, Branch
from apps.accounts.models import User
from apps.authority.models import Role
from members.models import Member

from apps.assessments.models import (
    Assessment,
    Question,
    QuestionOption,
    StudentAssessment,
    AssessmentAttempt,
    AttemptAnswer,
    AssessmentScore,
)
from apps.assessments.services.assessment_service import AssessmentService
from apps.assessments.services.question_service import QuestionService
from apps.assessments.services.attempt_service import AttemptService
from apps.assessments.services.grading_service import GradingService
from apps.assessments.services.certificate_service import CertificateService
from apps.core.tenant_context import set_current_tenant


# =====================================================
# Tenant Context Setup (for TenantManager to work in tests)
# =====================================================

@pytest.fixture(autouse=True)
def tenant_context(tenant_a):
    """Set tenant context for all tests"""
    set_current_tenant(tenant_a)
    yield
    set_current_tenant(None)


# =====================================================
# Tenants
# =====================================================

@pytest.fixture(scope="function")
def tenant_a(db):
    """Tenant A (Setu Yoga Studio)"""
    return Tenant.objects.create(
        name="Setu Yoga Studio",
        subdomain="setu-yoga"
    )


@pytest.fixture(scope="function")
def tenant_b(db):
    """Tenant B (Different Gym)"""
    return Tenant.objects.create(
        name="Fitness First Gym",
        subdomain="fitness-first"
    )


@pytest.fixture(scope="function")
def tenant(tenant_a):
    """Default tenant"""
    return tenant_a


# =====================================================
# Branches
# =====================================================

@pytest.fixture(scope="function")
def branch_a(db, tenant_a):
    """Branch for Tenant A"""
    return Branch.objects.create(
        tenant=tenant_a,
        name="Main Branch",
        address="123 Yoga St, City"
    )


@pytest.fixture(scope="function")
def branch_b(db, tenant_b):
    """Branch for Tenant B"""
    return Branch.objects.create(
        tenant=tenant_b,
        name="Downtown Branch",
        address="456 Fitness Ave, City"
    )


# =====================================================
# Roles
# =====================================================

@pytest.fixture(scope="function")
def staff_role_a(db, tenant_a):
    """Staff role for Tenant A"""
    return Role.objects.create(
        tenant=tenant_a,
        name="Staff"
    )


@pytest.fixture(scope="function")
def staff_role_b(db, tenant_b):
    """Staff role for Tenant B"""
    return Role.objects.create(
        tenant=tenant_b,
        name="Staff"
    )


# =====================================================
# Users
# =====================================================

@pytest.fixture(scope="function")
def admin_user(db):
    """Platform admin"""
    return User.objects.create_superuser(
        email="admin@test.com",
        password="admin123",
        is_platform_admin=True
    )


@pytest.fixture(scope="function")
def staff_user_a(db, tenant_a, staff_role_a):
    """Staff user for Tenant A"""
    user = User.objects.create_user(
        email="staff_a@test.com",
        password="staff123",
        tenant=tenant_a,
        role=staff_role_a,
        is_staff=True
    )
    return user


@pytest.fixture(scope="function")
def staff_user_b(db, tenant_b, staff_role_b):
    """Staff user for Tenant B"""
    user = User.objects.create_user(
        email="staff_b@test.com",
        password="staff123",
        tenant=tenant_b,
        role=staff_role_b,
        is_staff=True
    )
    return user


# =====================================================
# Members
# =====================================================

@pytest.fixture(scope="function")
def member_a(db, tenant_a):
    """Member for Tenant A"""
    return Member.objects.create(
        tenant=tenant_a,
        first_name="Rajesh",
        last_name="Kumar",
        email="rajesh@test.com",
        phone="9876543210"
    )


@pytest.fixture(scope="function")
def member_b(db, tenant_b):
    """Member for Tenant B"""
    return Member.objects.create(
        tenant=tenant_b,
        first_name="Priya",
        last_name="Singh",
        email="priya@test.com",
        phone="9876543211"
    )


@pytest.fixture(scope="function")
def student_a(member_a):
    """Alias for member_a"""
    return member_a


@pytest.fixture(scope="function")
def student_b(member_b):
    """Alias for member_b"""
    return member_b


# =====================================================
# Assessments
# =====================================================

@pytest.fixture(scope="function")
def assessment_a(db, tenant_a, staff_user_a):
    """Assessment for Tenant A"""
    return Assessment.objects.create(
        tenant=tenant_a,
        name="Yoga Fundamentals",
        description="Basic yoga knowledge assessment",
        total_questions=5,
        duration_minutes=30,
        passing_score=60,
        easy_percentage=40,
        medium_percentage=40,
        hard_percentage=20,
        status="draft",
        is_active=True,
        created_by=staff_user_a
    )


@pytest.fixture(scope="function")
def assessment_b(db, tenant_b, staff_user_b):
    """Assessment for Tenant B"""
    return Assessment.objects.create(
        tenant=tenant_b,
        name="Advanced Asanas",
        description="Advanced posture assessment",
        total_questions=10,
        duration_minutes=45,
        passing_score=70,
        easy_percentage=20,
        medium_percentage=40,
        hard_percentage=40,
        status="draft",
        is_active=True,
        created_by=staff_user_b
    )


@pytest.fixture(scope="function")
def assessment_draft(db, tenant_a, staff_user_a):
    """Draft assessment for Tenant A"""
    return Assessment.objects.create(
        tenant=tenant_a,
        name="Draft Exam",
        description="Not yet published",
        total_questions=10,
        duration_minutes=20,
        passing_score=50,
        easy_percentage=50,
        medium_percentage=30,
        hard_percentage=20,
        status="draft",
        is_active=False,
        created_by=staff_user_a
    )


@pytest.fixture(scope="function")
def assessment(assessment_a):
    """Default assessment"""
    return assessment_a


# =====================================================
# Questions (Simple - No Options Yet)
# =====================================================

@pytest.fixture(scope="function")
def question_a(db, assessment_a, staff_user_a):
    """Simple question for assessment_a (no options)"""
    return Question.objects.create(
        tenant=assessment_a.tenant,
        assessment=assessment_a,
        text="What is yoga?",
        difficulty="easy",
        topic="Basics",
        explanation="Yoga means union",
        status="draft",
        created_by=staff_user_a
    )


@pytest.fixture(scope="function")
def question_with_options(db, assessment_a, staff_user_a):
    """Question with 4 options for assessment_a"""
    q = Question.objects.create(
        tenant=assessment_a.tenant,
        assessment=assessment_a,
        text="Question with options?",
        difficulty="easy",
        topic="Basics",
        explanation="Explanation here",
        status="draft",
        created_by=staff_user_a
    )

    # Create 4 options
    QuestionOption.objects.create(
        tenant=assessment_a.tenant,
        question=q,
        text="Correct Answer",
        is_correct=True,
        display_order=0
    )
    for i in range(1, 4):
        QuestionOption.objects.create(
            tenant=assessment_a.tenant,
            question=q,
            text=f"Wrong Answer {i}",
            is_correct=False,
            display_order=i
        )

    return q


@pytest.fixture(scope="function")
def question_easy_a(db, assessment_a, staff_user_a):
    """Easy question for Tenant A's assessment"""
    q = Question.objects.create(
        tenant=assessment_a.tenant,
        assessment=assessment_a,
        text="What is yoga?",
        difficulty="easy",
        topic="Basics",
        explanation="Yoga means union",
        status="draft",
        created_by=staff_user_a
    )

    # Create 4 options
    QuestionOption.objects.create(
        tenant=assessment_a.tenant,
        question=q,
        text="Union",
        is_correct=True,
        display_order=0
    )
    for i, text in enumerate(["Exercise", "Religion", "Dance"], 1):
        QuestionOption.objects.create(
            tenant=assessment_a.tenant,
            question=q,
            text=text,
            is_correct=False,
            display_order=i
        )

    return q


@pytest.fixture(scope="function")
def question_medium_a(db, assessment_b, staff_user_b):
    """Medium question for Tenant B's assessment"""
    q = Question.objects.create(
        tenant=assessment_b.tenant,
        assessment=assessment_b,
        text="Name the eight limbs of yoga",
        difficulty="medium",
        topic="Philosophy",
        explanation="Eight limbs are central to yoga philosophy",
        status="draft",
        created_by=staff_user_b
    )

    # Create 4 options
    QuestionOption.objects.create(
        tenant=assessment_b.tenant,
        question=q,
        text="Eight",
        is_correct=True,
        display_order=0
    )
    for i, text in enumerate(["Five", "Six", "Seven"], 1):
        QuestionOption.objects.create(
            tenant=assessment_b.tenant,
            question=q,
            text=text,
            is_correct=False,
            display_order=i
        )

    return q


@pytest.fixture(scope="function")
def options_for_question_easy_a(db, question_a):
    """Create 4 options for question_a"""
    options = []
    option_texts = [
        {"text": "Union", "is_correct": True},
        {"text": "Exercise", "is_correct": False},
        {"text": "Religion", "is_correct": False},
        {"text": "Dance", "is_correct": False},
    ]

    for i, opt_data in enumerate(option_texts):
        option = QuestionOption.objects.create(
            tenant=question_a.tenant,
            question=question_a,
            text=opt_data["text"],
            is_correct=opt_data["is_correct"],
            display_order=i
        )
        options.append(option)

    return options


# =====================================================
# Enrollments
# =====================================================

@pytest.fixture(scope="function")
def enrollment_a(db, student_a, assessment_a):
    """Student A enrolled in Assessment A"""
    return StudentAssessment.objects.create(
        tenant=assessment_a.tenant,
        student=student_a,
        assessment=assessment_a,
        status="scheduled",
        scheduled_date=timezone.now() + timedelta(days=1),
        max_attempts=3
    )


@pytest.fixture(scope="function")
def enrollment_b(db, student_b, assessment_b):
    """Student B enrolled in Assessment B"""
    return StudentAssessment.objects.create(
        tenant=assessment_b.tenant,
        student=student_b,
        assessment=assessment_b,
        status="scheduled",
        scheduled_date=timezone.now() + timedelta(days=2),
        max_attempts=3
    )


@pytest.fixture(scope="function")
def enrollment(enrollment_a):
    """Default enrollment"""
    return enrollment_a


# =====================================================
# Attempts
# =====================================================

@pytest.fixture(scope="function")
def attempt(db, enrollment_a, question_with_options):
    """Basic attempt"""
    attempt = AssessmentAttempt.objects.create(
        tenant=enrollment_a.tenant,
        student_assessment=enrollment_a,
        status="started"
    )

    # Add answer
    AttemptAnswer.objects.create(
        tenant=enrollment_a.tenant,
        attempt=attempt,
        question=question_with_options,
        selected_option=question_with_options.options.filter(is_correct=True).first(),
        is_correct=True,
        points_earned=1
    )

    return attempt


@pytest.fixture(scope="function")
def attempt_started(db, enrollment_a, question_with_options):
    """Started attempt (alias for attempt)"""
    attempt = AssessmentAttempt.objects.create(
        tenant=enrollment_a.tenant,
        student_assessment=enrollment_a,
        status="started"
    )

    # Add answer
    AttemptAnswer.objects.create(
        tenant=enrollment_a.tenant,
        attempt=attempt,
        question=question_with_options,
        selected_option=question_with_options.options.filter(is_correct=True).first(),
        is_correct=True,
        points_earned=1
    )

    return attempt


@pytest.fixture(scope="function")
def attempt_submitted(db, enrollment_a, question_with_options):
    """Submitted attempt"""
    attempt = AssessmentAttempt.objects.create(
        tenant=enrollment_a.tenant,
        student_assessment=enrollment_a,
        status="submitted",
        started_at=timezone.now() - timedelta(minutes=10),
        submitted_at=timezone.now(),
        time_spent_seconds=600
    )

    # Add answer
    AttemptAnswer.objects.create(
        tenant=enrollment_a.tenant,
        attempt=attempt,
        question=question_with_options,
        selected_option=question_with_options.options.filter(is_correct=True).first(),
        is_correct=True,
        points_earned=1
    )

    return attempt


# =====================================================
# Scores
# =====================================================

@pytest.fixture(scope="function")
def score_passed(db, enrollment_a, attempt_submitted):
    """Passing score"""
    return AssessmentScore.objects.create(
        tenant=enrollment_a.tenant,
        student_assessment=enrollment_a,
        attempt=attempt_submitted,
        total_questions=5,
        correct_answers=4,
        total_points=Decimal("4"),
        max_points=Decimal("5"),
        percentage=Decimal("80.00"),
        status="passed",
        is_passed=True,
        breakdown_by_topic={
            "Basics": {"correct": 4, "total": 5, "percentage": 80.0}
        }
    )


@pytest.fixture(scope="function")
def score_failed(db, enrollment_b):
    """Failing score"""
    attempt = AssessmentAttempt.objects.create(
        tenant=enrollment_b.tenant,
        student_assessment=enrollment_b,
        status="submitted",
        submitted_at=timezone.now(),
        time_spent_seconds=600
    )

    return AssessmentScore.objects.create(
        tenant=enrollment_b.tenant,
        student_assessment=enrollment_b,
        attempt=attempt,
        total_questions=10,
        correct_answers=3,
        total_points=Decimal("3"),
        max_points=Decimal("10"),
        percentage=Decimal("30.00"),
        status="failed",
        is_passed=False,
        breakdown_by_topic={}
    )


@pytest.fixture(scope="function")
def score_passed_for_certificate(db, tenant_a, student_a, assessment_a, staff_user_a):
    """Fresh passing score for certificate generation (certificate_generated=False)"""
    # Use base_objects to get or create, handling constraint properly
    try:
        enrollment = StudentAssessment.objects.get(
            tenant=tenant_a,
            student=student_a,
            assessment=assessment_a
        )
    except StudentAssessment.DoesNotExist:
        enrollment = StudentAssessment.objects.create(
            tenant=tenant_a,
            student=student_a,
            assessment=assessment_a,
            status="scheduled"
        )

    attempt = AssessmentAttempt.objects.create(
        tenant=tenant_a,
        student_assessment=enrollment,
        status="submitted",
        started_at=timezone.now() - timedelta(minutes=10),
        submitted_at=timezone.now(),
        time_spent_seconds=600
    )

    # Create AttemptAnswer for the question_with_options
    q = Question.objects.create(
        tenant=tenant_a,
        assessment=assessment_a,
        text="Test question",
        difficulty="easy",
        status="published",
        created_by=staff_user_a
    )
    option = QuestionOption.objects.create(
        tenant=tenant_a,
        question=q,
        text="Correct",
        is_correct=True,
        display_order=0
    )
    AttemptAnswer.objects.create(
        tenant=tenant_a,
        attempt=attempt,
        question=q,
        selected_option=option,
        is_correct=True,
        points_earned=1
    )

    return AssessmentScore.objects.create(
        tenant=tenant_a,
        student_assessment=enrollment,
        attempt=attempt,
        total_questions=1,
        correct_answers=1,
        total_points=Decimal("1"),
        max_points=Decimal("1"),
        percentage=Decimal("100.00"),
        status="passed",
        is_passed=True,
        breakdown_by_topic={
            "Test": {"correct": 1, "total": 1, "percentage": 100.0}
        },
        certificate_generated=False  # Explicitly not generated yet
    )


@pytest.fixture(scope="function")
def score(score_passed):
    """Default score"""
    return score_passed


# =====================================================
# Services
# =====================================================

@pytest.fixture(scope="function")
def assessment_service(tenant):
    """AssessmentService"""
    return AssessmentService(tenant)


@pytest.fixture(scope="function")
def question_service(tenant):
    """QuestionService"""
    return QuestionService(tenant)


@pytest.fixture(scope="function")
def attempt_service(tenant):
    """AttemptService"""
    return AttemptService(tenant)


@pytest.fixture(scope="function")
def grading_service(tenant):
    """GradingService"""
    return GradingService(tenant)


@pytest.fixture(scope="function")
def certificate_service(tenant):
    """CertificateService"""
    return CertificateService(tenant)


# =====================================================
# API Client
# =====================================================

@pytest.fixture(scope="function")
def api_client_a(client, staff_user_a):
    """API client authenticated as Tenant A staff"""
    client.force_login(staff_user_a)
    return client


@pytest.fixture(scope="function")
def api_client_b(client, staff_user_b):
    """API client authenticated as Tenant B staff"""
    client.force_login(staff_user_b)
    return client


@pytest.fixture(scope="function")
def api_client(api_client_a):
    """Default API client"""
    return api_client_a
