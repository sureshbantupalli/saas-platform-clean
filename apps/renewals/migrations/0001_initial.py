import django.db.models.deletion
import django.db.models.manager
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0006_alter_branch_managers'),
        ('memberships', '0002_payment_tracking_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='RenewalTriggerLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('trigger_type', models.CharField(
                    choices=[
                        ('expiring_7d', 'Expiring in 7 days'),
                        ('expiring_3d', 'Expiring in 3 days'),
                        ('expiring_1d', 'Expiring in 1 day'),
                        ('expired', 'Expired (recovery)'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('expiry_date', models.DateField()),
                ('triggered_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('membership', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='renewal_logs',
                    to='memberships.membership',
                )),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='%(class)ss',
                    to='core.tenant',
                )),
            ],
            options={
                'db_table': 'renewals_trigger_log',
            },
            managers=[
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name='renewaltriggerlog',
            index=models.Index(
                fields=['membership', 'trigger_type', 'expiry_date'],
                name='renewals_tr_members_3b9715_idx',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='renewaltriggerlog',
            unique_together={('membership', 'trigger_type', 'expiry_date')},
        ),
    ]
