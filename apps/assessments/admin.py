"""
Assessment Module Django Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.assessments.models import (
    Assessment,
    Question,
    QuestionOption,
    StudentAssessment,
    AssessmentAttempt,
    AttemptAnswer,
    AssessmentScore,
    CertificateTemplate,
)


# =====================================================
# Inline Admin Classes
# =====================================================

class QuestionOptionInline(admin.TabularInline):
    """Inline options for questions"""
    model = QuestionOption
    extra = 4
    fields = ["text", "is_correct", "display_order"]


class QuestionInline(admin.TabularInline):
    """Inline questions for assessments"""
    model = Question
    extra = 0
    fields = ["text", "difficulty", "status"]
    show_change_link = True


class AttemptAnswerInline(admin.TabularInline):
    """Inline answers for attempts"""
    model = AttemptAnswer
    extra = 0
    fields = ["question", "selected_option", "is_correct", "points_earned"]
    readonly_fields = ["is_correct", "points_earned"]


# =====================================================
# Assessment Admin
# =====================================================

@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    """Exam template administration"""

    list_display = [
        "name",
        "tenant",
        "status_badge",
        "question_count",
        "total_questions",
        "duration_minutes",
        "passing_score",
        "created_at",
    ]
    list_filter = [
        "tenant",
        "status",
        "is_active",
        "created_at",
    ]
    search_fields = [
        "name",
        "description",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "question_count",
    ]
    fieldsets = (
        ("Basic Info", {
            "fields": ["id", "tenant", "name", "description"]
        }),
        ("Exam Structure", {
            "fields": [
                "total_questions",
                "duration_minutes",
                "question_count",
            ]
        }),
        ("Difficulty Distribution", {
            "fields": [
                "easy_percentage",
                "medium_percentage",
                "hard_percentage",
            ]
        }),
        ("Passing Criteria", {
            "fields": ["passing_score"]
        }),
        ("Status", {
            "fields": [
                "status",
                "is_active",
                "created_by",
            ]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    )
    inlines = [QuestionInline]
    actions = ["publish_assessment"]

    def status_badge(self, obj):
        """Display status as colored badge"""
        color_map = {
            "draft": "#FFA500",
            "published": "#00AA00",
            "archived": "#CCCCCC",
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color_map.get(obj.status, "#999"),
            obj.get_status_display()
        )
    status_badge.short_description = "Status"

    def question_count(self, obj):
        """Show published questions"""
        return f"{obj.question_count}/{obj.total_questions}"
    question_count.short_description = "Questions"

    def publish_assessment(self, request, queryset):
        """Action to publish assessments"""
        for assessment in queryset:
            try:
                assessment.publish()
                self.message_user(
                    request,
                    f"✓ Published: {assessment.name}"
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"✗ Failed {assessment.name}: {str(e)}",
                    level=40  # ERROR level
                )

    publish_assessment.short_description = "Publish selected assessments"


# =====================================================
# Question Admin
# =====================================================

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """Question administration"""

    list_display = [
        "text_preview",
        "assessment",
        "difficulty_badge",
        "topic",
        "status_badge",
        "option_count",
        "created_at",
    ]
    list_filter = [
        "assessment__tenant",
        "assessment",
        "difficulty",
        "status",
        "topic",
        "created_at",
    ]
    search_fields = [
        "text",
        "topic",
        "assessment__name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        ("Basic Info", {
            "fields": ["id", "assessment", "text", "topic"]
        }),
        ("Content", {
            "fields": [
                "difficulty",
                "explanation",
                "display_order",
            ]
        }),
        ("Status", {
            "fields": [
                "status",
                "created_by",
            ]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    )
    inlines = [QuestionOptionInline]

    def text_preview(self, obj):
        """Show preview of question text"""
        return obj.text[:60] + "..." if len(obj.text) > 60 else obj.text
    text_preview.short_description = "Question"

    def difficulty_badge(self, obj):
        """Display difficulty as badge"""
        color_map = {
            "easy": "#90EE90",
            "medium": "#FFD700",
            "hard": "#FF6B6B",
        }
        return format_html(
            '<span style="background-color: {}; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color_map.get(obj.difficulty, "#999"),
            obj.get_difficulty_display()
        )
    difficulty_badge.short_description = "Difficulty"

    def status_badge(self, obj):
        """Display status"""
        color_map = {
            "draft": "#FFA500",
            "published": "#00AA00",
            "archived": "#CCCCCC",
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color_map.get(obj.status, "#999"),
            obj.get_status_display()
        )
    status_badge.short_description = "Status"

    def option_count(self, obj):
        """Show number of options"""
        count = obj.options.count()
        return f"{count}/4"
    option_count.short_description = "Options"


# =====================================================
# StudentAssessment Admin
# =====================================================

@admin.register(StudentAssessment)
class StudentAssessmentAdmin(admin.ModelAdmin):
    """Student enrollment administration"""

    list_display = [
        "student",
        "assessment",
        "status_badge",
        "attempt_count",
        "best_score",
        "scheduled_date",
        "created_at",
    ]
    list_filter = [
        "tenant",
        "assessment",
        "status",
        "scheduled_date",
        "created_at",
    ]
    search_fields = [
        "student__name",
        "assessment__name",
    ]
    readonly_fields = [
        "id",
        "attempt_count",
        "last_attempted_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        ("Basic Info", {
            "fields": [
                "id",
                "student",
                "assessment",
                "tenant",
            ]
        }),
        ("Scheduling", {
            "fields": ["scheduled_date"]
        }),
        ("Attempt Tracking", {
            "fields": [
                "status",
                "attempt_count",
                "max_attempts",
                "last_attempted_at",
                "best_score",
            ]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    )

    def status_badge(self, obj):
        """Display status as badge"""
        color_map = {
            "scheduled": "#4169E1",
            "in_progress": "#FFD700",
            "submitted": "#FFA500",
            "graded": "#87CEEB",
            "passed": "#00AA00",
            "failed": "#FF6B6B",
            "cancelled": "#CCCCCC",
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color_map.get(obj.status, "#999"),
            obj.get_status_display()
        )
    status_badge.short_description = "Status"


# =====================================================
# AssessmentScore Admin
# =====================================================

@admin.register(AssessmentScore)
class AssessmentScoreAdmin(admin.ModelAdmin):
    """Results and grading administration"""

    list_display = [
        "student",
        "assessment",
        "percentage_display",
        "is_passed_badge",
        "status_badge",
        "certificate_generated",
        "created_at",
    ]
    list_filter = [
        "tenant",
        "is_passed",
        "status",
        "certificate_generated",
        "created_at",
    ]
    search_fields = [
        "student_assessment__student__name",
        "student_assessment__assessment__name",
    ]
    readonly_fields = [
        "id",
        "total_questions",
        "correct_answers",
        "total_points",
        "max_points",
        "percentage",
        "status",
        "is_passed",
        "breakdown_display",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        ("Basic Info", {
            "fields": [
                "id",
                "student_assessment",
                "attempt",
                "tenant",
            ]
        }),
        ("Scoring", {
            "fields": [
                "total_questions",
                "correct_answers",
                "total_points",
                "max_points",
                "percentage",
                "status",
                "is_passed",
            ]
        }),
        ("Topic Breakdown", {
            "fields": ["breakdown_display"],
        }),
        ("Certificate", {
            "fields": [
                "certificate_generated",
                "certificate_generated_at",
            ]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    )

    def student(self, obj):
        return str(obj.student_assessment.student)
    student.short_description = "Student"

    def assessment(self, obj):
        return obj.student_assessment.assessment.name
    assessment.short_description = "Assessment"

    def percentage_display(self, obj):
        return f"{obj.percentage:.2f}%"
    percentage_display.short_description = "Score"

    def is_passed_badge(self, obj):
        """Display pass/fail as badge"""
        color = "#00AA00" if obj.is_passed else "#FF6B6B"
        text = "PASS" if obj.is_passed else "FAIL"
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            text
        )
    is_passed_badge.short_description = "Pass/Fail"

    def status_badge(self, obj):
        """Display status"""
        color_map = {
            "passed": "#00AA00",
            "failed": "#FF6B6B",
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color_map.get(obj.status, "#999"),
            obj.get_status_display()
        )
    status_badge.short_description = "Status"

    def breakdown_display(self, obj):
        """Display topic breakdown as HTML table"""
        if not obj.breakdown_by_topic:
            return "No breakdown data"

        html = '<table style="border-collapse: collapse; width: 100%;">'
        html += '<tr style="background-color: #f0f0f0;"><th style="border: 1px solid #ddd; padding: 8px;">Topic</th><th style="border: 1px solid #ddd; padding: 8px;">Correct</th><th style="border: 1px solid #ddd; padding: 8px;">Total</th><th style="border: 1px solid #ddd; padding: 8px;">%</th></tr>'

        for topic, data in obj.breakdown_by_topic.items():
            html += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">{topic}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;">{data.get("correct", 0)}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;">{data.get("total", 0)}</td>'
            html += f'<td style="border: 1px solid #ddd; padding: 8px;">{data.get("percentage", 0):.1f}%</td></tr>'

        html += '</table>'
        return format_html(html)
    breakdown_display.short_description = "Topic Breakdown"


# =====================================================
# Other Admins (Minimal)
# =====================================================

@admin.register(QuestionOption)
class QuestionOptionAdmin(admin.ModelAdmin):
    list_display = ["question", "text", "is_correct", "display_order"]
    list_filter = ["is_correct", "question__assessment"]


@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = ["student", "assessment", "status", "started_at", "submitted_at"]
    list_filter = ["status", "started_at"]
    search_fields = ["student_assessment__student__name"]

    def student(self, obj):
        return str(obj.student_assessment.student)

    def assessment(self, obj):
        return obj.student_assessment.assessment.name


@admin.register(AttemptAnswer)
class AttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ["attempt", "question", "is_correct", "points_earned"]
    list_filter = ["is_correct", "attempt__student_assessment__assessment"]
    search_fields = ["question__text"]
    inlines = []


# =====================================================
# CertificateTemplate Admin
# =====================================================

@admin.register(CertificateTemplate)
class CertificateTemplateAdmin(admin.ModelAdmin):
    """Certificate template customization administration"""

    list_display = [
        "name",
        "assessment_link",
        "tenant",
        "is_active_badge",
        "has_logo",
        "font_family",
        "created_at",
    ]
    list_filter = [
        "tenant",
        "is_active",
        "assessment",
        "font_family",
        "created_at",
    ]
    search_fields = [
        "name",
        "certificate_title",
        "certificate_subtitle",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "logo_preview",
    ]
    fieldsets = (
        ("Basic Info", {
            "fields": [
                "id",
                "tenant",
                "name",
                "assessment",
                "is_active",
                "created_by",
            ]
        }),
        ("Content", {
            "fields": [
                "certificate_title",
                "certificate_subtitle",
                "footer_text",
                "authorized_by",
            ],
            "description": "Customize the text content displayed on the certificate"
        }),
        ("Styling", {
            "fields": [
                "border_color",
                "title_color",
                "text_color",
                "font_family",
            ],
            "description": "Customize colors and typography"
        }),
        ("Logo", {
            "fields": [
                "logo",
                "logo_preview",
            ],
            "description": "Optional logo image to display on certificate"
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    )

    def assessment_link(self, obj):
        """Display assessment name or 'Tenant Default'"""
        if obj.assessment:
            return obj.assessment.name
        return "Tenant Default"
    assessment_link.short_description = "Assessment"

    def is_active_badge(self, obj):
        """Display active status as badge"""
        color = "#00AA00" if obj.is_active else "#CCCCCC"
        text = "Active" if obj.is_active else "Inactive"
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            text
        )
    is_active_badge.short_description = "Status"

    def has_logo(self, obj):
        """Display if logo is present"""
        if obj.logo:
            return format_html(
                '<span style="color: #00AA00;">✓ Has Logo</span>'
            )
        return format_html(
            '<span style="color: #999;">No Logo</span>'
        )
    has_logo.short_description = "Logo"

    def logo_preview(self, obj):
        """Display logo preview in admin"""
        if not obj.logo:
            return "No logo uploaded"

        try:
            return format_html(
                '<img src="{}" style="max-width: 300px; max-height: 300px; border: 1px solid #ddd; padding: 5px;">',
                obj.logo.url
            )
        except Exception as e:
            return f"Error loading preview: {str(e)}"
    logo_preview.short_description = "Logo Preview"
