"""
Assessment Module ViewSets
============================

API endpoints for managing assessments, questions, and student exams.

All ViewSets enforce:
1. Tenant isolation (users only see their tenant's data)
2. Role-based permissions (admin vs student)
3. Automatic tenant assignment
"""

from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError

from apps.assessments.models import (
    Assessment,
    Question,
    StudentAssessment,
    AssessmentAttempt,
    AssessmentScore,
)
from apps.assessments.serializers import (
    AssessmentSerializer,
    QuestionSerializer,
    StudentAssessmentSerializer,
    AssessmentAttemptSerializer,
    AssessmentScoreSerializer,
)
from apps.assessments.services.assessment_service import AssessmentService
from apps.assessments.services.question_service import QuestionService
from apps.assessments.services.attempt_service import AttemptService
from apps.assessments.services.grading_service import GradingService


# =====================================================
# Assessment ViewSet (CRUD for exams)
# =====================================================

class AssessmentViewSet(ModelViewSet):
    """
    CRUD operations for assessments (exam templates).

    Endpoints:
    - GET /api/assessments/ - List exams
    - POST /api/assessments/ - Create exam
    - GET /api/assessments/{id}/ - Get exam details
    - PUT /api/assessments/{id}/ - Update exam
    - DELETE /api/assessments/{id}/ - Delete exam
    - POST /api/assessments/{id}/publish/ - Publish exam
    - POST /api/assessments/{id}/add_questions/ - Add questions
    """

    serializer_class = AssessmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Return assessments for current user's tenant.

        ✅ GOTCHA #1: Always filter by tenant
        ✅ GOTCHA #10: Use select_related to avoid N+1 queries
        """
        user = self.request.user
        queryset = Assessment.base_objects.select_related("tenant")

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)

    def perform_create(self, serializer):
        """
        Auto-assign tenant from request context.

        ✅ GOTCHA #2: Always set tenant in create
        """
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def publish(self, request, pk=None):
        """
        Publish assessment so students can enroll.

        POST /api/assessments/{id}/publish/
        """
        assessment = self.get_object()

        try:
            service = AssessmentService(request.user.tenant)
            published = service.publish_assessment(assessment)

            serializer = self.get_serializer(published)
            return Response(
                {
                    "message": "Assessment published successfully",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def add_questions(self, request, pk=None):
        """
        Add existing questions to assessment.

        POST /api/assessments/{id}/add_questions/
        Body: {"question_ids": ["uuid1", "uuid2", ...]}
        """
        assessment = self.get_object()
        question_ids = request.data.get("question_ids", [])

        try:
            service = AssessmentService(request.user.tenant)
            questions = service.add_questions_to_assessment(
                assessment,
                question_ids
            )

            return Response(
                {
                    "message": f"Added {len(questions)} questions",
                    "count": len(questions)
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# =====================================================
# Question ViewSet (CRUD for questions)
# =====================================================

class QuestionViewSet(ModelViewSet):
    """
    CRUD operations for questions.

    Endpoints:
    - GET /api/questions/ - List questions
    - POST /api/questions/ - Create question
    - GET /api/questions/{id}/ - Get question details
    - PUT /api/questions/{id}/ - Update question
    - DELETE /api/questions/{id}/ - Delete question
    - POST /api/questions/{id}/publish/ - Publish question
    - POST /api/questions/bulk_import/ - Import from CSV
    """

    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return questions for current user's tenant."""
        user = self.request.user
        queryset = Question.base_objects.select_related(
            "tenant",
            "assessment",
            "created_by"
        ).prefetch_related("options")

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)

    def perform_create(self, serializer):
        """Auto-assign tenant from request context."""
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def publish(self, request, pk=None):
        """
        Publish question so it can be used in exams.

        POST /api/questions/{id}/publish/
        """
        question = self.get_object()

        try:
            service = QuestionService(request.user.tenant)
            published = service.publish_question(question)

            serializer = self.get_serializer(published)
            return Response(
                {
                    "message": "Question published successfully",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def bulk_import(self, request):
        """
        Bulk import questions from CSV.

        POST /api/questions/bulk_import/
        Body: {
            "assessment_id": "uuid",
            "csv_content": "Question,Difficulty,..."
        }
        """
        assessment_id = request.data.get("assessment_id")
        csv_content = request.data.get("csv_content", "")

        if not assessment_id:
            return Response(
                {"error": "assessment_id required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            assessment = Assessment.objects.get(
                tenant=request.user.tenant,
                id=assessment_id
            )
        except Assessment.DoesNotExist:
            return Response(
                {"error": "Assessment not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            service = QuestionService(request.user.tenant)
            questions = service.bulk_import_questions(
                assessment=assessment,
                csv_file_content=csv_content,
                created_by=request.user
            )

            return Response(
                {
                    "message": f"Imported {len(questions)} questions",
                    "count": len(questions)
                },
                status=status.HTTP_201_CREATED
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# =====================================================
# StudentAssessment ViewSet (Enrollment)
# =====================================================

class StudentAssessmentViewSet(ModelViewSet):
    """
    Student assessment enrollment and starting exams.

    Endpoints:
    - GET /api/student-assessments/ - List enrollments
    - POST /api/student-assessments/ - Enroll student
    - GET /api/student-assessments/{id}/ - Get enrollment
    - POST /api/student-assessments/{id}/start_exam/ - Start exam
    """

    serializer_class = StudentAssessmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return enrollments for current user's tenant."""
        user = self.request.user
        queryset = StudentAssessment.base_objects.select_related(
            "tenant",
            "student",
            "assessment"
        )

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)

    def perform_create(self, serializer):
        """Auto-assign tenant."""
        serializer.save(tenant=self.request.user.tenant)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def start_exam(self, request, pk=None):
        """
        Start a new exam attempt.

        POST /api/student-assessments/{id}/start_exam/
        """
        enrollment = self.get_object()

        try:
            service = AttemptService(request.user.tenant)
            attempt = service.start_attempt(enrollment)

            serializer = AssessmentAttemptSerializer(attempt)
            return Response(
                {
                    "message": "Exam started",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# =====================================================
# AssessmentAttempt ViewSet (Exam taking)
# =====================================================

class AssessmentAttemptViewSet(ModelViewSet):
    """
    Exam attempts and answer recording.

    Endpoints:
    - GET /api/attempts/ - List attempts
    - GET /api/attempts/{id}/ - Get attempt details
    - POST /api/attempts/{id}/submit_answer/ - Save answer
    - POST /api/attempts/{id}/submit_exam/ - Submit exam
    """

    serializer_class = AssessmentAttemptSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]  # No PUT/DELETE

    def get_queryset(self):
        """Return attempts for current user's tenant."""
        user = self.request.user
        queryset = AssessmentAttempt.base_objects.select_related(
            "tenant",
            "student_assessment",
            "student_assessment__student",
            "student_assessment__assessment"
        ).prefetch_related("answers")

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def submit_answer(self, request, pk=None):
        """
        Save a student's answer to a question.

        POST /api/attempts/{id}/submit_answer/
        Body: {
            "question_id": "uuid",
            "selected_option_id": "uuid"
        }
        """
        attempt = self.get_object()
        question_id = request.data.get("question_id")
        selected_option_id = request.data.get("selected_option_id")

        if not question_id or not selected_option_id:
            return Response(
                {"error": "question_id and selected_option_id required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = AttemptService(request.user.tenant)
            answer = service.save_answer(
                attempt,
                question_id,
                selected_option_id
            )

            serializer = AssessmentAttemptSerializer(attempt)
            return Response(
                {
                    "message": "Answer saved",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def submit_exam(self, request, pk=None):
        """
        Submit exam and trigger automatic grading.

        POST /api/attempts/{id}/submit_exam/
        """
        attempt = self.get_object()

        try:
            service = AttemptService(request.user.tenant)
            submitted_attempt = service.submit_exam(attempt)

            # Trigger grading
            grading_service = GradingService(request.user.tenant)
            score = grading_service.grade_attempt(submitted_attempt)

            score_serializer = AssessmentScoreSerializer(score)
            return Response(
                {
                    "message": "Exam submitted and graded",
                    "data": score_serializer.data
                },
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# =====================================================
# AssessmentScore ViewSet (Results)
# =====================================================

class AssessmentScoreViewSet(ModelViewSet):
    """
    Exam results and scores.

    Endpoints:
    - GET /api/scores/ - List scores
    - GET /api/scores/{id}/ - Get score details
    """

    serializer_class = AssessmentScoreSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]  # Read-only

    def get_queryset(self):
        """Return scores for current user's tenant."""
        user = self.request.user
        queryset = AssessmentScore.base_objects.select_related(
            "tenant",
            "student_assessment",
            "attempt"
        )

        if user.is_platform_admin:
            return queryset

        return queryset.filter(tenant=user.tenant)
