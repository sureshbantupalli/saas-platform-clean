from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('engagement', '0002_retryrule_communication_log_fk'),
        ('members', '0004_alter_member_branches'),
    ]

    operations = [
        migrations.CreateModel(
            name='MemberEngagementScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('preferred_channel', models.CharField(blank=True, max_length=20)),
                ('success_count', models.PositiveIntegerField(default=0)),
                ('failure_count', models.PositiveIntegerField(default=0)),
                ('last_engaged_at', models.DateTimeField(blank=True, null=True)),
                ('member', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='engagement_score',
                    to='members.member',
                )),
            ],
            options={
                'db_table': 'engagement_member_score',
            },
        ),
    ]
