"""
AttemptService: Manage exam attempts and student answers.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

from apps.assessments.models import (
    StudentAssessment,
    AssessmentAttempt,
    AttemptAnswer,
    QuestionOption
)
from apps.assessments.services.question_service import QuestionService


class AttemptService:
    """
    Service for starting attempts, recording answers, and submitting exams.
    """

    def __init__(self, tenant):
        """
        Initialize with tenant for isolation.
        """
        self.tenant = tenant
        self.question_service = QuestionService(tenant)

    def start_attempt(self, student_assessment):
        """
        Start a new exam attempt for a student.

        Args:
            student_assessment: StudentAssessment enrollment

        Returns:
            AssessmentAttempt instance with questions

        Raises:
            ValidationError: If student cannot attempt now
        """
        if student_assessment.tenant != self.tenant:
            raise ValidationError(
                "StudentAssessment does not belong to your tenant"
            )

        # Check if student can attempt
        if not student_assessment.can_attempt():
            raise ValidationError(
                f"Student has reached maximum attempts ({student_assessment.max_attempts})"
            )

        # Get questions for this attempt
        assessment = student_assessment.assessment
        questions = self.question_service.get_random_questions(
            assessment=assessment,
            count=assessment.total_questions
        )

        if not questions:
            raise ValidationError(
                f"Not enough published questions in assessment"
            )

        # Create attempt
        with transaction.atomic():
            attempt = AssessmentAttempt.objects.create(
                tenant=self.tenant,
                student_assessment=student_assessment
            )

            # Add questions to attempt (via through model)
            for question in questions:
                AttemptAnswer.objects.create(
                    tenant=self.tenant,
                    attempt=attempt,
                    question=question,
                    is_correct=False,
                    points_earned=0
                )

            # Update student assessment
            student_assessment.status = "in_progress"
            student_assessment.last_attempted_at = timezone.now()
            student_assessment.attempt_count += 1
            student_assessment.save()

        return attempt

    def save_answer(self, attempt, question_id, selected_option_id):
        """
        Save a student's answer to a question.

        Args:
            attempt: AssessmentAttempt
            question_id: Question UUID
            selected_option_id: Selected QuestionOption UUID

        Returns:
            AttemptAnswer instance

        Raises:
            ValidationError: If invalid question/option or attempt already submitted
        """
        if attempt.tenant != self.tenant:
            raise ValidationError("Attempt does not belong to your tenant")

        if attempt.status != "started":
            raise ValidationError("Cannot save answers to submitted attempts")

        try:
            # Get answer record (created in start_attempt)
            answer = AttemptAnswer.objects.get(
                tenant=self.tenant,
                attempt=attempt,
                question_id=question_id
            )
        except AttemptAnswer.DoesNotExist:
            raise ValidationError(
                "Question not found in this attempt"
            )

        # Get selected option
        try:
            selected_option = QuestionOption.objects.get(
                tenant=self.tenant,
                id=selected_option_id,
                question_id=question_id
            )
        except QuestionOption.DoesNotExist:
            raise ValidationError("Invalid option selected")

        # Update answer
        answer.selected_option = selected_option
        answer.is_correct = selected_option.is_correct

        # Score (1 point per correct answer)
        if answer.is_correct:
            answer.points_earned = 1
        else:
            answer.points_earned = 0

        answer.save()

        return answer

    def submit_exam(self, attempt):
        """
        Submit completed exam and trigger grading.

        Args:
            attempt: AssessmentAttempt

        Returns:
            AssessmentAttempt with submitted status

        Raises:
            ValidationError: If attempt already submitted
        """
        if attempt.tenant != self.tenant:
            raise ValidationError("Attempt does not belong to your tenant")

        if attempt.status != "started":
            raise ValidationError("Attempt is already submitted")

        # Mark as submitted
        attempt.submit()

        # ✅ Trigger automatic grading
        # (This would call GradingService in a real implementation)
        # For now, just mark as submitted

        return attempt

    def get_current_attempt(self, student_assessment):
        """
        Get the student's current in-progress attempt.

        Args:
            student_assessment: StudentAssessment

        Returns:
            AssessmentAttempt instance or None

        Raises:
            ValidationError: If student_assessment invalid
        """
        if student_assessment.tenant != self.tenant:
            raise ValidationError(
                "StudentAssessment does not belong to your tenant"
            )

        try:
            return AssessmentAttempt.objects.get(
                tenant=self.tenant,
                student_assessment=student_assessment,
                status="started"
            )
        except AssessmentAttempt.DoesNotExist:
            return None

    def get_attempt_progress(self, attempt):
        """
        Get progress on current attempt (questions answered).

        Args:
            attempt: AssessmentAttempt

        Returns:
            Dict with:
                - total: Total questions
                - answered: Number answered
                - remaining: Number not answered
                - percentage: Completion percentage
        """
        if attempt.tenant != self.tenant:
            raise ValidationError("Attempt does not belong to your tenant")

        total = attempt.answers.count()
        answered = attempt.answers.exclude(selected_option__isnull=True).count()
        remaining = total - answered

        return {
            "total": total,
            "answered": answered,
            "remaining": remaining,
            "percentage": int((answered / total * 100) if total > 0 else 0)
        }

    def get_attempt_time_remaining(self, attempt):
        """
        Get time remaining for attempt.

        Args:
            attempt: AssessmentAttempt

        Returns:
            Seconds remaining (negative if time expired)
        """
        if attempt.tenant != self.tenant:
            raise ValidationError("Attempt does not belong to your tenant")

        duration_seconds = attempt.student_assessment.assessment.duration_minutes * 60
        elapsed_seconds = int(
            (timezone.now() - attempt.started_at).total_seconds()
        )
        remaining_seconds = duration_seconds - elapsed_seconds

        return remaining_seconds
