from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('engagement', '0003_memberengagementscore'),
    ]

    operations = [
        # MessageAttempt: failure intelligence fields
        migrations.AddField(
            model_name='messageattempt',
            name='error_code',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='messageattempt',
            name='error_message',
            field=models.TextField(blank=True),
        ),
        # RetryRule: priority-aware processing
        migrations.AddField(
            model_name='retryrule',
            name='priority',
            field=models.CharField(
                choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')],
                default='normal',
                max_length=10,
            ),
        ),
        # MemberEngagementScore: recency signal
        migrations.AddField(
            model_name='memberengagementscore',
            name='last_success_channel',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='memberengagementscore',
            name='last_success_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
