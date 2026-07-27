"""
AssessmentService: Manage exam creation, publishing, and student assignment.
"""

import csv
from io import StringIO
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.assessments.models import Assessment, Question, StudentAssessment


class AssessmentService:
    """
    Service for creating, publishing, and managing assessments.
    """

    def __init__(self, tenant):
        """
        Initialize with tenant for isolation.

        ✅ GOTCHA #5: Services take explicit tenant parameter (not from request).
        This enables testing without request context.
        """
        self.tenant = tenant

    def create_assessment(self, name, duration_minutes, passing_score,
                         total_questions, easy_percentage=30,
                         medium_percentage=40, hard_percentage=30,
                         description="", created_by=None):
        """
        Create a new assessment (exam template).

        Args:
            name: Exam name
            duration_minutes: Time limit
            passing_score: Minimum score to pass (0-100)
            total_questions: Total questions to include
            easy_percentage: % of easy questions
            medium_percentage: % of medium questions
            hard_percentage: % of hard questions
            description: Detailed description
            created_by: User who created

        Returns:
            Assessment instance

        Raises:
            ValidationError: If invalid parameters
        """
        # Validate difficulty distribution
        total_pct = easy_percentage + medium_percentage + hard_percentage
        if total_pct != 100:
            raise ValidationError(
                f"Difficulty percentages must sum to 100% (got {total_pct}%)"
            )

        assessment = Assessment.objects.create(
            tenant=self.tenant,
            name=name,
            description=description,
            duration_minutes=duration_minutes,
            passing_score=passing_score,
            total_questions=total_questions,
            easy_percentage=easy_percentage,
            medium_percentage=medium_percentage,
            hard_percentage=hard_percentage,
            created_by=created_by,
            status="draft"
        )

        return assessment

    def publish_assessment(self, assessment):
        """
        Publish assessment so students can enroll.

        ✅ GOTCHA #7: Verify sufficient questions exist before publishing
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        assessment.publish()  # Raises ValidationError if not ready
        return assessment

    def add_questions_to_assessment(self, assessment, question_ids):
        """
        Add pre-created questions to assessment.

        Args:
            assessment: Assessment to add to
            question_ids: List of question IDs

        Returns:
            List of questions added

        Raises:
            ValidationError: If questions invalid or belong to different tenant
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        questions = Question.objects.filter(
            tenant=self.tenant,
            id__in=question_ids,
            assessment=assessment
        )

        if questions.count() != len(question_ids):
            raise ValidationError(
                f"Some questions not found or don't belong to this assessment"
            )

        return list(questions)

    def get_assessment_for_student(self, assessment_id, student):
        """
        Get assessment details for a student (hide correct answers).

        Args:
            assessment_id: Assessment UUID
            student: Member object

        Returns:
            Assessment with serialized data (correct answers hidden)
        """
        try:
            assessment = Assessment.objects.get(
                tenant=self.tenant,
                id=assessment_id,
                status="published"
            )
        except Assessment.DoesNotExist:
            raise ValidationError("Assessment not found or not published")

        # Check student enrollment
        StudentAssessment.objects.get(
            tenant=self.tenant,
            student=student,
            assessment=assessment
        )

        return assessment

    def enroll_student(self, assessment, student):
        """
        Enroll a student in an assessment.

        Args:
            assessment: Assessment object
            student: Member object

        Returns:
            StudentAssessment instance

        Raises:
            ValidationError: If already enrolled or exam not published
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        if student.tenant != self.tenant:
            raise ValidationError("Student does not belong to your tenant")

        if assessment.status != "published":
            raise ValidationError("Cannot enroll in draft assessments")

        enrollment, created = StudentAssessment.objects.get_or_create(
            tenant=self.tenant,
            student=student,
            assessment=assessment
        )

        return enrollment
