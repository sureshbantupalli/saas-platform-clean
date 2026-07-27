import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('revenue', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='NudgeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_key', models.CharField(max_length=200, unique=True)),
                ('fired_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'db_table': 'revenue_nudge_log',
            },
        ),
    ]
