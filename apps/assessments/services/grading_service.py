"""
GradingService: Automatic grading and score calculation.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.assessments.models import (
    AssessmentAttempt,
    AssessmentScore,
    StudentAssessment,
    AttemptAnswer
)


class GradingService:
    """
    Service for automatic grading, score calculation, and pass/fail determination.
    """

    def __init__(self, tenant):
        """
        Initialize with tenant for isolation.
        """
        self.tenant = tenant

    def grade_attempt(self, attempt):
        """
        Grade a submitted attempt and create score record.

        Args:
            attempt: AssessmentAttempt (must be submitted)

        Returns:
            AssessmentScore instance

        Raises:
            ValidationError: If attempt not submitted or already graded
        """
        if attempt.tenant != self.tenant:
            raise ValidationError("Attempt does not belong to your tenant")

        if attempt.status != "submitted":
            raise ValidationError(
                f"Cannot grade attempt with status: {attempt.status}"
            )

        # Check if already graded
        if hasattr(attempt, 'score'):
            raise ValidationError("Attempt is already graded")

        student_assessment = attempt.student_assessment
        assessment = student_assessment.assessment

        with transaction.atomic():
            # Calculate scores
            answers = attempt.answers.select_related("question")
            total_questions = answers.count()
            correct_answers = answers.filter(is_correct=True).count()
            total_points = Decimal(correct_answers)
            max_points = Decimal(total_questions)

            # Calculate percentage
            if max_points > 0:
                percentage = (total_points / max_points) * 100
            else:
                percentage = Decimal(0)

            # ✅ GOTCHA #11: Round percentage correctly for display
            percentage = percentage.quantize(Decimal("0.01"))

            # Determine pass/fail
            is_passed = percentage >= assessment.passing_score
            status = "passed" if is_passed else "failed"

            # Calculate breakdown by topic
            breakdown_by_topic = self._calculate_topic_breakdown(answers)

            # Create score record
            score = AssessmentScore.objects.create(
                tenant=self.tenant,
                student_assessment=student_assessment,
                attempt=attempt,
                total_questions=total_questions,
                correct_answers=correct_answers,
                total_points=total_points,
                max_points=max_points,
                percentage=percentage,
                status=status,
                is_passed=is_passed,
                breakdown_by_topic=breakdown_by_topic
            )

            # Update student assessment
            student_assessment.status = "graded"
            if is_passed:
                student_assessment.status = "passed"
            else:
                student_assessment.status = "failed"

            # Track best score
            if student_assessment.best_score is None or percentage > student_assessment.best_score:
                student_assessment.best_score = percentage

            student_assessment.save()

            # Mark attempt as graded
            attempt.status = "graded"
            attempt.save()

        return score

    def _calculate_topic_breakdown(self, answers):
        """
        Calculate score breakdown by topic.

        Returns:
            Dict: {
                "Asanas": {"correct": 8, "total": 10, "percentage": 80.0},
                "Pranayama": {"correct": 6, "total": 10, "percentage": 60.0},
                ...
            }
        """
        breakdown = {}

        for answer in answers:
            topic = answer.question.topic or "Uncategorized"

            if topic not in breakdown:
                breakdown[topic] = {
                    "correct": 0,
                    "total": 0,
                    "percentage": 0.0
                }

            breakdown[topic]["total"] += 1
            if answer.is_correct:
                breakdown[topic]["correct"] += 1

        # Calculate percentages
        for topic, stats in breakdown.items():
            if stats["total"] > 0:
                stats["percentage"] = float(
                    Decimal(stats["correct"]) / Decimal(stats["total"]) * 100
                )

        return breakdown

    def get_grade_report(self, score):
        """
        Get detailed grade report for display.

        Args:
            score: AssessmentScore

        Returns:
            Dict with detailed report
        """
        if score.tenant != self.tenant:
            raise ValidationError("Score does not belong to your tenant")

        student = score.student_assessment.student
        assessment = score.student_assessment.assessment

        return {
            "student_name": str(student),
            "assessment_name": assessment.name,
            "total_questions": score.total_questions,
            "correct_answers": score.correct_answers,
            "percentage": float(score.percentage),
            "passing_score": float(assessment.passing_score),
            "is_passed": score.is_passed,
            "status": score.status,
            "time_spent": self._format_time(score.attempt.time_spent_seconds),
            "breakdown_by_topic": score.breakdown_by_topic,
            "attempted_at": score.attempt.started_at.isoformat(),
            "graded_at": score.created_at.isoformat(),
        }

    def _format_time(self, seconds):
        """Format seconds into HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def get_student_performance_summary(self, student, assessment):
        """
        Get student's performance summary for an assessment.

        Args:
            student: Member object
            assessment: Assessment object

        Returns:
            Dict with:
                - attempts_total: Total attempts
                - attempts_passed: Number of passing attempts
                - best_score: Highest score
                - latest_attempt: Most recent attempt info
                - is_passed: Overall pass status
        """
        try:
            enrollment = StudentAssessment.objects.get(
                tenant=self.tenant,
                student=student,
                assessment=assessment
            )
        except StudentAssessment.DoesNotExist:
            return None

        scores = AssessmentScore.objects.filter(
            student_assessment=enrollment
        ).order_by("-created_at")

        if not scores.exists():
            return {
                "attempts_total": enrollment.attempt_count,
                "attempts_passed": 0,
                "best_score": None,
                "latest_attempt": None,
                "is_passed": False
            }

        latest_score = scores.first()
        passed_count = scores.filter(is_passed=True).count()

        return {
            "attempts_total": enrollment.attempt_count,
            "attempts_passed": passed_count,
            "best_score": float(enrollment.best_score) if enrollment.best_score else None,
            "latest_attempt": {
                "percentage": float(latest_score.percentage),
                "status": latest_score.status,
                "attempted_at": latest_score.attempt.started_at.isoformat(),
            },
            "is_passed": passed_count > 0
        }
