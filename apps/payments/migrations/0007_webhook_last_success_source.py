from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0006_webhook_test_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantpaymentconfig',
            name='webhook_last_success_source',
            field=models.CharField(blank=True, default='', max_length=10),
            preserve_default=False,
        ),
    ]
