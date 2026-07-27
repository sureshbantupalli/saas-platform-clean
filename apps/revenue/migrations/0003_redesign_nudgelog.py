"""
Replace NudgeLog.event_key (opaque string) with proper relational fields:
member FK + event_name + payment_id + due_date.

The composite UniqueConstraint with nulls_distinct=False gives the same
idempotency guarantee as the old event_key unique column, but allows
dashboards and queries to filter by field instead of parsing a string.

NudgeLog is an idempotency ledger, not business data.  Existing rows are
cleared before the schema change — they cannot be migrated because the old
event_key format does not preserve the member FK.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('revenue', '0002_nudgelog'),
        ('members', '0004_alter_member_branches'),
    ]

    operations = [
        # NudgeLog is an idempotency ledger, not business data.
        # Clear rows before schema change; event_key format is not migratable.
        migrations.RunSQL(
            'TRUNCATE TABLE revenue_nudge_log',
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Drop old opaque-string column (unique index dropped automatically).
        migrations.RemoveField(model_name='nudgelog', name='event_key'),

        # Add member FK (nullable during migration; table is empty after TRUNCATE).
        migrations.AddField(
            model_name='nudgelog',
            name='member',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='nudge_logs',
                to='members.member',
            ),
        ),
        migrations.AddField(
            model_name='nudgelog',
            name='event_name',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='nudgelog',
            name='payment_id',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='nudgelog',
            name='due_date',
            field=models.DateField(blank=True, null=True),
        ),

        # Make member non-nullable (table is empty, so safe).
        migrations.AlterField(
            model_name='nudgelog',
            name='member',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='nudge_logs',
                to='members.member',
            ),
        ),

        # Composite unique constraint with NULLS NOT DISTINCT so that
        # risk-warning rows (payment_id=NULL, due_date=NULL) are unique per member.
        migrations.AddConstraint(
            model_name='nudgelog',
            constraint=models.UniqueConstraint(
                fields=['member', 'event_name', 'payment_id', 'due_date'],
                name='unique_nudge_per_event',
                nulls_distinct=False,
            ),
        ),
    ]
