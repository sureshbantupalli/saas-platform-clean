from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0006_alter_branch_managers'),
        ('members', '0004_alter_member_branches'),
    ]

    operations = [
        migrations.CreateModel(
            name='MessageAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_name', models.CharField(max_length=100)),
                ('channel', models.CharField(max_length=20)),
                ('status', models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed')], max_length=10)),
                ('attempt_number', models.PositiveIntegerField(default=1)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='message_attempts', to='core.tenant')),
                ('member', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='message_attempts', to='members.member')),
            ],
            options={
                'db_table': 'engagement_message_attempt',
                'ordering': ['-sent_at'],
            },
        ),
    ]
