"""
Assessment Module Signals
==========================

Signal handlers for automated actions in assessment system.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.assessments.models import AssessmentAttempt, AssessmentScore
from apps.assessments.services.grading_service import GradingService
from apps.assessments.services.certificate_service import CertificateService
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=AssessmentAttempt)
def auto_grade_submitted_attempt(sender, instance, created, **kwargs):
    """
    Automatically grade exam when submitted.

    Triggered when AssessmentAttempt is marked as 'submitted'.
    """
    if not created and instance.status == "submitted":
        try:
            # Check if score already exists
            if hasattr(instance, 'score'):
                return

            tenant = instance.student_assessment.assessment.tenant
            service = GradingService(tenant)
            score = service.grade_attempt(instance)

            logger.info(
                f"Auto-graded exam for {instance.student_assessment.student} "
                f"- Score: {score.percentage:.2f}%"
            )

        except Exception as e:
            logger.error(f"Failed to auto-grade attempt {instance.id}: {str(e)}")


@receiver(post_save, sender=AssessmentScore)
def auto_generate_certificate(sender, instance, created, **kwargs):
    """
    Automatically generate certificate on passing score.

    Triggered when AssessmentScore is created with is_passed=True.
    """
    if created and instance.is_passed and not instance.certificate_generated:
        try:
            tenant = instance.student_assessment.assessment.tenant
            cert_service = CertificateService(tenant)

            # Generate certificate
            cert_data = cert_service.generate_certificate(instance)

            # Send email (optional, handled asynchronously in production)
            try:
                cert_service.send_certificate_email(instance)
                logger.info(
                    f"Certificate generated and emailed for "
                    f"{instance.student_assessment.student}"
                )
            except Exception as e:
                logger.warning(f"Failed to email certificate: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to generate certificate for score {instance.id}: {str(e)}")
