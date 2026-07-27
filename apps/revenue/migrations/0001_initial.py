import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('members', '0004_alter_member_branches'),
    ]

    operations = [
        migrations.CreateModel(
            name='MemberRevenueSignal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('member', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='revenue_signal',
                    to='members.member',
                )),
                ('risk_level', models.CharField(
                    choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                    default='low',
                    max_length=10,
                )),
                ('risk_reason', models.CharField(blank=True, max_length=50)),
                ('last_payment_at', models.DateTimeField(blank=True, null=True)),
                ('missed_payments_count', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'db_table': 'revenue_member_signal',
            },
        ),
    ]
