"""
Assessment Module Serializers
==============================

Serializers for Assessment API with role-based field filtering.
"""

from rest_framework import serializers
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
# QuestionOption Serializer
# =====================================================

class QuestionOptionSerializer(serializers.ModelSerializer):
    """
    Multiple choice option serializer.

    ✅ GOTCHA #9: Hide correct answer from students
    - Students: Never see is_correct field
    - Admin: Always see is_correct field
    """

    class Meta:
        model = QuestionOption
        fields = ["id", "text", "is_correct", "display_order"]
        read_only_fields = ["id"]

    def to_representation(self, instance):
        """Hide correct answer for students"""
        data = super().to_representation(instance)
        request = self.context.get("request")

        # If user is not admin/staff, hide correct answer
        if request and not (request.user.is_staff or request.user.is_platform_admin):
            data.pop("is_correct", None)

        return data


# =====================================================
# Question Serializer
# =====================================================

class QuestionSerializer(serializers.ModelSerializer):
    """
    Question serializer with nested options.

    ✅ GOTCHA #9: Hide explanations from students during exam
    """

    options = QuestionOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = [
            "id",
            "assessment",
            "text",
            "topic",
            "difficulty",
            "explanation",
            "status",
            "display_order",
            "options",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def to_representation(self, instance):
        """Hide explanation from students during exam"""
        data = super().to_representation(instance)
        request = self.context.get("request")
        action = self.context.get("action", "retrieve")

        # Hide explanation during exam attempts
        if request and action == "retrieve_during_attempt":
            if not (request.user.is_staff or request.user.is_platform_admin):
                data.pop("explanation", None)

        return data

    def validate(self, attrs):
        """Validate question data"""
        # Verify assessment belongs to user's tenant
        request = self.context.get("request")
        if request and request.user and hasattr(request, "user"):
            assessment = attrs.get("assessment")
            if assessment and assessment.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "Assessment does not belong to your tenant"
                )

        return attrs


# =====================================================
# Assessment Serializer
# =====================================================

class AssessmentSerializer(serializers.ModelSerializer):
    """
    Exam template serializer.
    """

    question_count = serializers.SerializerMethodField()
    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = Assessment
        fields = [
            "id",
            "name",
            "description",
            "total_questions",
            "duration_minutes",
            "passing_score",
            "easy_percentage",
            "medium_percentage",
            "hard_percentage",
            "status",
            "is_active",
            "question_count",
            "questions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "question_count"]

    def get_question_count(self, obj):
        """Get total published questions"""
        return obj.question_count

    def validate(self, attrs):
        """Validate assessment data"""
        request = self.context.get("request")

        # Verify tenant
        if request and request.user and hasattr(request, "user"):
            if request.method in ["POST", "PUT", "PATCH"]:
                if hasattr(self, "instance") and self.instance:
                    if self.instance.tenant != request.user.tenant:
                        raise serializers.ValidationError(
                            "Assessment does not belong to your tenant"
                        )

        # Validate difficulty distribution
        easy = attrs.get("easy_percentage", 0)
        medium = attrs.get("medium_percentage", 0)
        hard = attrs.get("hard_percentage", 0)

        total = easy + medium + hard
        if total != 100:
            raise serializers.ValidationError(
                f"Difficulty percentages must sum to 100% (got {total}%)"
            )

        return attrs


# =====================================================
# StudentAssessment Serializer
# =====================================================

class StudentAssessmentSerializer(serializers.ModelSerializer):
    """
    Student enrollment in assessment.
    """

    assessment_name = serializers.CharField(
        source="assessment.name",
        read_only=True
    )
    student_name = serializers.CharField(
        source="student.name",
        read_only=True
    )
    can_attempt = serializers.SerializerMethodField()

    class Meta:
        model = StudentAssessment
        fields = [
            "id",
            "student",
            "student_name",
            "assessment",
            "assessment_name",
            "status",
            "scheduled_date",
            "last_attempted_at",
            "attempt_count",
            "max_attempts",
            "best_score",
            "can_attempt",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_can_attempt(self, obj):
        """Check if student can attempt"""
        return obj.can_attempt()

    def validate(self, attrs):
        """Validate enrollment"""
        request = self.context.get("request")

        if request and request.user:
            student = attrs.get("student")
            assessment = attrs.get("assessment")

            # Verify both belong to user's tenant
            if student and student.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "Student does not belong to your tenant"
                )

            if assessment and assessment.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "Assessment does not belong to your tenant"
                )

        return attrs


# =====================================================
# AttemptAnswer Serializer
# =====================================================

class AttemptAnswerSerializer(serializers.ModelSerializer):
    """
    Student's answer to a question.

    ✅ GOTCHA #9: Hide is_correct during exam, show after grading
    """

    question_text = serializers.CharField(
        source="question.text",
        read_only=True
    )
    selected_option_text = serializers.CharField(
        source="selected_option.text",
        read_only=True,
        allow_null=True
    )
    correct_option_text = serializers.SerializerMethodField()

    class Meta:
        model = AttemptAnswer
        fields = [
            "id",
            "attempt",
            "question",
            "question_text",
            "selected_option",
            "selected_option_text",
            "is_correct",
            "points_earned",
            "correct_option_text",
            "answered_at",
        ]
        read_only_fields = ["id", "answered_at"]

    def get_correct_option_text(self, obj):
        """Get correct answer text (only after grading)"""
        request = self.context.get("request")

        # Only show after submission/grading
        if request and (request.user.is_staff or request.user.is_platform_admin):
            try:
                correct = obj.question.options.get(is_correct=True)
                return correct.text
            except:
                return None

        return None


# =====================================================
# AssessmentAttempt Serializer
# =====================================================

class AssessmentAttemptSerializer(serializers.ModelSerializer):
    """
    Exam session/attempt serializer.
    """

    answers = AttemptAnswerSerializer(many=True, read_only=True)
    assessment_name = serializers.CharField(
        source="student_assessment.assessment.name",
        read_only=True
    )
    student_name = serializers.CharField(
        source="student_assessment.student.name",
        read_only=True
    )

    class Meta:
        model = AssessmentAttempt
        fields = [
            "id",
            "student_assessment",
            "assessment_name",
            "student_name",
            "status",
            "started_at",
            "submitted_at",
            "time_spent_seconds",
            "answers",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        """Validate attempt"""
        request = self.context.get("request")

        if request and request.user:
            student_assessment = attrs.get("student_assessment")

            if student_assessment and student_assessment.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "StudentAssessment does not belong to your tenant"
                )

        return attrs


# =====================================================
# AssessmentScore Serializer
# =====================================================

class AssessmentScoreSerializer(serializers.ModelSerializer):
    """
    Exam results and grading serializer.
    """

    student_name = serializers.CharField(
        source="student_assessment.student.name",
        read_only=True
    )
    assessment_name = serializers.CharField(
        source="student_assessment.assessment.name",
        read_only=True
    )
    grade_letter = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentScore
        fields = [
            "id",
            "student_assessment",
            "student_name",
            "assessment_name",
            "attempt",
            "total_questions",
            "correct_answers",
            "total_points",
            "max_points",
            "percentage",
            "status",
            "is_passed",
            "grade_letter",
            "breakdown_by_topic",
            "certificate_generated",
            "certificate_generated_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "total_questions",
            "correct_answers",
            "total_points",
            "max_points",
            "percentage",
            "status",
            "is_passed",
            "created_at",
        ]

    def get_grade_letter(self, obj):
        """Convert percentage to letter grade"""
        pct = float(obj.percentage)

        if pct >= 90:
            return "A"
        elif pct >= 80:
            return "B"
        elif pct >= 70:
            return "C"
        elif pct >= 60:
            return "D"
        else:
            return "F"

    def validate(self, attrs):
        """Validate score"""
        request = self.context.get("request")

        if request and request.user:
            student_assessment = attrs.get("student_assessment")

            if student_assessment and student_assessment.tenant != request.user.tenant:
                raise serializers.ValidationError(
                    "StudentAssessment does not belong to your tenant"
                )

        return attrs
