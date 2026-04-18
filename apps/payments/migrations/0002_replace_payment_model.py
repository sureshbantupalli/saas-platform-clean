"""
Replace the old booking-coupled Payment table with a gateway-agnostic model.
Adds PaymentEvent audit log table.
"""

import uuid
import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
        ("core", "0006_alter_branch_managers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Drop the old tightly-coupled Payment table
        migrations.DeleteModel(name="Payment"),

        # Create the new gateway-agnostic Payment model
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id",             models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("created_at",     models.DateTimeField(auto_now_add=True)),
                ("updated_at",     models.DateTimeField(auto_now=True)),
                ("is_deleted",     models.BooleanField(default=False)),
                ("amount",         models.DecimalField(max_digits=10, decimal_places=2)),
                ("currency",       models.CharField(max_length=3, default="INR")),
                ("status",         models.CharField(max_length=20, choices=[("CREATED","Created"),("PENDING","Pending"),("SUCCESS","Success"),("FAILED","Failed"),("CANCELLED","Cancelled"),("REFUNDED","Refunded")], default="CREATED", db_index=True)),
                ("purpose",        models.CharField(max_length=20, choices=[("membership","Membership"),("booking","Booking"),("other","Other")], default="membership")),
                ("reference_type", models.CharField(max_length=50, blank=True)),
                ("reference_id",   models.UUIDField(null=True, blank=True, db_index=True)),
                ("gateway",        models.CharField(max_length=20, choices=[("offline","Offline / Manual"),("razorpay","Razorpay"),("stripe","Stripe")], default="offline")),
                ("gateway_order_id",   models.CharField(max_length=200, blank=True)),
                ("gateway_payment_id", models.CharField(max_length=200, blank=True)),
                ("gateway_signature",  models.CharField(max_length=500, blank=True)),
                ("payment_method",     models.CharField(max_length=20, choices=[("cash","Cash"),("upi","UPI"),("bank_transfer","Bank Transfer"),("card","Card"),("online","Online")], null=True, blank=True)),
                ("payment_reference",  models.CharField(max_length=200, blank=True)),
                ("notes",              models.TextField(blank=True)),
                ("paid_at",            models.DateTimeField(null=True, blank=True)),
                ("tenant",    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(class)ss", to="core.tenant")),
                ("created_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_payments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "payments", "ordering": ["-created_at"]},
            managers=[("base_objects", django.db.models.manager.Manager())],
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["reference_type", "reference_id"], name="payments_ref_idx"),
        ),

        # PaymentEvent audit log
        migrations.CreateModel(
            name="PaymentEvent",
            fields=[
                ("id",         models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("event_type", models.CharField(max_length=50)),
                ("payload",    models.JSONField(default=dict)),
                ("payment",    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="payments.payment")),
            ],
            options={"db_table": "payment_events", "ordering": ["created_at"]},
        ),
    ]
