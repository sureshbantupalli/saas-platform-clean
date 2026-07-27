from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_tenant_payment_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_status',
            field=models.CharField(
                choices=[('unverified', 'Not verified'), ('verified', 'Verified'), ('failed', 'Failed')],
                default='unverified',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
