# Generated migration for Assessment module

import django.db.models.deletion
import uuid
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0006_alter_branch_managers'),
        ('members', '0004_alter_member_branches'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Assessment model
        migrations.CreateModel(
            name='Assessment',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text="E.g., 'Yoga Fundamentals Exam'", max_length=255)),
                ('description', models.TextField(blank=True, help_text='Detailed description of what this exam tests')),
                ('total_questions', models.PositiveIntegerField(default=50, help_text='Total number of questions in this exam')),
                ('duration_minutes', models.PositiveIntegerField(default=60, help_text='Time limit in minutes (5 min to 8 hours)')),
                ('passing_score', models.DecimalField(decimal_places=2, default=60, help_text='Minimum score (%) to pass (0-100)', max_digits=5)),
                ('easy_percentage', models.PositiveIntegerField(default=30, help_text='Percentage of easy questions (0-100)')),
                ('medium_percentage', models.PositiveIntegerField(default=40, help_text='Percentage of medium questions (0-100)')),
                ('hard_percentage', models.PositiveIntegerField(default=30, help_text='Percentage of hard questions (0-100)')),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')], default='draft', help_text='Draft = in development, Published = students can take', max_length=20)),
                ('is_active', models.BooleanField(default=True, help_text='Can students enroll in this assessment?')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_assessments', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'assessments',
                'ordering': ['-created_at'],
            },
        ),

        # Question model
        migrations.CreateModel(
            name='Question',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('text', models.TextField(help_text='The question text')),
                ('topic', models.CharField(blank=True, help_text="Topic this question covers (e.g., 'Pranayama', 'Asanas')", max_length=100)),
                ('difficulty', models.CharField(choices=[('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')], default='medium', max_length=20)),
                ('explanation', models.TextField(blank=True, help_text='Explanation shown after answering')),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')], default='draft', max_length=20)),
                ('display_order', models.PositiveIntegerField(default=0, help_text='Order to display questions (0 = random order)')),
                ('assessment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='assessments.Assessment')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_questions', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'questions',
                'ordering': ['display_order', 'created_at'],
            },
        ),

        # QuestionOption model
        migrations.CreateModel(
            name='QuestionOption',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('text', models.TextField(help_text='The option text')),
                ('is_correct', models.BooleanField(default=False, help_text='Is this the correct answer?')),
                ('display_order', models.PositiveIntegerField(default=0, help_text='Order to display options (0 = random)')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='options', to='assessments.Question')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'question_options',
                'ordering': ['display_order', 'created_at'],
            },
        ),

        # StudentAssessment model
        migrations.CreateModel(
            name='StudentAssessment',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('scheduled', 'Scheduled'), ('in_progress', 'In Progress'), ('submitted', 'Submitted'), ('graded', 'Graded'), ('passed', 'Passed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], default='scheduled', max_length=20)),
                ('scheduled_date', models.DateTimeField(blank=True, help_text='When student is scheduled to take exam', null=True)),
                ('last_attempted_at', models.DateTimeField(blank=True, null=True)),
                ('attempt_count', models.PositiveIntegerField(default=0, help_text='Number of times student has attempted this exam')),
                ('max_attempts', models.PositiveIntegerField(default=3, help_text='Maximum allowed attempts')),
                ('best_score', models.DecimalField(blank=True, decimal_places=2, help_text='Highest score achieved', max_digits=5, null=True)),
                ('assessment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_enrollments', to='assessments.Assessment')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_assessments', to='members.Member')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'student_assessments',
                'ordering': ['-scheduled_date'],
            },
        ),

        # AssessmentAttempt model
        migrations.CreateModel(
            name='AssessmentAttempt',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('started', 'Started'), ('submitted', 'Submitted'), ('graded', 'Graded'), ('cancelled', 'Cancelled')], default='started', max_length=20)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, help_text='When student submitted exam', null=True)),
                ('time_spent_seconds', models.PositiveIntegerField(default=0, help_text='Total time spent (seconds)')),
                ('student_assessment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='assessments.StudentAssessment')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'assessment_attempts',
                'ordering': ['-started_at'],
            },
        ),

        # AttemptAnswer model
        migrations.CreateModel(
            name='AttemptAnswer',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_correct', models.BooleanField(default=False, help_text='Is this answer correct?')),
                ('points_earned', models.DecimalField(decimal_places=2, default=0, help_text='Points awarded for this answer', max_digits=5)),
                ('answered_at', models.DateTimeField(auto_now_add=True)),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='assessments.AssessmentAttempt')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempt_answers', to='assessments.Question')),
                ('selected_option', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attempt_answers', to='assessments.QuestionOption')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'attempt_answers',
                'ordering': ["question__display_order"],
            },
        ),

        # AssessmentScore model
        migrations.CreateModel(
            name='AssessmentScore',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('total_questions', models.PositiveIntegerField(default=0)),
                ('correct_answers', models.PositiveIntegerField(default=0)),
                ('total_points', models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('max_points', models.DecimalField(decimal_places=2, default=100, max_digits=7)),
                ('percentage', models.DecimalField(decimal_places=2, default=0, max_digits=5, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ('status', models.CharField(choices=[('passed', 'Passed'), ('failed', 'Failed')], default='failed', max_length=20)),
                ('is_passed', models.BooleanField(default=False, help_text='Did student pass?')),
                ('breakdown_by_topic', models.JSONField(blank=True, default=dict, help_text="Score breakdown by topic: {'Asanas': {'correct': 8, 'total': 10}, ...}")),
                ('certificate_generated', models.BooleanField(default=False)),
                ('certificate_generated_at', models.DateTimeField(blank=True, null=True)),
                ('attempt', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='score', to='assessments.AssessmentAttempt')),
                ('student_assessment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='score', to='assessments.StudentAssessment')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'assessment_scores',
                'ordering': ['-created_at'],
            },
        ),

        
    ]
