"""
CertificateService: Generate and email certificates on exam pass.

Supports:
- Custom certificate templates per assessment
- Tenant-wide default templates
- Custom logos, colors, fonts, and text
- Fallback to hardcoded default if no template exists
"""

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
import logging
import base64
from io import BytesIO

logger = logging.getLogger(__name__)


class CertificateService:
    """
    Service for generating certificates after passing exam.

    Features:
    - Load assessment-specific or tenant-default certificate templates
    - Render certificates with custom colors, fonts, logos, and text
    - Email certificates to students
    - Revoke certificates if needed
    """

    def __init__(self, tenant):
        """
        Initialize with tenant for isolation.

        Args:
            tenant: Tenant instance for multi-tenant isolation
        """
        self.tenant = tenant

    def generate_certificate(self, score):
        """
        Generate certificate for passing score.

        Args:
            score: AssessmentScore (must have is_passed=True)

        Returns:
            Dict with certificate info or raises ValidationError

        Raises:
            ValidationError: If not a passing score or already generated
        """
        if score.tenant != self.tenant:
            raise ValidationError("Score does not belong to your tenant")

        if not score.is_passed:
            raise ValidationError("Cannot generate certificate for failed attempts")

        if score.certificate_generated:
            raise ValidationError("Certificate already generated for this score")

        # Create certificate (would integrate with Document model in real impl)
        certificate_data = {
            "student_name": str(score.student_assessment.student),
            "assessment_name": score.student_assessment.assessment.name,
            "percentage": float(score.percentage),
            "generated_date": timezone.now().strftime("%Y-%m-%d"),
            "certificate_number": self._generate_certificate_number(score),
        }

        # Mark as generated
        score.certificate_generated = True
        score.certificate_generated_at = timezone.now()
        score.save()

        return certificate_data

    def _generate_certificate_number(self, score):
        """
        Generate unique certificate number.

        Format: CERT-{TENANT}-{STUDENT_ID}-{DATE}-{SEQUENCE}
        """
        from datetime import datetime

        date_part = datetime.now().strftime("%Y%m%d")
        tenant_short = str(score.tenant.id)[:8].upper()
        student_short = str(score.student_assessment.student.id)[:8].upper()

        return f"CERT-{tenant_short}-{student_short}-{date_part}"

    def get_template_for_assessment(self, assessment):
        """
        Get active certificate template for assessment.

        Resolution order:
        1. Assessment-specific active template
        2. Tenant default active template (assessment=null)
        3. None (will use hardcoded default)

        Args:
            assessment: Assessment instance

        Returns:
            CertificateTemplate or None
        """
        from apps.assessments.models import CertificateTemplate

        # Try assessment-specific template first
        template = CertificateTemplate.objects.filter(
            tenant=self.tenant,
            assessment=assessment,
            is_active=True
        ).first()

        if template:
            return template

        # Fall back to tenant default
        template = CertificateTemplate.objects.filter(
            tenant=self.tenant,
            assessment__isnull=True,
            is_active=True
        ).first()

        return template

    def _get_logo_data_uri(self, logo_field):
        """
        Convert logo image to data URI for embedding in email.

        Args:
            logo_field: ImageField instance

        Returns:
            Data URI string or empty string if no logo
        """
        if not logo_field:
            return ""

        try:
            # Read image file
            logo_field.open("rb")
            image_data = logo_field.read()
            logo_field.close()

            # Determine MIME type
            filename = logo_field.name.lower()
            if filename.endswith(".png"):
                mime_type = "image/png"
            elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
                mime_type = "image/jpeg"
            elif filename.endswith(".gif"):
                mime_type = "image/gif"
            else:
                mime_type = "image/jpeg"

            # Encode to base64
            encoded = base64.b64encode(image_data).decode("utf-8")
            return f"data:{mime_type};base64,{encoded}"

        except Exception as e:
            logger.warning(f"Failed to convert logo to data URI: {str(e)}")
            return ""

    def send_certificate_email(self, score, recipient_email=None):
        """
        Email certificate to student.

        Args:
            score: AssessmentScore
            recipient_email: Email to send to (default: student email)

        Returns:
            True if sent successfully, False otherwise

        Raises:
            ValidationError: If certificate not generated
        """
        if score.tenant != self.tenant:
            raise ValidationError("Score does not belong to your tenant")

        if not score.certificate_generated:
            raise ValidationError("Certificate not yet generated")

        student = score.student_assessment.student
        if not recipient_email:
            recipient_email = student.email

        if not recipient_email:
            raise ValidationError(f"Student {student} has no email address")

        try:
            # Get template for this assessment
            assessment = score.student_assessment.assessment
            template = self.get_template_for_assessment(assessment)

            # Prepare email
            subject = f"Certificate of Completion - {assessment.name}"

            # Build context with template data
            context = {
                "student_name": str(student),
                "assessment_name": assessment.name,
                "percentage": score.percentage,
                "passing_score": assessment.passing_score,
                "certificate_number": self._generate_certificate_number(score),
                "issued_date": score.certificate_generated_at.strftime("%B %d, %Y"),
            }

            # Render certificate with template
            html_message = self._render_certificate_with_template(context, template)

            # Send email
            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email="noreply@setuyogastudio.com",
                to=[recipient_email],
            )
            email.content_subtype = "html"

            email.send()

            logger.info(
                f"Certificate email sent to {recipient_email} "
                f"for {student} - {assessment.name}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to send certificate email: {str(e)}")
            return False

    def _render_certificate_with_template(self, context, template=None):
        """
        Render certificate HTML with custom template styling.

        If template is None, uses hardcoded defaults.

        Args:
            context: Dict with certificate data
            template: CertificateTemplate instance or None

        Returns:
            HTML string
        """
        # Get template values or use defaults
        if template:
            title = template.certificate_title
            subtitle = template.certificate_subtitle
            footer_text = template.footer_text
            authorized_by = template.authorized_by
            border_color = template.border_color
            title_color = template.title_color
            text_color = template.text_color
            font_family = template.font_family
            logo_data_uri = self._get_logo_data_uri(template.logo)
        else:
            # Hardcoded defaults
            title = "Certificate of Completion"
            subtitle = "Setu Yoga Studio"
            footer_text = ""
            authorized_by = "Studio Director"
            border_color = "#8B4513"
            title_color = "#8B4513"
            text_color = "#333"
            font_family = "Georgia"
            logo_data_uri = ""

        # Build logo HTML if present
        logo_html = ""
        if logo_data_uri:
            logo_html = f'<img src="{logo_data_uri}" alt="Logo" style="max-width: 150px; height: auto; margin-bottom: 20px;">'

        # Build footer HTML if present
        footer_html = ""
        if footer_text:
            footer_html = f'<div class="footer">{footer_text}</div>'

        html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: '{font_family}', serif;
                    text-align: center;
                    padding: 40px;
                    margin: 0;
                }}
                .certificate {{
                    border: 3px solid {border_color};
                    padding: 50px 40px;
                    max-width: 900px;
                    margin: 0 auto;
                    background-color: #fafaf8;
                }}
                .logo {{
                    text-align: center;
                    margin-bottom: 20px;
                }}
                .logo img {{
                    max-width: 150px;
                    height: auto;
                }}
                .title {{
                    font-size: 36px;
                    color: {title_color};
                    margin-bottom: 10px;
                    font-weight: bold;
                }}
                .subtitle {{
                    font-size: 18px;
                    color: {text_color};
                    margin-bottom: 40px;
                }}
                .intro {{
                    font-size: 14px;
                    color: {text_color};
                    margin: 20px 0;
                }}
                .name {{
                    font-size: 28px;
                    font-weight: bold;
                    color: {title_color};
                    margin: 25px 0;
                    border-bottom: 2px solid {border_color};
                    padding-bottom: 10px;
                }}
                .assessment-name {{
                    font-size: 24px;
                    font-weight: bold;
                    color: {title_color};
                    margin: 20px 0;
                }}
                .details {{
                    margin: 40px 0;
                    font-size: 14px;
                    color: {text_color};
                }}
                .details p {{
                    margin: 8px 0;
                }}
                .signature {{
                    margin-top: 50px;
                    padding-top: 30px;
                    border-top: 2px solid {border_color};
                }}
                .signature-line {{
                    margin-top: 30px;
                    font-size: 12px;
                    color: {text_color};
                }}
                .authorized {{
                    font-weight: bold;
                    color: {title_color};
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid {border_color};
                    font-size: 12px;
                    color: {text_color};
                    font-style: italic;
                }}
                .number {{
                    margin-top: 20px;
                    font-size: 11px;
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="certificate">
                {f'<div class="logo">{logo_html}</div>' if logo_data_uri else ''}
                <div class="title">{title}</div>
                <div class="subtitle">{subtitle}</div>

                <p class="intro">This certifies that</p>
                <div class="name">{context['student_name']}</div>
                <p class="intro">has successfully completed the assessment</p>
                <div class="assessment-name">{context['assessment_name']}</div>

                <div class="details">
                    <p><strong>Score:</strong> {context['percentage']:.2f}%</p>
                    <p><strong>Passing Score:</strong> {context['passing_score']:.2f}%</p>
                    <p><strong>Date Issued:</strong> {context['issued_date']}</p>
                </div>

                <div class="signature">
                    <div style="margin: 40px 0;">_____________________</div>
                    <div class="signature-line">
                        <span class="authorized">{authorized_by}</span>
                    </div>
                </div>

                {footer_html}

                <div class="number">
                    Certificate #: {context['certificate_number']}
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _render_certificate_template(self, context):
        """
        Render certificate HTML template (legacy method for backward compatibility).

        Delegates to _render_certificate_with_template with no custom template.
        """
        return self._render_certificate_with_template(context, template=None)

    def revoke_certificate(self, score):
        """
        Revoke a previously issued certificate.

        Args:
            score: AssessmentScore

        Returns:
            Updated AssessmentScore
        """
        if score.tenant != self.tenant:
            raise ValidationError("Score does not belong to your tenant")

        score.certificate_generated = False
        score.certificate_generated_at = None
        score.save()

        logger.info(
            f"Certificate revoked for {score.student_assessment.student} "
            f"- {score.student_assessment.assessment.name}"
        )

        return score
