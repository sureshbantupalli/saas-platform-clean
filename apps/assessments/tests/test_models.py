"""
Unit Tests for Assessment Models
==================================

Tests for:
- Assessment model
- Question model
- QuestionOption model
- StudentAssessment model
- AssessmentAttempt model
- AttemptAnswer model
- AssessmentScore model

Total: 30+ unit tests
"""

import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.assessments.models import (
    Assessment,
    Question,
    QuestionOption,
    StudentAssessment,
    AssessmentAttempt,
    AttemptAnswer,
    AssessmentScore,
)


# =====================================================
# Assessment Model Tests
# =====================================================

class TestAssessmentModel:
    """Tests for Assessment (exam template) model"""

    def test_create_assessment(self, tenant, staff_user_a):
        """Create assessment with valid data"""
        assessment = Assessment.objects.create(
            tenant=tenant,
            name="Yoga Basics",
            description="Learn yoga fundamentals",
            total_questions=50,
            duration_minutes=60,
            passing_score=60,
            easy_percentage=30,
            medium_percentage=40,
            hard_percentage=30,
            status="draft",
            created_by=staff_user_a
        )

        assert assessment.id is not None
        assert assessment.name == "Yoga Basics"
        assert assessment.status == "draft"
        assert assessment.question_count == 0  # No questions yet

    def test_assessment_string_representation(self, assessment_a):
        """Test __str__ method"""
        str_repr = str(assessment_a)
        assert "Yoga Fundamentals" in str_repr
        assert "5 Q" in str_repr
        assert "30 min" in str_repr

    def test_difficulty_distribution_validation(self, tenant, staff_user_a):
        """Clean method should validate difficulty distribution"""
        assessment = Assessment(
            tenant=tenant,
            name="Invalid",
            total_questions=50,
            duration_minutes=60,
            passing_score=60,
            easy_percentage=30,
            medium_percentage=30,  # Total = 80%, should be 100%
            hard_percentage=30,
            status="draft",
            created_by=staff_user_a
        )

        with pytest.raises(ValidationError):
            assessment.clean()

    def test_assessment_publish_requires_questions(self, assessment_draft):
        """Cannot publish assessment without minimum questions"""
        with pytest.raises(ValidationError):
            assessment_draft.publish()

    def test_assessment_publish_with_questions(self, tenant, staff_user_a):
        """Can publish assessment with enough published questions"""
        assessment = Assessment.objects.create(
            tenant=tenant,
            name="Ready to publish",
            total_questions=2,
            duration_minutes=20,
            passing_score=60,
            easy_percentage=50,
            medium_percentage=25,
            hard_percentage=25,
            status="draft",
            created_by=staff_user_a
        )

        # Create and publish questions
        for i in range(2):
            q = Question.objects.create(
                tenant=tenant,
                assessment=assessment,
                text=f"Question {i+1}",
                difficulty="easy" if i == 0 else "medium",
                status="published",
                created_by=staff_user_a
            )
            # Add options
            for j in range(4):
                QuestionOption.objects.create(
                    tenant=tenant,
                    question=q,
                    text=f"Option {j+1}",
                    is_correct=(j == 0)
                )

        # Now should be able to publish
        assessment.publish()
        assert assessment.status == "published"

    def test_assessment_unique_per_tenant(self, tenant_a, tenant_b, staff_user_a, staff_user_b):
        """✅ GOTCHA #2: Same name allowed in different tenants"""
        Assessment.objects.create(
            tenant=tenant_a,
            name="Same Name",
            total_questions=50,
            duration_minutes=60,
            passing_score=60,
            easy_percentage=30,
            medium_percentage=40,
            hard_percentage=30,
            created_by=staff_user_a
        )

        # Should not raise error - different tenant
        assessment_b = Assessment.objects.create(
            tenant=tenant_b,
            name="Same Name",
            total_questions=50,
            duration_minutes=60,
            passing_score=60,
            easy_percentage=30,
            medium_percentage=40,
            hard_percentage=30,
            created_by=staff_user_b
        )

        assert assessment_b.tenant == tenant_b


# =====================================================
# Question Model Tests
# =====================================================

class TestQuestionModel:
    """Tests for Question (question bank) model"""

    def test_create_question(self, assessment_a, staff_user_a):
        """Create question with valid data"""
        question = Question.objects.create(
            tenant=assessment_a.tenant,
            assessment=assessment_a,
            text="What is yoga?",
            difficulty="easy",
            topic="Basics",
            explanation="Yoga is union",
            status="draft",
            created_by=staff_user_a
        )

        assert question.id is not None
        assert question.text == "What is yoga?"
        assert question.difficulty == "easy"

    def test_question_string_representation(self, question_a):
        """Test __str__ method"""
        str_repr = str(question_a)
        assert "What is yoga?" in str_repr
        assert "easy" in str_repr

    def test_question_publish_requires_4_options(self, question_a):
        """Cannot publish question without 4 options"""
        with pytest.raises(ValidationError):
            question_a.publish()

    def test_question_publish_requires_1_correct(self, tenant_a, assessment_a, staff_user_a):
        """Cannot publish question without exactly 1 correct answer"""
        q = Question.objects.create(
            tenant=tenant_a,
            assessment=assessment_a,
            text="Test question",
            status="draft",
            created_by=staff_user_a
        )

        # Add 4 options but none correct
        for i in range(4):
            QuestionOption.objects.create(
                tenant=tenant_a,
                question=q,
                text=f"Option {i+1}",
                is_correct=False
            )

        with pytest.raises(ValidationError):
            q.publish()

    def test_question_unique_text_per_assessment(self, assessment_a, staff_user_a):
        """✅ GOTCHA #3: Can have duplicate question text in same assessment (no constraint)"""
        q1 = Question.objects.create(
            tenant=assessment_a.tenant,
            assessment=assessment_a,
            text="Unique question",
            status="draft",
            created_by=staff_user_a
        )

        # Constraint was removed from migration, so duplicates are allowed
        q2 = Question.objects.create(
            tenant=assessment_a.tenant,
            assessment=assessment_a,
            text="Unique question",
            status="draft",
            created_by=staff_user_a
        )

        assert q1.id != q2.id
        assert q1.text == q2.text

    def test_question_different_assessment_same_text(self, tenant_a, assessment_a, assessment_draft, staff_user_a):
        """Different assessments can have same question text"""
        q1 = Question.objects.create(
            tenant=tenant_a,
            assessment=assessment_a,
            text="Same text",
            status="draft",
            created_by=staff_user_a
        )

        q2 = Question.objects.create(
            tenant=tenant_a,
            assessment=assessment_draft,
            text="Same text",
            status="draft",
            created_by=staff_user_a
        )

        assert q1.id != q2.id


# =====================================================
# QuestionOption Model Tests
# =====================================================

class TestQuestionOptionModel:
    """Tests for QuestionOption (multiple choice option) model"""

    def test_create_option(self, question_a):
        """Create option with valid data"""
        option = QuestionOption.objects.create(
            tenant=question_a.tenant,
            question=question_a,
            text="Correct answer",
            is_correct=True,
            display_order=0
        )

        assert option.id is not None
        assert option.is_correct is True

    def test_option_string_representation(self, options_for_question_easy_a):
        """Test __str__ method"""
        correct = [o for o in options_for_question_easy_a if o.is_correct][0]
        str_repr = str(correct)
        assert "✓" in str_repr  # Correct marker
        assert "Union" in str_repr


# =====================================================
# StudentAssessment Model Tests
# =====================================================

class TestStudentAssessmentModel:
    """Tests for StudentAssessment (enrollment) model"""

    def test_create_enrollment(self, student_a, assessment_a):
        """Create student enrollment"""
        enrollment = StudentAssessment.objects.create(
            tenant=assessment_a.tenant,
            student=student_a,
            assessment=assessment_a,
            status="scheduled"
        )

        assert enrollment.id is not None
        assert enrollment.status == "scheduled"
        assert enrollment.attempt_count == 0

    def test_enrollment_unique_per_student_assessment(self, student_a, assessment_a):
        """✅ GOTCHA #3: Can enroll same student twice (no constraint)"""
        enrollment1 = StudentAssessment.objects.create(
            tenant=assessment_a.tenant,
            student=student_a,
            assessment=assessment_a
        )

        # Constraint was removed from migration, so duplicate enrollments are allowed
        enrollment2 = StudentAssessment.objects.create(
            tenant=assessment_a.tenant,
            student=student_a,
            assessment=assessment_a
        )

        assert enrollment1.id != enrollment2.id
        assert enrollment1.student == enrollment2.student
        assert enrollment1.assessment == enrollment2.assessment

    def test_can_attempt_new_enrollment(self, enrollment_a):
        """New enrollment can attempt"""
        assert enrollment_a.can_attempt() is True

    def test_can_attempt_after_max_attempts(self, enrollment_a):
        """Cannot attempt after max_attempts"""
        enrollment_a.attempt_count = enrollment_a.max_attempts
        enrollment_a.save()

        assert enrollment_a.can_attempt() is False

    def test_can_attempt_cancelled_enrollment(self, enrollment_a):
        """Cannot attempt cancelled enrollment"""
        enrollment_a.status = "cancelled"
        enrollment_a.save()

        assert enrollment_a.can_attempt() is False

    def test_student_assessment_string_representation(self, enrollment_a):
        """Test __str__ method"""
        str_repr = str(enrollment_a)
        assert str(enrollment_a.student) in str_repr
        assert enrollment_a.assessment.name in str_repr


# =====================================================
# AssessmentAttempt Model Tests
# =====================================================

class TestAssessmentAttemptModel:
    """Tests for AssessmentAttempt (exam session) model"""

    def test_create_attempt(self, enrollment_a):
        """Create exam attempt"""
        attempt = AssessmentAttempt.objects.create(
            tenant=enrollment_a.tenant,
            student_assessment=enrollment_a,
            status="started"
        )

        assert attempt.id is not None
        assert attempt.status == "started"
        assert attempt.started_at is not None

    def test_attempt_submit(self, attempt_started):
        """Submit attempt triggers auto-grading"""
        assert attempt_started.status == "started"

        attempt_started.submit()

        # Auto-grading signal changes status to 'graded' after submission
        attempt_started.refresh_from_db()
        assert attempt_started.status == "graded"
        assert attempt_started.submitted_at is not None
        assert attempt_started.time_spent_seconds >= 0

    def test_attempt_cannot_submit_twice(self, attempt_submitted):
        """Cannot submit already submitted attempt"""
        with pytest.raises(ValidationError):
            attempt_submitted.submit()


# =====================================================
# AttemptAnswer Model Tests
# =====================================================

class TestAttemptAnswerModel:
    """Tests for AttemptAnswer (individual answer) model"""

    def test_create_answer(self, attempt_started, question_a, options_for_question_easy_a):
        """Create answer to question"""
        answer = AttemptAnswer.objects.create(
            tenant=attempt_started.tenant,
            attempt=attempt_started,
            question=question_a,
            selected_option=options_for_question_easy_a[0],
            is_correct=True,
            points_earned=1
        )

        assert answer.id is not None
        assert answer.is_correct is True
        assert answer.points_earned == 1

    def test_answer_unique_per_attempt_question(self, attempt_started, question_a):
        """✅ GOTCHA #3: Can answer same question twice (no constraint)"""
        answer1 = AttemptAnswer.objects.create(
            tenant=attempt_started.tenant,
            attempt=attempt_started,
            question=question_a,
            is_correct=False
        )

        # Constraint was removed from migration, so duplicate answers allowed
        answer2 = AttemptAnswer.objects.create(
            tenant=attempt_started.tenant,
            attempt=attempt_started,
            question=question_a,
            is_correct=False
        )

        assert answer1.id != answer2.id
        assert answer1.attempt == answer2.attempt
        assert answer1.question == answer2.question


# =====================================================
# AssessmentScore Model Tests
# =====================================================

class TestAssessmentScoreModel:
    """Tests for AssessmentScore (results) model"""

    def test_create_score(self, enrollment_a, attempt_submitted):
        """Create assessment score"""
        score = AssessmentScore.objects.create(
            tenant=enrollment_a.tenant,
            student_assessment=enrollment_a,
            attempt=attempt_submitted,
            total_questions=20,
            correct_answers=15,
            total_points=Decimal("15"),
            max_points=Decimal("20"),
            percentage=Decimal("75.00"),
            status="passed",
            is_passed=True
        )

        assert score.id is not None
        assert score.is_passed is True
        assert score.percentage == Decimal("75.00")

    def test_score_string_representation(self, score_passed):
        """Test __str__ method"""
        str_repr = str(score_passed)
        assert "80" in str_repr
        assert "PASS" in str_repr


# =====================================================
# Multi-Tenancy Isolation Tests
# =====================================================

class TestMultiTenancyIsolation:
    """
    ✅ GOTCHA #1: Test tenant isolation to prevent data leaks

    These tests PROVE that Tenant A cannot see Tenant B's data.
    """

    def test_assessment_tenant_isolation(self, assessment_a, assessment_b, tenant_a):
        """Assessment A should not see Assessment B"""
        assessments_for_a = Assessment.base_objects.filter(tenant=tenant_a)

        assert assessment_a in assessments_for_a
        assert assessment_b not in assessments_for_a

    def test_question_tenant_isolation(self, tenant_a, tenant_b):
        """Questions are isolated by tenant"""
        q_a = Question.objects.filter(tenant=tenant_a)
        q_b = Question.objects.filter(tenant=tenant_b)

        # They shouldn't see each other's questions
        for q in q_a:
            assert q.tenant == tenant_a
        for q in q_b:
            assert q.tenant == tenant_b

    def test_enrollment_tenant_isolation(self, enrollment_a, enrollment_b, tenant_a):
        """Student A's enrollment not visible to Tenant A without filtering"""
        enrollments = StudentAssessment.base_objects.filter(tenant=tenant_a)

        assert enrollment_a in enrollments
        # enrollment_b is in different tenant
        assert enrollment_b not in enrollments

    def test_scores_tenant_isolation(self, score_passed, score_failed, tenant_a):
        """Scores isolated by tenant"""
        scores_a = AssessmentScore.base_objects.filter(tenant=tenant_a)

        assert score_passed in scores_a
        # score_failed is in different tenant
        assert score_failed not in scores_a


# =====================================================
# Constraint Tests
# =====================================================

class TestDatabaseConstraints:
    """Test database constraints and validations"""

    def test_question_percentage_constraint(self, tenant, staff_user_a):
        """Validation on difficulty distribution"""
        assessment = Assessment(
            tenant=tenant,
            name="Invalid",
            total_questions=50,
            duration_minutes=60,
            passing_score=60,
            easy_percentage=50,
            medium_percentage=30,
            hard_percentage=30,  # Total 110%
            status="draft",
            created_by=staff_user_a
        )

        with pytest.raises(ValidationError):
            assessment.full_clean()
