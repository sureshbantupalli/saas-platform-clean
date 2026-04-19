import uuid
from django.db import models
from django.utils import timezone
from apps.core.models import TenantAwareModel, BaseModel


FIELD_TYPES = [
    ("text", "Short Text"),
    ("textarea", "Long Text"),
    ("number", "Number"),
    ("date", "Date"),
    ("select", "Dropdown"),
    ("multiselect", "Multi-Select"),
    ("radio", "Radio Buttons"),
    ("boolean", "Yes / No"),
    ("scale", "Rating Scale"),
]

ENTITY_TYPES = [
    ("lead", "Lead"),
    ("member", "Member"),
    ("generic", "Generic"),
]

FORM_STATUSES = [
    ("draft", "Draft"),
    ("active", "Active"),
    ("inactive", "Inactive"),
]


class IntakeForm(TenantAwareModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES, default="member")
    status = models.CharField(max_length=10, choices=FORM_STATUSES, default="draft", db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intake_forms"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_intake_form_name_per_tenant"
            )
        ]

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def is_draft(self):
        return self.status == "draft"

    def __str__(self):
        return self.name


class FormField(BaseModel):
    form = models.ForeignKey(IntakeForm, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=255)
    field_key = models.CharField(
        max_length=100,
        help_text="Snake_case identifier. Matches prefill map keys (name, phone, email, age, etc.)"
    )
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    placeholder = models.CharField(max_length=255, blank=True)
    help_text = models.CharField(max_length=500, blank=True)
    is_required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    # For select / multiselect / radio: [{"label": "...", "value": "..."}]
    options = models.JSONField(default=list, blank=True)
    # For scale: {"min": 1, "max": 5, "min_label": "Poor", "max_label": "Excellent"}
    scale_config = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "intake_form_fields"
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.form.name} / {self.label}"


class FormResponse(TenantAwareModel):
    form = models.ForeignKey(IntakeForm, on_delete=models.CASCADE, related_name="responses")
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    entity_id = models.UUIDField(help_text="UUID of the lead or member this response belongs to")
    # {"field_key": value, ...}
    data = models.JSONField(default=dict)
    submitted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intake_responses"
    )

    class Meta:
        db_table = "intake_form_responses"
        constraints = [
            models.UniqueConstraint(
                fields=["form", "entity_id"],
                name="unique_form_response_per_entity"
            )
        ]

    def __str__(self):
        return f"Response to {self.form.name} for {self.entity_type}:{self.entity_id}"
