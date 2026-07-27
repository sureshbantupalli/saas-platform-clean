# Certificate Customization System - Usage Guide

## Quick Start

### 1. Apply Migrations

```bash
# Apply database migration to create certificate_templates table
python manage.py migrate assessments

# Verify migration applied
python manage.py showmigrations assessments
```

### 2. Create a Default Tenant Template

Use the Django Admin interface:

1. Navigate to: `/admin/assessments/certificatetemplate/`
2. Click "Add Certificate Template"
3. Fill in the form:
   - **Name:** "Studio Default Certificate"
   - **Assessment:** Leave blank (null = tenant default)
   - **Certificate Title:** "Certificate of Completion"
   - **Certificate Subtitle:** "Setu Yoga Studio"
   - **Footer Text:** (Optional) "This certifies successful completion"
   - **Authorized By:** "Studio Director"
   - **Border Color:** `#8B4513` (brown)
   - **Title Color:** `#8B4513` (brown)
   - **Text Color:** `#333` (dark gray)
   - **Font Family:** Georgia
   - **Logo:** Upload studio logo (optional)
   - **Is Active:** Check this box

4. Click "Save"

### 3. Create Assessment-Specific Templates (Optional)

If you want different certificates for different assessments:

1. Click "Add Certificate Template" again
2. Fill in:
   - **Name:** "Yoga Fundamentals Certificate"
   - **Assessment:** Select "Yoga Fundamentals" assessment
   - Customize other fields as desired
   - **Is Active:** Check

3. Click "Save"

### 4. Test Certificate Generation

Use Django shell to test:

```python
python manage.py shell

# Import models
from apps.assessments.models import Assessment, AssessmentScore, CertificateTemplate
from apps.assessments.services.certificate_service import CertificateService
from apps.core.models import Tenant

# Get test data
tenant = Tenant.objects.get(subdomain="your-tenant")
assessment = Assessment.objects.get(name="Yoga Fundamentals")
score = AssessmentScore.objects.filter(
    is_passed=True,
    certificate_generated=False
).first()

# Create service
service = CertificateService(tenant=tenant)

# Check template
template = service.get_template_for_assessment(assessment)
print(f"Template: {template.name if template else 'Using defaults'}")

# Generate certificate
cert_data = service.generate_certificate(score)
print(f"Certificate generated: {cert_data}")

# Send email
success = service.send_certificate_email(score)
print(f"Email sent: {success}")
```

## Common Customization Tasks

### Change Certificate Colors

**In Admin Interface:**
1. Find template in Certificate Templates list
2. Click to edit
3. Update color fields:
   - **Border Color:** Border around certificate
   - **Title Color:** Certificate title and student name
   - **Text Color:** Regular body text
4. Save

**Color Suggestions:**
- Professional: `#000000` (black), `#333333` (dark gray)
- Elegant: `#8B4513` (brown), `#A0522D` (sienna)
- Premium: `#FFD700` (gold), `#D4AF37` (gold)
- Wellness: `#228B22` (forest green), `#2F5233` (dark green)
- Academic: `#003366` (navy), `#000080` (dark blue)

### Add Studio Logo

**In Admin Interface:**
1. Find template
2. Click to edit
3. Scroll to "Logo" section
4. Click "Choose File" and upload logo image
5. Logo preview displays when saved
6. Save

**Logo Requirements:**
- Format: PNG, JPG, or GIF
- Size: 150x150px or larger
- Background: Transparent PNG recommended
- Upload once, used for all certificates with this template

### Change Certificate Text

**In Admin Interface:**
1. Find template
2. Click to edit
3. Update "Content" fieldset:
   - **Certificate Title:** Main heading (e.g., "Certificate of Completion")
   - **Certificate Subtitle:** Org name (e.g., "Setu Yoga Studio")
   - **Footer Text:** Optional footer message
   - **Authorized By:** Signature line (e.g., "Studio Director")
4. Save

**Example Customizations:**

For yoga studio:
- Title: "Yoga Certification"
- Subtitle: "200-Hour Training Program"
- Authorized By: "Certified Yoga Instructor"
- Footer: "Completion of this program certifies proficiency in yoga instruction"

For wellness program:
- Title: "Certificate of Achievement"
- Subtitle: "Wellness & Mindfulness Program"
- Authorized By: "Program Director"
- Footer: "Demonstrates commitment to personal wellness development"

### Change Font

**In Admin Interface:**
1. Find template
2. Click to edit
3. In "Styling" section, find **Font Family**
4. Select from dropdown:
   - Georgia (Serif) - Elegant, traditional
   - Arial (Sans-serif) - Modern, clean
   - Times New Roman (Serif) - Formal, academic
5. Save

**Font Usage:**
- **Georgia** - Best for elegant/traditional certificates
- **Arial** - Best for modern/clean design
- **Times New Roman** - Best for academic/formal certificates

### Use Different Template Per Assessment

**Scenario:** Different certificates for different assessments

**Steps:**
1. Create assessment-specific template:
   - **Name:** "Yoga Fundamentals Cert"
   - **Assessment:** Select specific assessment
   - Customize colors, fonts, text
   - **Is Active:** Check
   - Save

2. Create another template:
   - **Name:** "Advanced Asanas Cert"
   - **Assessment:** Select different assessment
   - Different customization
   - **Is Active:** Check
   - Save

3. Template resolution is automatic:
   - Assessment-specific templates used if available
   - Falls back to tenant default if assessment template missing
   - Falls back to hardcoded defaults if no templates exist

### Deactivate a Template

**In Admin Interface:**
1. Find template
2. Click to edit
3. Uncheck **Is Active** checkbox
4. Save

**Effect:**
- Template no longer used for new certificates
- Resolution falls back to next template in chain
- Existing certificates remain valid

### Revoke Previously Issued Certificate

**Via Django Shell:**
```python
from apps.assessments.models import AssessmentScore
from apps.assessments.services.certificate_service import CertificateService

score = AssessmentScore.objects.get(id=score_id)
service = CertificateService(tenant=score.tenant)

# Revoke certificate
service.revoke_certificate(score)

# Certificate can now be regenerated
cert_data = service.generate_certificate(score)
service.send_certificate_email(score)
```

## Integration Examples

### Auto-Generate Certificates on Test Completion

**In signals.py or after score assignment:**

```python
from apps.assessments.services.certificate_service import CertificateService

def handle_assessment_completion(score):
    """Called after student completes assessment"""
    
    if score.is_passed:
        service = CertificateService(tenant=score.tenant)
        
        # Generate certificate
        try:
            cert_data = service.generate_certificate(score)
            
            # Send email
            service.send_certificate_email(score)
            
            return True
        except Exception as e:
            logger.error(f"Certificate generation failed: {str(e)}")
            return False
    
    return False
```

### Bulk Certificate Generation

**Generate certificates for all passing assessments:**

```python
from apps.assessments.models import AssessmentScore
from apps.assessments.services.certificate_service import CertificateService

def bulk_generate_certificates(tenant):
    """Generate certificates for all eligible scores"""
    
    scores = AssessmentScore.objects.filter(
        tenant=tenant,
        is_passed=True,
        certificate_generated=False
    )
    
    service = CertificateService(tenant=tenant)
    
    success_count = 0
    error_count = 0
    
    for score in scores:
        try:
            service.generate_certificate(score)
            service.send_certificate_email(score)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed for {score.student_assessment.student}: {str(e)}")
            error_count += 1
    
    return {
        "success": success_count,
        "errors": error_count,
        "total": success_count + error_count
    }

# Run it
result = bulk_generate_certificates(tenant)
print(f"Generated {result['success']}/{result['total']} certificates")
```

### View Certificates in Admin Dashboard

**In Certificate Templates Admin:**
- List shows all templates with status
- Filter by tenant, assessment, active status
- Search by name or title
- Logo indicator shows if image is present
- Click template to edit/preview

**In Assessment Admin:**
- See all certificate templates for that assessment
- View active template
- Jump to template admin

**In Assessment Score Admin:**
- See `certificate_generated` flag
- See `certificate_generated_at` timestamp
- Filter by certificate status

## Troubleshooting

### "Certificate Template Not Found" Error

**Cause:** No active template and no hardcoded defaults available

**Solution:**
1. Create and activate a template:
   ```bash
   python manage.py shell
   
   from apps.assessments.models import CertificateTemplate
   from apps.core.models import Tenant
   
   tenant = Tenant.objects.get(id=tenant_id)
   
   CertificateTemplate.objects.create(
       tenant=tenant,
       name="Default",
       is_active=True
   )
   ```

2. Or edit existing template and check **Is Active**

### Logo Not Showing in Email

**Cause:** Image file not found or encoding error

**Solution:**
1. Verify logo uploaded successfully in admin
2. Check image format (PNG/JPG/GIF)
3. Try smaller image (< 1MB)
4. Test with PNG with transparent background
5. Check email client logs

### Colors Not Applying

**Cause:** Invalid hex color format

**Solution:**
1. Check format is `#RRGGBB` or `#RGB`
2. No spaces or special characters
3. Valid examples: `#8B4513`, `#FFF`, `#000000`
4. Invalid examples: `8B4513` (no #), `#8B451` (wrong length)

### Certificate Generated But Not Sent

**Cause:** Missing or invalid email address

**Solution:**
1. Check student email: `Student.objects.get(id=id).email`
2. Update student email if missing
3. Send manually: `service.send_certificate_email(score)`

### Template Query Returning None

**Cause:** No active templates

**Solution:**
1. Verify templates exist: 
   ```python
   from apps.assessments.models import CertificateTemplate
   CertificateTemplate.objects.filter(tenant=tenant, is_active=True).count()
   ```

2. Check tenant assignment matches
3. Check **Is Active** box in admin
4. Activate tenant default template (assessment=null)

## Database Queries

### Find All Active Templates for Tenant

```python
from apps.assessments.models import CertificateTemplate

templates = CertificateTemplate.objects.filter(
    tenant=tenant,
    is_active=True
)
```

### Find Assessment-Specific Template

```python
template = CertificateTemplate.objects.get(
    tenant=tenant,
    assessment=assessment,
    is_active=True
)
```

### Find Tenant Default Template

```python
template = CertificateTemplate.objects.get(
    tenant=tenant,
    assessment__isnull=True,
    is_active=True
)
```

### Count Certificates Generated

```python
from apps.assessments.models import AssessmentScore

count = AssessmentScore.objects.filter(
    tenant=tenant,
    certificate_generated=True
).count()
```

### Find Certificates Waiting to be Sent

```python
scores = AssessmentScore.objects.filter(
    tenant=tenant,
    is_passed=True,
    certificate_generated=False
)
```

## Performance Considerations

### Database Indexes

Automatic indexes on:
- `(tenant, assessment)` - Fast template lookup
- `(tenant, is_active)` - Fast active template queries

### Image Optimization

Logo embedded as base64 in email:
- No external HTTP requests
- Works in all email clients
- Keep images < 500KB for email compatibility
- Base64 encoding increases size by ~33%

### Bulk Operations

For bulk certificate generation:
```python
# Efficient query
scores = AssessmentScore.objects.filter(
    tenant=tenant,
    is_passed=True,
    certificate_generated=False
).select_related('student_assessment__assessment', 'student_assessment__student')

for score in scores:
    service.generate_certificate(score)
```

## Best Practices

1. **Always Create Tenant Default** - Fallback for missing templates
2. **Test Email Delivery** - Send test certificate before production
3. **Backup Custom Designs** - Document custom colors and fonts
4. **Logo Optimization** - Use PNG with transparent background
5. **Brand Consistency** - Use same colors and fonts across templates
6. **Regular Audits** - Verify active templates exist
7. **Error Logging** - Monitor certificate generation failures
8. **Version Control** - Document template changes

## Support & Maintenance

### Check System Health

```python
from apps.assessments.models import CertificateTemplate, AssessmentScore

# Count templates per tenant
for tenant in Tenant.objects.all():
    count = CertificateTemplate.objects.filter(tenant=tenant).count()
    print(f"{tenant.name}: {count} templates")

# Check certificate generation stats
stats = AssessmentScore.objects.aggregate(
    total=Count('id'),
    generated=Count('id', filter=Q(certificate_generated=True)),
    pending=Count('id', filter=Q(is_passed=True, certificate_generated=False))
)
```

### Monitor Errors

```python
import logging

logger = logging.getLogger('apps.assessments.services.certificate_service')

# All certificate generation errors logged here
# Check application logs for failures
```

### Validate Data

```python
from apps.assessments.models import CertificateTemplate

# Find templates with invalid colors
for template in CertificateTemplate.objects.all():
    try:
        template.clean()
    except Exception as e:
        print(f"Invalid: {template.name} - {str(e)}")
```
