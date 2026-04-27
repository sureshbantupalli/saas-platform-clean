import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0006_alter_branch_managers'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantWhatsAppSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tone', models.CharField(
                    choices=[('FORMAL', 'Formal (Dear {name})'), ('FRIENDLY', 'Friendly (Hi {name}!)'), ('MINIMAL', 'Minimal (no greeting)')],
                    default='FRIENDLY', max_length=10,
                )),
                ('signature_enabled', models.BooleanField(default=True)),
                ('cta_style', models.CharField(
                    choices=[('PAY_NOW', 'Pay Now (link)'), ('CONFIRM', 'Confirm (Reply YES)'), ('CONTACT', 'Contact (phone number)'), ('NONE', 'None')],
                    default='NONE', max_length=10,
                )),
                ('template_overrides', models.JSONField(blank=True, default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='whatsapp_settings',
                    to='core.tenant',
                )),
            ],
            options={
                'db_table': 'settings_whatsapp',
            },
        ),
    ]
