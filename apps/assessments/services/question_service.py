"""
QuestionService: Manage question creation, options, and bulk import.
"""

import csv
from io import StringIO
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.assessments.models import Question, QuestionOption


class QuestionService:
    """
    Service for creating, publishing, and managing questions.
    """

    def __init__(self, tenant):
        """
        Initialize with tenant for isolation.
        """
        self.tenant = tenant

    def create_question(self, assessment, text, difficulty="medium",
                       topic="", explanation="", created_by=None):
        """
        Create a new question (without options yet).

        Args:
            assessment: Assessment this question belongs to
            text: Question text
            difficulty: 'easy', 'medium', or 'hard'
            topic: Topic/category
            explanation: Explanation shown after answering
            created_by: User who created

        Returns:
            Question instance

        Raises:
            ValidationError: If invalid parameters
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        if difficulty not in ["easy", "medium", "hard"]:
            raise ValidationError(f"Invalid difficulty: {difficulty}")

        question = Question.objects.create(
            tenant=self.tenant,
            assessment=assessment,
            text=text,
            difficulty=difficulty,
            topic=topic,
            explanation=explanation,
            created_by=created_by,
            status="draft"
        )

        return question

    def add_options(self, question, options_data):
        """
        Add multiple choice options to a question.

        Args:
            question: Question object
            options_data: List of dicts:
                [
                    {"text": "Option A", "is_correct": True},
                    {"text": "Option B", "is_correct": False},
                    ...
                ]

        Returns:
            List of created QuestionOption objects

        Raises:
            ValidationError: If wrong number of options or no correct answer
        """
        if question.tenant != self.tenant:
            raise ValidationError("Question does not belong to your tenant")

        if len(options_data) != 4:
            raise ValidationError(
                f"Must provide exactly 4 options (got {len(options_data)})"
            )

        # Verify exactly one correct answer
        correct_count = sum(1 for opt in options_data if opt.get("is_correct", False))
        if correct_count != 1:
            raise ValidationError(
                f"Must have exactly 1 correct answer (got {correct_count})"
            )

        # Create options in transaction
        with transaction.atomic():
            options = []
            for idx, opt_data in enumerate(options_data):
                option = QuestionOption.objects.create(
                    tenant=self.tenant,
                    question=question,
                    text=opt_data["text"],
                    is_correct=opt_data.get("is_correct", False),
                    display_order=idx
                )
                options.append(option)

        return options

    def publish_question(self, question):
        """
        Publish question so it can be used in exams.

        ✅ GOTCHA #6: Verify exactly 4 options with 1 correct answer
        """
        if question.tenant != self.tenant:
            raise ValidationError("Question does not belong to your tenant")

        question.publish()  # Raises ValidationError if not ready
        return question

    def bulk_import_questions(self, assessment, csv_file_content, created_by=None):
        """
        Bulk import questions from CSV.

        CSV Format:
        ```
        Question Text,Difficulty,Topic,Option 1,Option 2,Option 3,Option 4,Correct Option (1-4),Explanation
        "What is yoga?",easy,"Basics","Science","Practice","Philosophy","All above",4,"Yoga is all of these"
        ...
        ```

        Args:
            assessment: Assessment to add questions to
            csv_file_content: CSV file content (string)
            created_by: User importing

        Returns:
            List of created Question objects

        Raises:
            ValidationError: If CSV format invalid or import fails
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        questions = []

        try:
            reader = csv.DictReader(StringIO(csv_file_content))
            rows = list(reader)

            if not rows:
                raise ValidationError("CSV file is empty")

            with transaction.atomic():
                for idx, row in enumerate(rows):
                    try:
                        # Extract data
                        text = row.get("Question Text", "").strip()
                        difficulty = row.get("Difficulty", "medium").strip().lower()
                        topic = row.get("Topic", "").strip()
                        explanation = row.get("Explanation", "").strip()
                        correct_idx = int(row.get("Correct Option (1-4)", "1").strip()) - 1

                        # Validate
                        if not text:
                            raise ValidationError(f"Row {idx + 1}: Question text missing")

                        if difficulty not in ["easy", "medium", "hard"]:
                            raise ValidationError(
                                f"Row {idx + 1}: Invalid difficulty '{difficulty}'"
                            )

                        # Extract options
                        option_texts = [
                            row.get(f"Option {i}", "").strip()
                            for i in range(1, 5)
                        ]

                        if not all(option_texts):
                            raise ValidationError(
                                f"Row {idx + 1}: All 4 options required"
                            )

                        if correct_idx < 0 or correct_idx >= 4:
                            raise ValidationError(
                                f"Row {idx + 1}: Correct option must be 1-4"
                            )

                        # Create question
                        question = self.create_question(
                            assessment=assessment,
                            text=text,
                            difficulty=difficulty,
                            topic=topic,
                            explanation=explanation,
                            created_by=created_by
                        )

                        # Add options
                        options_data = [
                            {
                                "text": opt_text,
                                "is_correct": (i == correct_idx)
                            }
                            for i, opt_text in enumerate(option_texts)
                        ]

                        self.add_options(question, options_data)
                        questions.append(question)

                    except ValidationError:
                        raise
                    except Exception as e:
                        raise ValidationError(f"Row {idx + 1}: {str(e)}")

        except Exception as e:
            raise ValidationError(f"CSV import failed: {str(e)}")

        return questions

    def get_random_questions(self, assessment, count=None, by_difficulty=None):
        """
        Get random questions from assessment by difficulty.

        Args:
            assessment: Assessment
            count: Number of questions (default: assessment.total_questions)
            by_difficulty: Dict of difficulty counts:
                {"easy": 15, "medium": 20, "hard": 15}
                If not provided, uses assessment percentages

        Returns:
            QuerySet of random questions

        Raises:
            ValidationError: If not enough questions available
        """
        if assessment.tenant != self.tenant:
            raise ValidationError("Assessment does not belong to your tenant")

        if count is None:
            count = assessment.total_questions

        if by_difficulty is None:
            # Calculate from assessment percentages
            by_difficulty = {
                "easy": int(count * assessment.easy_percentage / 100),
                "medium": int(count * assessment.medium_percentage / 100),
                "hard": int(count * assessment.hard_percentage / 100),
            }

        # ✅ GOTCHA #10: Verify enough questions available (avoid N+1)
        available = {
            "easy": assessment.questions.filter(
                difficulty="easy",
                status="published"
            ).count(),
            "medium": assessment.questions.filter(
                difficulty="medium",
                status="published"
            ).count(),
            "hard": assessment.questions.filter(
                difficulty="hard",
                status="published"
            ).count(),
        }

        for difficulty, needed in by_difficulty.items():
            if needed > 0 and available[difficulty] < needed:
                raise ValidationError(
                    f"Not enough {difficulty} questions: "
                    f"need {needed}, have {available[difficulty]}"
                )

        # Fetch questions in single query (avoid N+1)
        questions = []
        for difficulty, count_for_difficulty in by_difficulty.items():
            if count_for_difficulty > 0:
                qs = assessment.questions.filter(
                    difficulty=difficulty,
                    status="published"
                ).order_by("?")[:count_for_difficulty]
                questions.extend(qs)

        return questions
