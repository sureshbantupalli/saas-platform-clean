from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0005_tenantpaymentconfig_webhook_last_error'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_last_error_source',
            field=models.CharField(blank=True, default='', max_length=10),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_last_tested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
