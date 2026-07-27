# Certificate Customization System - Test Plan

## Pre-Deployment Testing Checklist

### 1. Migration Testing

#### Test 1.1: Migration Applies Successfully
```bash
# Reset to previous state
python manage.py migrate assessments 0001_initial

# Apply new migration
python manage.py migrate assessments 0002_certificatetemplate

# Expected: Migration completes without errors
```

**Verification:**
```bash
python manage.py showmigrations assessments
# Output should show 0002_certificatetemplate as [X]
```

#### Test 1.2: Reverse Migration Works
```bash
# Reverse the migration
python manage.py migrate assessments 0001_initial

# Verify certificate_templates table removed
python manage.py dbshell
> SELECT * FROM information_schema.tables WHERE table_name = 'certificate_templates';
> exit

# Re-apply migration
python manage.py migrate assessments 0002_certificatetemplate
```

### 2. Model Testing

#### Test 2.1: Create CertificateTemplate with Default Values
```python
python manage.py shell

from apps.assessments.models import CertificateTemplate
from apps.core.models import Tenant

tenant = Tenant.objects.first()

template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Test Template"
)

# Verify defaults
assert template.certificate_title == "Certificate of Completion"
assert template.certificate_subtitle == "Setu Yoga Studio"
assert template.border_color == "#8B4513"
assert template.title_color == "#8B4513"
assert template.text_color == "#333"
assert template.font_family == "Georgia"
assert template.authorized_by == "Studio Director"
assert template.is_active == True
assert template.assessment is None

print("✓ Default values correct")
```

#### Test 2.2: Create Assessment-Specific Template
```python
from apps.assessments.models import Assessment, CertificateTemplate

assessment = Assessment.objects.first()

template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Assessment Template",
    assessment=assessment,
    certificate_title="Yoga Certification",
    border_color="#D4AF37"
)

assert template.assessment == assessment
assert template.certificate_title == "Yoga Certification"
assert template.border_color == "#D4AF37"

print("✓ Assessment-specific template created")
```

#### Test 2.3: Color Validation
```python
from django.core.exceptions import ValidationError

# Test valid colors
valid_colors = ["#8B4513", "#FFF", "#000000", "#FFFFFF", "#123ABC"]

for color in valid_colors:
    template = CertificateTemplate(
        tenant=tenant,
        name=f"Color {color}",
        border_color=color
    )
    template.clean()  # Should not raise
    print(f"✓ Valid color: {color}")

# Test invalid colors
invalid_colors = ["8B4513", "#12345", "#12345G", "#12345"]

for color in invalid_colors:
    template = CertificateTemplate(
        tenant=tenant,
        name=f"Invalid {color}",
        border_color=color
    )
    try:
        template.clean()
        print(f"✗ Should have failed: {color}")
    except ValidationError:
        print(f"✓ Invalid color rejected: {color}")
```

#### Test 2.4: Unique Constraint
```python
# Create first active template
t1 = CertificateTemplate.objects.create(
    tenant=tenant,
    assessment=None,
    is_active=True,
    name="Default 1"
)

# Try to create second active template without assessment
# (should fail if constraint enforced)
try:
    t2 = CertificateTemplate.objects.create(
        tenant=tenant,
        assessment=None,
        is_active=True,
        name="Default 2"
    )
    print("✗ Constraint not enforced")
except Exception as e:
    print(f"✓ Constraint enforced: {str(e)}")

# Deactivate first, then create second (should work)
t1.is_active = False
t1.save()

t2 = CertificateTemplate.objects.create(
    tenant=tenant,
    assessment=None,
    is_active=True,
    name="Default 2"
)
print("✓ Can create new template after deactivating old one")
```

### 3. CertificateService Testing

#### Test 3.1: Template Resolution
```python
from apps.assessments.services.certificate_service import CertificateService

service = CertificateService(tenant=tenant)
assessment = Assessment.objects.first()

# Create templates
default = CertificateTemplate.objects.create(
    tenant=tenant,
    assessment=None,
    is_active=True,
    name="Default"
)

specific = CertificateTemplate.objects.create(
    tenant=tenant,
    assessment=assessment,
    is_active=True,
    name="Specific"
)

# Test resolution: should return specific
template = service.get_template_for_assessment(assessment)
assert template == specific
print("✓ Assessment-specific template preferred")

# Deactivate specific, should fall back to default
specific.is_active = False
specific.save()

template = service.get_template_for_assessment(assessment)
assert template == default
print("✓ Falls back to default when specific inactive")

# Deactivate default, should return None
default.is_active = False
default.save()

template = service.get_template_for_assessment(assessment)
assert template is None
print("✓ Returns None when no templates available")
```

#### Test 3.2: Certificate Generation
```python
from apps.assessments.models import AssessmentScore

# Create test score (passed)
score = AssessmentScore.objects.filter(is_passed=True).first()

service = CertificateService(tenant=score.tenant)

# Generate certificate
cert_data = service.generate_certificate(score)

# Verify result
assert cert_data is not None
assert "student_name" in cert_data
assert "certificate_number" in cert_data
assert score.certificate_generated == True
assert score.certificate_generated_at is not None

print("✓ Certificate generated successfully")
```

#### Test 3.3: Certificate Revocation
```python
# Revoke certificate
updated_score = service.revoke_certificate(score)

assert updated_score.certificate_generated == False
assert updated_score.certificate_generated_at is None

print("✓ Certificate revoked successfully")

# Can generate again
cert_data = service.generate_certificate(score)
assert score.certificate_generated == True

print("✓ Can regenerate after revocation")
```

#### Test 3.4: HTML Rendering
```python
# Test with no template (defaults)
html = service._render_certificate_template({
    "student_name": "John Doe",
    "assessment_name": "Yoga 101",
    "percentage": 92.5,
    "passing_score": 60,
    "certificate_number": "CERT-TEST",
    "issued_date": "June 28, 2026"
})

assert "John Doe" in html
assert "Yoga 101" in html
assert "92.50%" in html
assert "CERT-TEST" in html
assert "Georgia" in html  # Default font
assert "#8B4513" in html  # Default border color
assert "<!DOCTYPE html>" in html or "<html>" in html

print("✓ HTML rendered with defaults")

# Test with custom template
template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Custom",
    certificate_title="Custom Title",
    border_color="#D4AF37",
    font_family="Arial"
)

html = service._render_certificate_with_template({
    "student_name": "Jane Smith",
    "assessment_name": "Advanced Yoga",
    "percentage": 95.0,
    "passing_score": 70,
    "certificate_number": "CERT-002",
    "issued_date": "June 28, 2026"
}, template=template)

assert "Custom Title" in html
assert "#D4AF37" in html
assert "Jane Smith" in html
assert "Advanced Yoga" in html

print("✓ HTML rendered with custom template")
```

### 4. Admin Interface Testing

#### Test 4.1: Admin Registration
```bash
# Start development server
python manage.py runserver

# Navigate to /admin/assessments/certificatetemplate/
# Verify:
# - Admin page loads
# - List view shows templates
# - Add button works
# - Edit button works
```

#### Test 4.2: Admin Features
**In Django Admin:**

1. List Display:
   - [ ] Name displays
   - [ ] Assessment (or "Tenant Default") displays
   - [ ] Tenant displays
   - [ ] Active status badge displays
   - [ ] Has logo indicator displays
   - [ ] Font family displays
   - [ ] Created date displays

2. Filters Work:
   - [ ] Filter by tenant
   - [ ] Filter by is_active
   - [ ] Filter by assessment
   - [ ] Filter by font_family

3. Search Works:
   - [ ] Search by name
   - [ ] Search by certificate_title
   - [ ] Search by certificate_subtitle

4. Fieldsets Display:
   - [ ] Basic Info fieldset
   - [ ] Content fieldset
   - [ ] Styling fieldset
   - [ ] Logo fieldset

5. Color Preview:
   - [ ] Color fields display
   - [ ] Can edit hex values

6. Logo Upload:
   - [ ] Can upload image
   - [ ] Preview displays after save
   - [ ] Can change image

### 5. Email Integration Testing

#### Test 5.1: Email Sending
```python
from apps.assessments.models import AssessmentScore

score = AssessmentScore.objects.filter(
    is_passed=True,
    certificate_generated=False
).first()

service = CertificateService(tenant=score.tenant)

# Generate certificate
service.generate_certificate(score)

# Send email
success = service.send_certificate_email(score)

assert success == True
print("✓ Email sent successfully")

# Check mailbox (depends on email backend)
# For testing: check console output or email file
```

#### Test 5.2: Logo Embedding
```python
from django.core.files.uploadedfile import SimpleUploadedFile

# Create test image
test_image = SimpleUploadedFile(
    "test.png",
    b"fake image content",
    content_type="image/png"
)

template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="With Logo",
    logo=test_image,
    is_active=True
)

# Get data URI
data_uri = service._get_logo_data_uri(template.logo)

assert data_uri.startswith("data:image/")
assert "base64" in data_uri
print("✓ Logo converted to data URI")

# Test rendering with logo
html = service._render_certificate_with_template(
    {
        "student_name": "Test User",
        "assessment_name": "Test",
        "percentage": 85,
        "passing_score": 60,
        "certificate_number": "CERT-LOGO",
        "issued_date": "Today"
    },
    template=template
)

assert data_uri in html
assert "img src" in html
print("✓ Logo embedded in HTML")
```

#### Test 5.3: Email Without Logo
```python
template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="No Logo",
    logo=None,
    is_active=True
)

data_uri = service._get_logo_data_uri(template.logo)
assert data_uri == ""
print("✓ Handles missing logo gracefully")

# Should still render HTML
html = service._render_certificate_with_template({
    "student_name": "Test",
    "assessment_name": "Test",
    "percentage": 80,
    "passing_score": 60,
    "certificate_number": "CERT-NOLOGO",
    "issued_date": "Today"
}, template=template)

assert "<html>" in html
print("✓ Renders without logo")
```

### 6. Multi-Tenant Isolation Testing

#### Test 6.1: Tenant Isolation
```python
from apps.core.models import Tenant

# Create second tenant
tenant1 = Tenant.objects.first()
tenant2 = Tenant.objects.create(
    name="Test Tenant 2",
    subdomain="test-tenant-2"
)

# Create templates for different tenants
t1 = CertificateTemplate.objects.create(
    tenant=tenant1,
    name="Tenant 1 Template"
)

t2 = CertificateTemplate.objects.create(
    tenant=tenant2,
    name="Tenant 2 Template"
)

# Service for tenant1 should only see tenant1 templates
service1 = CertificateService(tenant=tenant1)
template = service1.get_template_for_assessment(Assessment.objects.first())

# Should get tenant1 template
if template:
    assert template.tenant == tenant1
    print("✓ Service1 returns tenant1 template")

# Verify service1 can't access tenant2 data
try:
    service1.generate_certificate(
        AssessmentScore.objects.filter(tenant=tenant2).first()
    )
    print("✗ Cross-tenant access not blocked")
except ValidationError:
    print("✓ Cross-tenant access blocked")
```

### 7. Performance Testing

#### Test 7.1: Query Efficiency
```python
from django.test.utils import override_settings
from django.db import connection, reset_queries

@override_settings(DEBUG=True)
def test_template_lookup():
    reset_queries()
    
    service = CertificateService(tenant=tenant)
    assessment = Assessment.objects.first()
    
    # Should use indexes
    template = service.get_template_for_assessment(assessment)
    
    # Count queries
    query_count = len(connection.queries)
    
    assert query_count <= 2  # Should be 1-2 queries max
    print(f"✓ Template lookup uses {query_count} queries")

test_template_lookup()
```

### 8. Edge Cases

#### Test 8.1: Missing Student Email
```python
from apps.assessments.models import StudentAssessment

# Create student without email
student_assessment = StudentAssessment.objects.first()
student_assessment.student.email = None
student_assessment.student.save()

score = AssessmentScore.objects.filter(
    is_passed=True,
    student_assessment=student_assessment
).first()

service = CertificateService(tenant=score.tenant)
service.generate_certificate(score)

# Try to send
try:
    service.send_certificate_email(score)
    print("✗ Should reject missing email")
except ValidationError as e:
    print(f"✓ Rejects missing email: {str(e)}")
```

#### Test 8.2: Failed Score
```python
score = AssessmentScore.objects.filter(is_passed=False).first()
service = CertificateService(tenant=score.tenant)

try:
    service.generate_certificate(score)
    print("✗ Should reject failed score")
except ValidationError:
    print("✓ Rejects failed score")
```

#### Test 8.3: Already Generated
```python
score = AssessmentScore.objects.filter(
    is_passed=True,
    certificate_generated=True
).first()

service = CertificateService(tenant=score.tenant)

try:
    service.generate_certificate(score)
    print("✗ Should reject already generated")
except ValidationError:
    print("✓ Rejects already generated certificate")
```

## Test Summary

**Total Test Cases:** 30+
**Coverage Areas:**
- Database migrations
- Model creation and validation
- Service layer functionality
- Admin interface
- Email integration
- Multi-tenant isolation
- Performance
- Edge cases

**Success Criteria:**
- All tests pass without errors
- No data corruption
- Proper error handling
- Email templates render correctly
- Admin interface functions smoothly
- Tenant isolation maintained

## Deployment Verification

After deploying to production:

1. [ ] Run all tests pass
2. [ ] Migrations apply successfully
3. [ ] Create test tenant template
4. [ ] Generate test certificate
5. [ ] Verify email sends
6. [ ] Check certificate appearance
7. [ ] Monitor error logs for 24 hours
8. [ ] Get stakeholder sign-off
9. [ ] Document any issues found
10. [ ] Update runbooks if needed

## Rollback Plan

If issues found in production:

```bash
# Revert to previous state
python manage.py migrate assessments 0001_initial

# This removes certificate_templates table but preserves data
# (if needed to restore, database backup can be restored)

# Existing certificates continue to work via hardcoded defaults
```

No changes to existing assessment models, so minimal risk.
