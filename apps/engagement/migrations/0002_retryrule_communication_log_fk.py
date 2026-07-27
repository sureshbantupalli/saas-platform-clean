from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('engagement', '0001_initial'),
        ('communications', '0005_add_skipped_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='messageattempt',
            name='communication_log',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='attempts',
                to='communications.communicationlog',
            ),
        ),
        migrations.CreateModel(
            name='RetryRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_name', models.CharField(max_length=100)),
                ('channel', models.CharField(max_length=20)),
                ('max_attempts', models.PositiveSmallIntegerField(default=3)),
                ('retry_delay_minutes', models.PositiveIntegerField(default=60)),
            ],
            options={
                'db_table': 'engagement_retry_rule',
                'ordering': ['event_name', 'channel'],
                'unique_together': {('event_name', 'channel')},
            },
        ),
    ]
