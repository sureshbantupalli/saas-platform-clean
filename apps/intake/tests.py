"""
Intake Form System — end-to-end tests.

Covers:
  - Form lifecycle (draft → active → inactive)
  - Activation rules (≥1 field, one-active-per-tenant)
  - Form submission + validation + response storage
  - Duplicate submission (idempotent upsert)
  - Redirect flow: member → intake → membership selection
  - Workflow bypass when no active form exists
  - Edge cases: no fields, missing entity_id, non-active form submission blocked
"""

from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import User
from apps.authority.models import Role
from apps.core.models import Tenant, Branch
from members.models import Member

from apps.intake.models import IntakeForm, FormField, FormResponse
from apps.intake.services.form_service import FormService, FormLifecycleError
from apps.intake.services.prefill_service import PrefillService


# ══════════════════════════════════════════════════════════════
# Shared fixtures
# ══════════════════════════════════════════════════════════════

def make_tenant(name="TestGym"):
    return Tenant.objects.create(name=name, subdomain=name.lower().replace(" ", "-"))


def make_user(tenant, email="staff@test.com"):
    role = Role.objects.create(tenant=tenant, name="Manager")
    return User.objects.create_user(email=email, password="testpass123", tenant=tenant, role=role)


def make_member(tenant, user, first="Alice", last="Smith", email="alice@test.com"):
    return Member.objects.create(
        tenant=tenant, created_by=user,
        first_name=first, last_name=last, email=email, phone="9999999999"
    )


def make_form(tenant, name="Intake", entity_type="member", status="draft"):
    return IntakeForm.base_objects.create(
        tenant=tenant, name=name, entity_type=entity_type, status=status
    )


def add_text_field(form, label="Full Name", key="name", required=True):
    return FormField.objects.create(
        form=form, label=label, field_key=key,
        field_type="text", is_required=required, order=0
    )


def add_field(form, label, key, field_type="text", required=False, order=0, options=None):
    return FormField.objects.create(
        form=form, label=label, field_key=key, field_type=field_type,
        is_required=required, order=order, options=options or []
    )


# ══════════════════════════════════════════════════════════════
# 1. Form Lifecycle Tests
# ══════════════════════════════════════════════════════════════

class FormLifecycleTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)

    def test_new_form_starts_as_draft(self):
        form = make_form(self.tenant)
        self.assertEqual(form.status, "draft")
        self.assertTrue(form.is_draft)
        self.assertFalse(form.is_active)

    def test_cannot_activate_form_with_no_fields(self):
        form = make_form(self.tenant)
        with self.assertRaises(FormLifecycleError) as ctx:
            FormService.activate_form(form)
        self.assertIn("at least one field", str(ctx.exception))
        form.refresh_from_db()
        self.assertEqual(form.status, "draft")

    def test_can_activate_form_with_fields(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        form.refresh_from_db()
        self.assertEqual(form.status, "active")
        self.assertTrue(form.is_active)
        self.assertIsNotNone(form.published_at)

    def test_activating_second_form_deactivates_first(self):
        form_a = make_form(self.tenant, name="Form A")
        add_text_field(form_a, key="name_a")
        FormService.activate_form(form_a)

        form_b = make_form(self.tenant, name="Form B")
        add_text_field(form_b, key="name_b")
        FormService.activate_form(form_b)

        form_a.refresh_from_db()
        form_b.refresh_from_db()
        self.assertEqual(form_a.status, "inactive")
        self.assertEqual(form_b.status, "active")

    def test_only_one_active_form_per_tenant(self):
        # Activate on tenant_1 should not affect tenant_2's active form
        tenant2 = make_tenant("OtherGym")
        form_t1 = make_form(self.tenant, name="T1 Form")
        form_t2 = make_form(tenant2, name="T2 Form")
        add_text_field(form_t1, key="x")
        add_text_field(form_t2, key="y")

        FormService.activate_form(form_t1)
        FormService.activate_form(form_t2)

        form_t1.refresh_from_db()
        self.assertEqual(form_t1.status, "active")   # still active on its own tenant

    def test_deactivate_form(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        FormService.deactivate_form(form)
        form.refresh_from_db()
        self.assertEqual(form.status, "inactive")

    def test_reactivate_inactive_form(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        FormService.deactivate_form(form)
        FormService.activate_form(form)
        form.refresh_from_db()
        self.assertEqual(form.status, "active")


# ══════════════════════════════════════════════════════════════
# 2. FormService Query Tests
# ══════════════════════════════════════════════════════════════

class FormServiceQueryTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()

    def test_get_active_form_returns_active_form(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        result = FormService.get_active_form_for_entity(self.tenant, "member")
        self.assertEqual(result.pk, form.pk)

    def test_get_active_form_returns_none_when_none_active(self):
        make_form(self.tenant)   # draft, never activated
        result = FormService.get_active_form_for_entity(self.tenant, "member")
        self.assertIsNone(result)

    def test_get_active_form_filters_by_entity_type(self):
        # Only ONE form can be active per tenant at a time.
        # Activating member_form deactivates lead_form.
        lead_form = make_form(self.tenant, name="Lead Form", entity_type="lead")
        member_form = make_form(self.tenant, name="Member Form", entity_type="member")
        add_text_field(lead_form, key="lf")
        add_text_field(member_form, key="mf")

        FormService.activate_form(lead_form)   # lead active
        FormService.activate_form(member_form) # member active, lead deactivated

        # Only member_form is now active
        lead_result   = FormService.get_active_form_for_entity(self.tenant, "lead")
        member_result = FormService.get_active_form_for_entity(self.tenant, "member")

        self.assertIsNone(lead_result)                       # deactivated
        self.assertEqual(member_result.pk, member_form.pk)  # now active


# ══════════════════════════════════════════════════════════════
# 3. Form Submission Tests
# ══════════════════════════════════════════════════════════════

class FormSubmissionTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)
        self.member = make_member(self.tenant, self.user)
        self.form = make_form(self.tenant)
        add_field(self.form, "Full Name", "name", required=True)
        add_field(self.form, "Phone", "phone", required=False)
        add_field(self.form, "Age", "age", field_type="number", required=False)
        FormService.activate_form(self.form)

    def test_valid_submission_saves_response(self):
        data = {"name": "Alice Smith", "phone": "9999999999", "age": "30"}
        response, errors = FormService.submit_response(
            form=self.form,
            entity_type="member",
            entity_id=self.member.pk,
            data=data,
            submitted_by=self.user,
        )
        self.assertEqual(errors, {})
        self.assertIsNotNone(response)
        self.assertEqual(response.data["name"], "Alice Smith")
        self.assertEqual(str(response.entity_id), str(self.member.pk))

    def test_missing_required_field_returns_error(self):
        data = {"name": "", "phone": "9999999999"}  # name is required but empty
        response, errors = FormService.submit_response(
            form=self.form,
            entity_type="member",
            entity_id=self.member.pk,
            data=data,
        )
        self.assertIsNone(response)
        self.assertIn("name", errors)

    def test_submission_blocked_for_draft_form(self):
        draft_form = make_form(self.tenant, name="Draft Form")
        add_field(draft_form, "X", "x")
        # Do NOT activate — leave as draft
        data = {"x": "hello"}
        response, errors = FormService.submit_response(
            form=draft_form,
            entity_type="member",
            entity_id=self.member.pk,
            data=data,
        )
        self.assertIsNone(response)
        self.assertIn("__form__", errors)

    def test_submission_blocked_for_inactive_form(self):
        FormService.deactivate_form(self.form)
        data = {"name": "Alice"}
        response, errors = FormService.submit_response(
            form=self.form, entity_type="member", entity_id=self.member.pk, data=data
        )
        self.assertIsNone(response)
        self.assertIn("__form__", errors)

    def test_duplicate_submission_is_upserted_not_duplicated(self):
        data1 = {"name": "Alice", "phone": "111"}
        FormService.submit_response(
            form=self.form, entity_type="member",
            entity_id=self.member.pk, data=data1
        )
        data2 = {"name": "Alice Updated", "phone": "222"}
        FormService.submit_response(
            form=self.form, entity_type="member",
            entity_id=self.member.pk, data=data2
        )
        count = FormResponse.base_objects.filter(form=self.form, entity_id=self.member.pk).count()
        latest = FormResponse.base_objects.get(form=self.form, entity_id=self.member.pk)
        self.assertEqual(count, 1)
        self.assertEqual(latest.data["name"], "Alice Updated")

    def test_existing_response_retrievable(self):
        data = {"name": "Alice", "phone": "9999999999"}
        FormService.submit_response(
            form=self.form, entity_type="member",
            entity_id=self.member.pk, data=data
        )
        existing = FormService.get_existing_response(self.form, self.member.pk)
        self.assertIsNotNone(existing)
        self.assertEqual(existing.data["name"], "Alice")


# ══════════════════════════════════════════════════════════════
# 4. Prefill Tests
# ══════════════════════════════════════════════════════════════

class PrefillTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)
        self.member = make_member(self.tenant, self.user, first="Bob", last="Jones", email="bob@test.com")
        self.member.phone = "8888888888"
        self.member.save()

        self.form = make_form(self.tenant)
        add_field(self.form, "Full Name", "name")
        add_field(self.form, "First Name", "first_name")
        add_field(self.form, "Email", "email")
        add_field(self.form, "Phone", "phone")
        add_field(self.form, "Age", "age")  # no mapping → stays empty

    def test_prefill_from_member_maps_known_keys(self):
        data = PrefillService.prefill_from_member(self.form, self.member)
        self.assertEqual(data["name"], "Bob Jones")
        self.assertEqual(data["first_name"], "Bob")
        self.assertEqual(data["email"], "bob@test.com")
        self.assertEqual(data["phone"], "8888888888")
        # 'age' has no mapping — should not appear or be empty
        self.assertNotIn("age", data)


# ══════════════════════════════════════════════════════════════
# 5. HTTP View Tests (workflow + redirects)
# ══════════════════════════════════════════════════════════════

class FormRenderViewTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)
        self.member = make_member(self.tenant, self.user)
        self.client = Client()
        self.client.login(username="staff@test.com", password="testpass123")

        self.form = make_form(self.tenant, status="draft")
        add_field(self.form, "Full Name", "name", required=True)
        add_field(self.form, "Phone", "phone")

    def test_draft_form_shows_preview_banner_on_get(self):
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview mode")

    def test_active_form_renders_without_preview_banner(self):
        FormService.activate_form(self.form)
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Preview mode")

    def test_post_to_draft_form_redirects_to_builder(self):
        # Draft form should block submission and redirect to builder
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.post(url, {
            "name": "Alice", "phone": "999",
            "entity_type": "member", "entity_id": str(self.member.pk), "next": ""
        })
        self.assertRedirects(
            response,
            reverse("intake:form_builder_detail", args=[self.form.pk]),
            fetch_redirect_response=False
        )

    def test_valid_post_to_active_form_redirects_to_membership(self):
        FormService.activate_form(self.form)
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.post(url, {
            "name": "Alice Smith",
            "phone": "9999999999",
            "entity_type": "member",
            "entity_id": str(self.member.pk),
            "next": "",
        })
        expected = f"{reverse('membership_add')}?member={self.member.pk}"
        self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_valid_post_with_explicit_next_respects_it(self):
        FormService.activate_form(self.form)
        explicit_next = reverse("members:member_detail", args=[self.member.pk])
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.post(url, {
            "name": "Alice",
            "phone": "999",
            "entity_type": "member",
            "entity_id": str(self.member.pk),
            "next": explicit_next,
        })
        self.assertRedirects(response, explicit_next, fetch_redirect_response=False)

    def test_missing_required_field_rerenders_form_with_error(self):
        FormService.activate_form(self.form)
        url = reverse("intake:form_render", args=[self.form.pk])
        response = self.client.post(url, {
            "name": "",   # required but empty
            "phone": "",
            "entity_type": "member",
            "entity_id": str(self.member.pk),
            "next": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the following")

    def test_response_is_stored_after_valid_submission(self):
        FormService.activate_form(self.form)
        url = reverse("intake:form_render", args=[self.form.pk])
        self.client.post(url, {
            "name": "Alice Smith",
            "phone": "9999999999",
            "entity_type": "member",
            "entity_id": str(self.member.pk),
            "next": "",
        })
        response = FormResponse.base_objects.filter(
            form=self.form, entity_id=self.member.pk
        ).first()
        self.assertIsNotNone(response)
        self.assertEqual(response.data["name"], "Alice Smith")

    def test_prefill_appears_in_rendered_form(self):
        FormService.activate_form(self.form)
        url = (
            reverse("intake:form_render", args=[self.form.pk])
            + f"?entity_type=member&entity_id={self.member.pk}"
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Member's first+last name should be prefilled in the 'name' field
        self.assertContains(response, "Alice Smith")

    def test_cancel_button_points_to_member_detail_for_member_entity(self):
        FormService.activate_form(self.form)
        url = (
            reverse("intake:form_render", args=[self.form.pk])
            + f"?entity_type=member&entity_id={self.member.pk}"
        )
        response = self.client.get(url)
        expected_cancel = reverse("members:member_detail", args=[self.member.pk])
        self.assertContains(response, expected_cancel)


# ══════════════════════════════════════════════════════════════
# 6. Lifecycle HTTP Tests
# ══════════════════════════════════════════════════════════════

class FormLifecycleViewTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user(self.tenant)
        self.client = Client()
        self.client.login(username="staff@test.com", password="testpass123")

    def test_activate_with_no_fields_shows_error_message(self):
        form = make_form(self.tenant)
        url = reverse("intake:form_activate", args=[form.pk])
        response = self.client.post(url)
        self.assertRedirects(
            response,
            reverse("intake:form_builder_detail", args=[form.pk]),
            fetch_redirect_response=False
        )
        form.refresh_from_db()
        self.assertEqual(form.status, "draft")   # still draft

    def test_activate_with_fields_succeeds(self):
        form = make_form(self.tenant)
        add_text_field(form)
        url = reverse("intake:form_activate", args=[form.pk])
        self.client.post(url)
        form.refresh_from_db()
        self.assertEqual(form.status, "active")

    def test_deactivate_sets_status_inactive(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        url = reverse("intake:form_deactivate", args=[form.pk])
        self.client.post(url)
        form.refresh_from_db()
        self.assertEqual(form.status, "inactive")

    def test_activating_sets_published_at(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        form.refresh_from_db()
        self.assertIsNotNone(form.published_at)


# ══════════════════════════════════════════════════════════════
# 7. Workflow Bypass — No active form
# ══════════════════════════════════════════════════════════════

class WorkflowBypassTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant()

    def test_get_active_form_returns_none_when_all_deactivated(self):
        form = make_form(self.tenant)
        add_text_field(form)
        FormService.activate_form(form)
        FormService.deactivate_form(form)
        result = FormService.get_active_form_for_entity(self.tenant, "member")
        self.assertIsNone(result)

    def test_get_active_form_returns_none_for_different_entity_type(self):
        form = make_form(self.tenant, entity_type="lead")
        add_text_field(form)
        FormService.activate_form(form)
        # Query for "member" — should return None since only "lead" form is active
        result = FormService.get_active_form_for_entity(self.tenant, "member")
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════════
# 8. Template Filter Unit Tests
# ══════════════════════════════════════════════════════════════

class TemplateFilterTests(TestCase):

    def test_get_item_returns_value(self):
        from apps.intake.templatetags.intake_extras import get_item
        d = {"name": "Alice", "age": 30}
        self.assertEqual(get_item(d, "name"), "Alice")
        self.assertEqual(get_item(d, "age"), 30)

    def test_get_item_returns_empty_for_missing_key(self):
        from apps.intake.templatetags.intake_extras import get_item
        self.assertEqual(get_item({"a": 1}, "missing"), "")

    def test_get_item_returns_empty_for_non_dict(self):
        from apps.intake.templatetags.intake_extras import get_item
        self.assertEqual(get_item(None, "key"), "")
        self.assertEqual(get_item("string", "key"), "")

    def test_value_in_returns_true_for_list(self):
        from apps.intake.templatetags.intake_extras import value_in
        self.assertTrue(value_in("yoga", ["yoga", "pilates"]))
        self.assertFalse(value_in("crossfit", ["yoga", "pilates"]))

    def test_value_in_handles_empty(self):
        from apps.intake.templatetags.intake_extras import value_in
        self.assertFalse(value_in("yoga", None))
        self.assertFalse(value_in("yoga", []))
