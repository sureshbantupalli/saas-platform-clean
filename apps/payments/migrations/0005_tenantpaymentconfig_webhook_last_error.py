from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0004_payment_config_webhook_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_last_error',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
