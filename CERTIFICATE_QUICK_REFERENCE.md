# Certificate Customization System - Quick Reference

## File Locations

| Component | File Path |
|-----------|-----------|
| Model | `/c/Users/bsure/projects/saas-platform-clean/apps/assessments/models.py` |
| Service | `/c/Users/bsure/projects/saas-platform-clean/apps/assessments/services/certificate_service.py` |
| Admin | `/c/Users/bsure/projects/saas-platform-clean/apps/assessments/admin.py` |
| Migration | `/c/Users/bsure/projects/saas-platform-clean/apps/assessments/migrations/0002_certificatetemplate.py` |

## Quick Commands

### Apply Migration
```bash
python manage.py migrate assessments
```

### Create Template (Admin)
```bash
# Navigate to: /admin/assessments/certificatetemplate/
# Click "Add Certificate Template"
# Fill form and save
```

### Create Template (Code)
```python
from apps.assessments.models import CertificateTemplate
from apps.core.models import Tenant

tenant = Tenant.objects.get(subdomain="studio")
template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Default",
    is_active=True
)
```

### Generate Certificate
```python
from apps.assessments.services.certificate_service import CertificateService

service = CertificateService(tenant=tenant)
cert = service.generate_certificate(score)
success = service.send_certificate_email(score)
```

### Get Template
```python
template = service.get_template_for_assessment(assessment)
```

### Revoke Certificate
```python
service.revoke_certificate(score)
```

## Template Fields

### Content Fields
- `name` - Template name (e.g., "Studio Default")
- `certificate_title` - Main title (default: "Certificate of Completion")
- `certificate_subtitle` - Org name (default: "Setu Yoga Studio")
- `footer_text` - Optional footer
- `authorized_by` - Signature line (default: "Studio Director")

### Style Fields
- `border_color` - Hex color for border (e.g., "#8B4513")
- `title_color` - Hex color for title (e.g., "#8B4513")
- `text_color` - Hex color for body (e.g., "#333")
- `font_family` - Georgia, Arial, or Times New Roman

### Other Fields
- `assessment` - Assessment (null = tenant default)
- `logo` - Image file
- `is_active` - Boolean

## Color Codes

| Color | Code |
|-------|------|
| Brown | `#8B4513` |
| Dark Brown | `#A0522D` |
| Gold | `#FFD700` |
| Dark Gold | `#D4AF37` |
| Black | `#000000` |
| Dark Gray | `#333333` |
| Navy | `#000080` |
| Dark Navy | `#003366` |
| Green | `#228B22` |
| Dark Green | `#2F5233` |
| White | `#FFFFFF` |
| Light Gray | `#CCCCCC` |

## Font Options

| Font | Use Case |
|------|----------|
| Georgia | Elegant, traditional |
| Arial | Modern, clean |
| Times New Roman | Formal, academic |

## Certificate Rendering

**Default Appearance:**
- Title: Brown (#8B4513)
- Border: Brown (#8B4513)
- Font: Georgia
- Text: Dark gray (#333)

**With Custom Template:**
- Applies template colors
- Uses template font
- Includes logo if provided
- Shows footer if provided
- Shows authorized_by signature line

## Template Resolution

1. **Assessment-specific** (if active)
2. **Tenant default** (assessment=null, if active)
3. **Hardcoded defaults** (if no templates)

## Validation Rules

### Hex Colors
- Valid: `#8B4513`, `#FFF`, `#000000`
- Invalid: `8B4513` (no #), `#12345` (wrong length)

### Images
- Format: PNG, JPG, GIF
- Size: < 500KB recommended
- Display: 150x150px on certificate

### Assessment
- Optional (null = tenant default)
- Only one active per assessment per tenant

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Template not appearing | Check is_active=True |
| Logo not showing in email | Verify image format (PNG/JPG) |
| Color not applying | Check hex format (#RRGGBB) |
| Certificate not generating | Verify score.is_passed=True |
| Email not sending | Check student.email not None |
| Template not found | Create tenant default |
| Admin not showing | Check migration applied |

## Key Methods

```python
# Get template for assessment
template = service.get_template_for_assessment(assessment)

# Generate certificate
cert = service.generate_certificate(score)

# Send email
success = service.send_certificate_email(score)

# Revoke certificate
service.revoke_certificate(score)

# Render HTML
html = service._render_certificate_with_template(context, template)

# Get logo as data URI
data_uri = service._get_logo_data_uri(template.logo)
```

## Database Info

**Table:** `certificate_templates`

**Indexes:**
- `(tenant_id, assessment_id)`
- `(tenant_id, is_active)`

**Constraint:**
- `UNIQUE(tenant_id, assessment_id) WHERE is_active=TRUE`

## Admin URL

```
/admin/assessments/certificatetemplate/
```

## Common Customizations

### Professional Certificate
- **Border Color:** `#000080` (Navy)
- **Title Color:** `#000080` (Navy)
- **Font:** Times New Roman
- **Subtitle:** "Professional Certification Program"

### Elegant Certificate
- **Border Color:** `#D4AF37` (Gold)
- **Title Color:** `#D4AF37` (Gold)
- **Font:** Georgia
- **Logo:** Studio logo with transparent background

### Modern Certificate
- **Border Color:** `#333333` (Dark Gray)
- **Title Color:** `#333333` (Dark Gray)
- **Font:** Arial
- **Footer:** Custom footer text

## Performance Tips

1. Create tenant default (falls back if assessment template missing)
2. Use PNG for logos (better compression)
3. Keep images < 500KB
4. Reuse colors across templates (brand consistency)

## Email Notes

- Logo embedded as base64 (works in all clients)
- HTML renders in email/web
- No external resources required
- Professional formatting applied

## Support

**For Issues:**
1. Check CERTIFICATE_SYSTEM.md for detailed docs
2. Check CERTIFICATE_USAGE_GUIDE.md for examples
3. Check CERTIFICATE_TEST_PLAN.md for testing
4. Review application logs

**For Development:**
1. Models: apps/assessments/models.py
2. Service: apps/assessments/services/certificate_service.py
3. Admin: apps/assessments/admin.py
4. Tests: See test plan document

## Next Steps

1. [ ] Apply migration: `python manage.py migrate`
2. [ ] Create default template in admin
3. [ ] Test certificate generation
4. [ ] Verify email delivery
5. [ ] Check certificate appearance
6. [ ] Get stakeholder sign-off
7. [ ] Monitor for 24 hours
8. [ ] Document any customizations

## Links

- **System Docs:** CERTIFICATE_SYSTEM.md
- **Usage Guide:** CERTIFICATE_USAGE_GUIDE.md
- **Test Plan:** CERTIFICATE_TEST_PLAN.md
- **Implementation:** CERTIFICATE_IMPLEMENTATION_SUMMARY.md
