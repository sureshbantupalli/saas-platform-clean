"""
Assessment Module URLs
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.assessments.views import (
    AssessmentViewSet,
    QuestionViewSet,
    StudentAssessmentViewSet,
    AssessmentAttemptViewSet,
    AssessmentScoreViewSet,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r"assessments", AssessmentViewSet, basename="assessment")
router.register(r"questions", QuestionViewSet, basename="question")
router.register(r"student-assessments", StudentAssessmentViewSet, basename="student-assessment")
router.register(r"attempts", AssessmentAttemptViewSet, basename="attempt")
router.register(r"scores", AssessmentScoreViewSet, basename="score")

# Prefix for include() in main urls.py
app_name = "assessments"

urlpatterns = [
    # All routes defined by router
]

# Include router URLs
urlpatterns += router.urls
