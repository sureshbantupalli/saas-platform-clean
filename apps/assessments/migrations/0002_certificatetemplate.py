# Generated migration for CertificateTemplate model

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assessments', '0001_initial'),
        ('core', '0006_alter_branch_managers'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CertificateTemplate',
            fields=[
                ('is_deleted', models.BooleanField(default=False)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text="E.g., 'Yoga Fundamentals Certificate', 'Studio Default'", max_length=255)),
                ('certificate_title', models.CharField(default='Certificate of Completion', help_text="Main title on certificate (e.g., 'Certificate of Completion')", max_length=255)),
                ('certificate_subtitle', models.CharField(default='Setu Yoga Studio', help_text="Subtitle/organization name (e.g., 'Setu Yoga Studio')", max_length=255)),
                ('footer_text', models.TextField(blank=True, help_text='Optional custom footer text')),
                ('authorized_by', models.CharField(default='Studio Director', help_text="Signature/authorization line (e.g., 'Studio Director', 'Certified Instructor')", max_length=255)),
                ('border_color', models.CharField(default='#8B4513', help_text='Hex color for certificate border (e.g., #8B4513)', max_length=7)),
                ('title_color', models.CharField(default='#8B4513', help_text='Hex color for certificate title (e.g., #8B4513)', max_length=7)),
                ('text_color', models.CharField(default='#333', help_text='Hex color for body text (e.g., #333)', max_length=7)),
                ('font_family', models.CharField(choices=[('Georgia', 'Georgia (Serif)'), ('Arial', 'Arial (Sans-serif)'), ('Times New Roman', 'Times New Roman (Serif)')], default='Georgia', help_text='Font family for certificate', max_length=50)),
                ('logo', models.ImageField(blank=True, help_text='Optional logo/image to display on certificate', null=True, upload_to='certificate_logos/%Y/%m/')),
                ('is_active', models.BooleanField(default=True, help_text='Is this template active and available for use?')),
                ('assessment', models.ForeignKey(blank=True, help_text='If set, this template applies to this specific assessment. If null, this is tenant default.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='certificate_templates', to='assessments.assessment')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_certificate_templates', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.tenant')),
            ],
            options={
                'db_table': 'certificate_templates',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='certificatetemplate',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)),
                fields=('tenant', 'assessment', 'is_active'),
                name='unique_active_template_per_assessment'
            ),
        ),
        migrations.AddIndex(
            model_name='certificatetemplate',
            index=models.Index(fields=['tenant', 'assessment'], name='assessments_tenant_assessment_idx'),
        ),
        migrations.AddIndex(
            model_name='certificatetemplate',
            index=models.Index(fields=['tenant', 'is_active'], name='assessments_tenant_is_act_idx'),
        ),
    ]
