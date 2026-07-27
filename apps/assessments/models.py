"""
Assessment Module Models
========================

Implements complete exam system with:
- Assessment (exam template)
- Question + QuestionOption (question bank)
- StudentAssessment (enrollment)
- AssessmentAttempt + AttemptAnswer (exam taking)
- AssessmentScore (results & grading)

Multi-tenant architecture: All models inherit from TenantAwareModel
for automatic tenant isolation.
"""

import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import TenantAwareModel


# =====================================================
# Assessment Model (Exam Template)
# =====================================================

class Assessment(TenantAwareModel):
    """
    Exam template defining structure, questions, and passing criteria.

    Examples:
    - "Yoga Fundamentals Exam" (50 questions, 60 min, 60% pass score)
    - "Advanced Asanas Test" (30 questions, 45 min, 70% pass score)
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(
        max_length=255,
        help_text="E.g., 'Yoga Fundamentals Exam'"
    )

    description = models.TextField(
        blank=True,
        help_text="Detailed description of what this exam tests"
    )

    # Exam structure
    total_questions = models.PositiveIntegerField(
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(500)],
        help_text="Total number of questions in this exam"
    )

    duration_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(480)],
        help_text="Time limit in minutes (5 min to 8 hours)"
    )

    # Passing criteria
    passing_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=60,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Minimum score (%) to pass (0-100)"
    )

    # Difficulty distribution
    easy_percentage = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of easy questions (0-100)"
    )

    medium_percentage = models.PositiveIntegerField(
        default=40,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of medium questions (0-100)"
    )

    hard_percentage = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of hard questions (0-100)"
    )

    # Status and visibility
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        help_text="Draft = in development, Published = students can take"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Can students enroll in this assessment?"
    )

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_assessments"
    )

    class Meta:
        db_table = "assessments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.total_questions} Q, {self.duration_minutes} min)"

    def clean(self):
        """Validate difficulty distribution adds to 100%"""
        total = self.easy_percentage + self.medium_percentage + self.hard_percentage
        if total != 100:
            raise ValidationError(
                f"Difficulty distribution must add to 100% (got {total}%)"
            )

    def publish(self):
        """Move exam from draft to published"""
        if self.status != "draft":
            raise ValidationError("Only draft exams can be published")

        # ✅ GOTCHA #7: Verify sufficient questions exist
        if self.questions.filter(status="published").count() < self.total_questions:
            raise ValidationError(
                f"Not enough published questions: {self.questions.filter(status='published').count()} "
                f"available, {self.total_questions} required"
            )

        self.status = "published"
        self.save()

    @property
    def question_count(self):
        """Get total published questions available"""
        return self.questions.filter(status="published").count()


# =====================================================
# Question Model (Question Bank)
# =====================================================

class Question(TenantAwareModel):
    """
    Individual question in the question bank.
    Supports multiple-choice with 4 options each.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="questions"
    )

    text = models.TextField(
        help_text="The question text"
    )

    topic = models.CharField(
        max_length=100,
        blank=True,
        help_text="Topic this question covers (e.g., 'Pranayama', 'Asanas')"
    )

    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default="medium"
    )

    explanation = models.TextField(
        blank=True,
        help_text="Explanation shown after answering"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft"
    )

    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order to display questions (0 = random order)"
    )

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_questions"
    )

    class Meta:
        db_table = "questions"
        ordering = ["display_order", "created_at"]
        indexes = [
            models.Index(fields=["assessment", "difficulty"]),
            models.Index(fields=["assessment", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "text"],
                name="unique_question_per_assessment"
            ),
        ]

    def __str__(self):
        return f"Q: {self.text[:50]}... ({self.difficulty})"

    def publish(self):
        """Move question from draft to published"""
        if self.status != "draft":
            raise ValidationError("Only draft questions can be published")

        # ✅ GOTCHA #6: Verify exactly 4 options with 1 correct answer
        options = self.options.all()
        if options.count() != 4:
            raise ValidationError(
                f"Question must have exactly 4 options (has {options.count()})"
            )

        correct_count = options.filter(is_correct=True).count()
        if correct_count != 1:
            raise ValidationError(
                f"Question must have exactly 1 correct answer (has {correct_count})"
            )

        self.status = "published"
        self.save()


# =====================================================
# QuestionOption Model (Multiple Choice Options)
# =====================================================

class QuestionOption(TenantAwareModel):
    """
    Individual option for a multiple-choice question.
    Exactly 1 option per question is marked as correct.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="options"
    )

    text = models.TextField(
        help_text="The option text"
    )

    is_correct = models.BooleanField(
        default=False,
        help_text="Is this the correct answer?"
    )

    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order to display options (0 = random)"
    )

    class Meta:
        db_table = "question_options"
        ordering = ["display_order", "created_at"]
        indexes = [
            models.Index(fields=["question", "is_correct"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "text"],
                name="unique_option_per_question"
            ),
        ]

    def __str__(self):
        marker = "✓" if self.is_correct else "✗"
        return f"{marker} {self.text[:50]}..."


# =====================================================
# StudentAssessment Model (Enrollment)
# =====================================================

class StudentAssessment(TenantAwareModel):
    """
    Student enrollment in an assessment.
    Tracks when exam is scheduled, attempted, and completed.
    """

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("in_progress", "In Progress"),
        ("submitted", "Submitted"),
        ("graded", "Graded"),
        ("passed", "Passed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    student = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="student_assessments"
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="student_enrollments"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="scheduled"
    )

    # Scheduling
    scheduled_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When student is scheduled to take exam"
    )

    # Attempt tracking
    last_attempted_at = models.DateTimeField(
        null=True,
        blank=True
    )

    attempt_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times student has attempted this exam"
    )

    max_attempts = models.PositiveIntegerField(
        default=3,
        help_text="Maximum allowed attempts"
    )

    # Score tracking
    best_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Highest score achieved"
    )

    class Meta:
        db_table = "student_assessments"
        ordering = ["-scheduled_date"]
        indexes = [
            models.Index(fields=["student", "assessment"]),
            models.Index(fields=["student", "status"]),
            models.Index(fields=["assessment", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "assessment"],
                name="unique_student_per_assessment"
            ),
        ]

    def __str__(self):
        return f"{self.student} → {self.assessment.name}"

    def can_attempt(self):
        """Check if student can attempt exam now"""
        if self.status == "cancelled":
            return False
        if self.attempt_count >= self.max_attempts:
            return False
        return True


# =====================================================
# AssessmentAttempt Model (Exam Session)
# =====================================================

class AssessmentAttempt(TenantAwareModel):
    """
    Individual exam session/attempt.
    Tracks start time, end time, and all answers provided.
    """

    STATUS_CHOICES = [
        ("started", "Started"),
        ("submitted", "Submitted"),
        ("graded", "Graded"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    student_assessment = models.ForeignKey(
        StudentAssessment,
        on_delete=models.CASCADE,
        related_name="attempts"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="started"
    )

    # Timing
    started_at = models.DateTimeField(
        auto_now_add=True
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When student submitted exam"
    )

    time_spent_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Total time spent (seconds)"
    )

    # Questions for this attempt
    questions = models.ManyToManyField(
        Question,
        through="AttemptAnswer",
        related_name="attempts"
    )

    class Meta:
        db_table = "assessment_attempts"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["student_assessment", "status"]),
        ]

    def __str__(self):
        return f"Attempt on {self.student_assessment.assessment.name} ({self.started_at})"

    def submit(self):
        """Mark attempt as submitted"""
        if self.status != "started":
            raise ValidationError("Can only submit attempts that are in progress")

        self.submitted_at = timezone.now()
        self.time_spent_seconds = int(
            (self.submitted_at - self.started_at).total_seconds()
        )
        self.status = "submitted"
        self.save()


# =====================================================
# AttemptAnswer Model (Individual Answer)
# =====================================================

class AttemptAnswer(TenantAwareModel):
    """
    Student's answer to a single question in an attempt.
    Tracks which option they selected and whether it's correct.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    attempt = models.ForeignKey(
        AssessmentAttempt,
        on_delete=models.CASCADE,
        related_name="answers"
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="attempt_answers"
    )

    selected_option = models.ForeignKey(
        QuestionOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attempt_answers",
        help_text="The option the student selected"
    )

    is_correct = models.BooleanField(
        default=False,
        help_text="Is this answer correct?"
    )

    points_earned = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Points awarded for this answer"
    )

    answered_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = "attempt_answers"
        ordering = ["question__display_order"]
        indexes = [
            models.Index(fields=["attempt", "question"]),
            models.Index(fields=["attempt", "is_correct"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"],
                name="unique_answer_per_question_per_attempt"
            ),
        ]

    def __str__(self):
        return f"Q{self.question.display_order}: {self.question.text[:30]}... → {'✓' if self.is_correct else '✗'}"


# =====================================================
# AssessmentScore Model (Results)
# =====================================================

class AssessmentScore(TenantAwareModel):
    """
    Final score and results for a student assessment.
    Includes pass/fail status, percentage, and topic breakdown.
    """

    STATUS_CHOICES = [
        ("passed", "Passed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    student_assessment = models.OneToOneField(
        StudentAssessment,
        on_delete=models.CASCADE,
        related_name="score"
    )

    attempt = models.OneToOneField(
        AssessmentAttempt,
        on_delete=models.CASCADE,
        related_name="score"
    )

    # Total scoring
    total_questions = models.PositiveIntegerField(
        default=0
    )

    correct_answers = models.PositiveIntegerField(
        default=0
    )

    total_points = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0
    )

    max_points = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=100
    )

    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Score as percentage (0-100)"
    )

    # Pass/fail
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="failed"
    )

    is_passed = models.BooleanField(
        default=False,
        help_text="Did student pass?"
    )

    # Topic breakdown (JSON)
    breakdown_by_topic = models.JSONField(
        default=dict,
        blank=True,
        help_text="Score breakdown by topic: {'Asanas': {'correct': 8, 'total': 10}, ...}"
    )

    # Certificate
    certificate_generated = models.BooleanField(
        default=False
    )

    certificate_generated_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        db_table = "assessment_scores"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student_assessment", "is_passed"]),
            models.Index(fields=["attempt"]),
        ]

    def __str__(self):
        return f"{self.student_assessment.student} - {self.percentage}% ({'PASS' if self.is_passed else 'FAIL'})"


# =====================================================
# CertificateTemplate Model (Customization)
# =====================================================

class CertificateTemplate(TenantAwareModel):
    """
    Customizable certificate template for assessments.

    Supports:
    - Per-assessment customization (assessment-specific templates)
    - Tenant-wide defaults (assessment=null)
    - Logo, custom colors, fonts, and text
    - Automatic fallback to hardcoded default if no template exists

    Examples:
    - "Yoga Fundamentals Certificate" (assessment=Yoga101)
    - "Studio Default Certificate" (assessment=null, for all assessments)
    """

    FONT_CHOICES = [
        ("Georgia", "Georgia (Serif)"),
        ("Arial", "Arial (Sans-serif)"),
        ("Times New Roman", "Times New Roman (Serif)"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(
        max_length=255,
        help_text="E.g., 'Yoga Fundamentals Certificate', 'Studio Default'"
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="certificate_templates",
        help_text="If set, this template applies to this specific assessment. If null, this is tenant default."
    )

    # Content customization
    certificate_title = models.CharField(
        max_length=255,
        default="Certificate of Completion",
        help_text="Main title on certificate (e.g., 'Certificate of Completion')"
    )

    certificate_subtitle = models.CharField(
        max_length=255,
        default="Setu Yoga Studio",
        help_text="Subtitle/organization name (e.g., 'Setu Yoga Studio')"
    )

    footer_text = models.TextField(
        blank=True,
        help_text="Optional custom footer text"
    )

    authorized_by = models.CharField(
        max_length=255,
        default="Studio Director",
        help_text="Signature/authorization line (e.g., 'Studio Director', 'Certified Instructor')"
    )

    # Styling customization
    border_color = models.CharField(
        max_length=7,
        default="#8B4513",
        help_text="Hex color for certificate border (e.g., #8B4513)"
    )

    title_color = models.CharField(
        max_length=7,
        default="#8B4513",
        help_text="Hex color for certificate title (e.g., #8B4513)"
    )

    text_color = models.CharField(
        max_length=7,
        default="#333",
        help_text="Hex color for body text (e.g., #333)"
    )

    font_family = models.CharField(
        max_length=50,
        choices=FONT_CHOICES,
        default="Georgia",
        help_text="Font family for certificate"
    )

    # Logo
    logo = models.ImageField(
        upload_to="certificate_logos/%Y/%m/",
        null=True,
        blank=True,
        help_text="Optional logo/image to display on certificate"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Is this template active and available for use?"
    )

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_certificate_templates"
    )

    class Meta:
        db_table = "certificate_templates"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "assessment"]),
            models.Index(fields=["tenant", "is_active"]),
        ]
        constraints = [
            # Only one active template per assessment per tenant
            models.UniqueConstraint(
                fields=["tenant", "assessment", "is_active"],
                condition=models.Q(is_active=True),
                name="unique_active_template_per_assessment"
            ),
        ]

    def __str__(self):
        assessment_name = f" ({self.assessment.name})" if self.assessment else " (Tenant Default)"
        return f"{self.name}{assessment_name}"

    def clean(self):
        """Validate hex colors"""
        import re
        hex_color_pattern = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$'

        for field in ["border_color", "title_color", "text_color"]:
            value = getattr(self, field)
            if not re.match(hex_color_pattern, value):
                raise ValidationError({
                    field: f"Invalid hex color format. Expected #RRGGBB or #RGB, got {value}"
                })


# =====================================================
# Signals
# =====================================================

def create_signals():
    """
    Create default signal handlers.
    See signals.py for implementations.
    """
    pass
