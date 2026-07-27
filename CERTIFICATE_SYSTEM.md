# Certificate Customization System Documentation

## Overview

The Certificate Customization System allows tenants to create and manage custom certificate templates with full control over:
- Certificate text (title, subtitle, footer, authorization line)
- Visual styling (colors, borders, fonts)
- Logo/branding images
- Assessment-specific or tenant-wide defaults

## System Architecture

### Models

#### CertificateTemplate (TenantAwareModel)
Complete certificate template with customization options.

**Key Fields:**
- `name` - Template name (e.g., "Yoga Fundamentals Certificate")
- `assessment` - ForeignKey to Assessment (null = tenant default)
- `certificate_title` - Main title (default: "Certificate of Completion")
- `certificate_subtitle` - Subtitle/organization (default: "Setu Yoga Studio")
- `footer_text` - Optional custom footer
- `authorized_by` - Signature line (default: "Studio Director")
- `logo` - ImageField for logo/branding
- `border_color` - Hex color for border (default: "#8B4513")
- `title_color` - Hex color for title (default: "#8B4513")
- `text_color` - Hex color for body text (default: "#333")
- `font_family` - Georgia/Arial/Times New Roman (default: Georgia)
- `is_active` - Boolean activation flag
- `tenant` - ForeignKey to Tenant (automatic isolation)

**Constraints:**
- Only one active template per assessment per tenant
- Multiple templates allowed (different assessments, inactive templates)
- Automatic fallback to tenant default if assessment template missing

### Service Layer

#### CertificateService

**Key Methods:**

1. **get_template_for_assessment(assessment)**
   - Retrieves active template for assessment
   - Resolution: Assessment-specific → Tenant default → None
   - Returns CertificateTemplate or None

2. **generate_certificate(score)**
   - Generates certificate for passing score
   - Validates pass status and previous generation
   - Returns certificate data dict
   - Marks score.certificate_generated = True

3. **send_certificate_email(score, recipient_email=None)**
   - Emails certificate to student
   - Uses custom template styling
   - Embeds logo as data URI in email
   - Returns True/False success status

4. **_render_certificate_with_template(context, template=None)**
   - Renders certificate HTML with template styling
   - Falls back to hardcoded defaults if no template
   - Applies custom colors, fonts, logos
   - Includes signature line and footer

5. **revoke_certificate(score)**
   - Revokes previously issued certificate
   - Clears certificate_generated flag
   - Allows certificate to be regenerated

**Helper Methods:**

- `_get_logo_data_uri(logo_field)` - Converts logo to base64 data URI for embedding
- `_generate_certificate_number(score)` - Creates unique certificate number
- `_render_certificate_template(context)` - Legacy backward compatibility method

## Usage Examples

### Creating a Tenant Default Certificate Template

```python
from apps.core.models import Tenant
from apps.assessments.models import CertificateTemplate

tenant = Tenant.objects.get(subdomain="my-studio")

template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Studio Default Certificate",
    assessment=None,  # Null = tenant default
    certificate_title="Certificate of Completion",
    certificate_subtitle="My Yoga Studio",
    footer_text="This certificate recognizes successful completion",
    authorized_by="Studio Director",
    border_color="#8B4513",
    title_color="#8B4513",
    text_color="#333",
    font_family="Georgia",
    is_active=True,
)
```

### Creating an Assessment-Specific Template

```python
from apps.assessments.models import Assessment, CertificateTemplate

assessment = Assessment.objects.get(name="Yoga Fundamentals")

template = CertificateTemplate.objects.create(
    tenant=tenant,
    name="Yoga Fundamentals Certificate",
    assessment=assessment,  # Assessment-specific
    certificate_title="Yoga Fundamentals Certification",
    certificate_subtitle="200-Hour Training Program",
    authorized_by="Certified Yoga Instructor",
    border_color="#D4AF37",  # Gold
    title_color="#D4AF37",
    logo=logo_file,  # ImageField
    is_active=True,
)
```

### Generating and Emailing a Certificate

```python
from apps.assessments.models import AssessmentScore
from apps.assessments.services.certificate_service import CertificateService

score = AssessmentScore.objects.get(id=score_id)
service = CertificateService(tenant=score.tenant)

# Generate certificate
cert_data = service.generate_certificate(score)

# Send email
success = service.send_certificate_email(score)

if success:
    print(f"Certificate sent to {score.student_assessment.student.email}")
```

### Template Resolution Example

```python
from apps.assessments.services.certificate_service import CertificateService

service = CertificateService(tenant=tenant)
assessment = Assessment.objects.get(id=assessment_id)

# Retrieves in this order:
# 1. Active assessment-specific template
# 2. Active tenant default template
# 3. None (hardcoded defaults used)
template = service.get_template_for_assessment(assessment)
```

## Admin Interface

### CertificateTemplateAdmin Features

**List Display:**
- Name
- Assessment (or "Tenant Default")
- Tenant
- Active status (badge)
- Has logo indicator
- Font family
- Created date

**Filters:**
- Tenant
- Is Active
- Assessment
- Font Family
- Created Date

**Search:**
- Template name
- Certificate title
- Certificate subtitle

**Fieldsets:**
- **Basic Info** - name, assessment, is_active, created_by
- **Content** - certificate_title, subtitle, footer, authorized_by
- **Styling** - border_color, title_color, text_color, font_family
- **Logo** - logo file and inline preview

**Special Features:**
- Color picker friendly (hex color fields)
- Logo preview in admin interface
- Assessment link with dropdown
- Status badge with colors
- Logo presence indicator

## Certificate Rendering

### HTML Output Features

The rendered certificate includes:

**Header Section:**
- Custom logo (if provided, embedded as data URI)
- Custom title
- Custom subtitle

**Body Section:**
- Student name (underlined)
- Assessment name (underlined)
- Score and passing score
- Issue date

**Signature Section:**
- Signature line with authorized_by label
- Optional footer text

**Certificate Number:**
- Unique identifier (CERT-{TENANT}-{STUDENT}-{DATE})

**Styling:**
- Font family applied globally
- Custom border color
- Custom title color
- Custom text color
- Professional spacing and typography

## Color Customization

All color fields use hex format with validation:

**Valid Formats:**
- 6-digit: `#8B4513`
- 3-digit: `#FFF`

**Common Colors:**
- Brown (traditional): `#8B4513`, `#A0522D`
- Gold (premium): `#FFD700`, `#D4AF37`
- Navy (professional): `#000080`, `#003366`
- Green (wellness): `#228B22`, `#2F5233`

**Validation:**
- Automatic hex validation in model.clean()
- Admin displays color preview
- Invalid formats rejected with clear error

## Font Options

**Available Fonts:**
1. Georgia (Serif) - Default, elegant
2. Arial (Sans-serif) - Modern, clean
3. Times New Roman (Serif) - Traditional, formal

Font family applies to entire certificate globally.

## Logo Handling

**Upload Details:**
- Path: `certificate_logos/{YYYY}/{MM}/`
- Formats: PNG, JPG, GIF
- Embedded in email as base64 data URI (no external dependencies)
- Max display: 150x150px on certificate

**Email Embedding:**
- Automatically converted to data URI
- Works in all email clients
- No external image downloads required
- Gracefully handles missing images

## Multi-Tenant Isolation

All templates are fully tenant-isolated:

1. **Automatic Tenant Assignment** - Via TenantAwareModel
2. **Query Filtering** - TenantManager automatically filters
3. **Constraint Protection** - Unique constraints scoped to tenant
4. **Service Isolation** - CertificateService validates tenant on all operations

## Migration Information

### Migration 0002_certificatetemplate

**Creates:**
- `certificate_templates` table
- All model fields and constraints
- Indexes on (tenant, assessment) and (tenant, is_active)
- Unique constraint for active templates per assessment

**Dependencies:**
- assessments:0001_initial
- core:0006_alter_branch_managers
- auth

**Safe to Apply:**
- No data loss (new table only)
- No existing data modifications
- Can be applied to databases with existing assessments

## Backward Compatibility

**Legacy Support:**
- `_render_certificate_template(context)` - Delegates to new method with template=None
- Existing code continues to work unchanged
- New features are opt-in

**Certificate Service Behavior:**
- If no template exists, uses hardcoded defaults
- Default colors, fonts, and text are identical to previous version
- Existing functionality preserved

## Production Deployment Checklist

- [ ] Review all color hex codes for brand compliance
- [ ] Upload logo image(s) if using custom branding
- [ ] Create and activate default tenant template
- [ ] Create assessment-specific templates (if needed)
- [ ] Test certificate generation with real data
- [ ] Verify email delivery with custom styling
- [ ] Check logo rendering in multiple email clients
- [ ] Test fallback to defaults if templates deleted
- [ ] Run migrations on all environments
- [ ] Update documentation with custom colors/fonts

## Troubleshooting

### Template Not Appearing

1. Check `is_active` field is True
2. Verify correct assessment is selected
3. Confirm tenant assignment
4. Check database migrations applied

### Logo Not Displaying in Email

1. Verify image file uploaded successfully
2. Check image format (PNG/JPG/GIF)
3. Review browser console for base64 encoding errors
4. Test with smaller image file
5. Check email client compatibility

### Color Not Applying

1. Verify hex color format (#RRGGBB)
2. Check for typos in color codes
3. Clear browser cache
4. Regenerate certificate HTML
5. Test with known valid color (#000000 or #FFFFFF)

### Certificate Not Generating

1. Verify score.is_passed = True
2. Check score.certificate_generated is False
3. Ensure tenant isolation is correct
4. Review logs for detailed error messages

## API Reference

### CertificateTemplate Fields

```python
CertificateTemplate(
    tenant=Tenant,                          # Required (auto)
    name=str,                               # Required, 255 chars
    assessment=Assessment|None,             # Optional (null=default)
    certificate_title=str,                  # Default: "Certificate of Completion"
    certificate_subtitle=str,               # Default: "Setu Yoga Studio"
    footer_text=str,                        # Optional (blank)
    authorized_by=str,                      # Default: "Studio Director"
    border_color=str,                       # Default: "#8B4513" (hex)
    title_color=str,                        # Default: "#8B4513" (hex)
    text_color=str,                         # Default: "#333" (hex)
    font_family=str,                        # Default: "Georgia" (choices)
    logo=ImageField,                        # Optional (blank)
    is_active=bool,                         # Default: True
    created_by=User|None,                   # Optional (null)
)
```

### CertificateService Methods

```python
service = CertificateService(tenant=Tenant)

template = service.get_template_for_assessment(assessment: Assessment)
cert_data = service.generate_certificate(score: AssessmentScore)
success = service.send_certificate_email(
    score: AssessmentScore,
    recipient_email: str = None
)
updated_score = service.revoke_certificate(score: AssessmentScore)

html = service._render_certificate_with_template(context: dict, template: CertificateTemplate = None)
```

## Future Enhancements

Potential additions:
- QR code linking to verification portal
- Digital signature support
- Batch certificate generation
- Certificate revocation tracking
- Template versioning/history
- Email template customization
- Multiple language support
- PDF generation and storage
- Certificate sharing/download functionality
