from django.db import IntegrityError
from django.shortcuts import redirect, get_object_or_404
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.urls import reverse
from django.db.models import Count, Q
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.views import View
from .forms import EnquiryForm
from django.contrib import messages
	
from django.core.exceptions import ValidationError
from apps.core.models import Branch
from crm.services.enquiry_guard_service import ensure_enquiry_not_converted
from django.utils import timezone
from datetime import timedelta	
from django.http import JsonResponse
from .models import Enquiry, LeadStage, EnquiryActivity
from crm.services.enquiry_lifecycle_service import EnquiryLifecycleService
from datetime import datetime


# ============================================================
# CRM DASHBOARD VIEW
# ============================================================

class CRMdashboardView(LoginRequiredMixin, TemplateView):
    template_name = "crm/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        # =========================
        # KPI METRICS
        # =========================
        total_enquiries = qs.count()
        converted_count = qs.filter(converted_member__isnull=False).count()
        new_count = qs.filter(converted_member__isnull=True).count()

        conversion_rate = 0
        if total_enquiries > 0:
            conversion_rate = round((converted_count / total_enquiries) * 100, 2)

        # =========================
        # FUNNEL DATA
        # =========================
        stage_counts = [
            {
                "label": "New",
                "count": new_count,
                "percentage": round((new_count / total_enquiries) * 100, 2)
                if total_enquiries > 0 else 0,
            },
            {
                "label": "Converted",
                "count": converted_count,
                "percentage": round((converted_count / total_enquiries) * 100, 2)
                if total_enquiries > 0 else 0,
            },
        ]

        # =========================
        # RECENT ENQUIRIES
        # =========================
        recent_enquiries = qs.order_by("-created_at")[:5]

        today = timezone.localdate()

        # Overdue followups
        overdue_followups = qs.filter(
            next_followup_date__lt=today,
            converted_member__isnull=True
        ).order_by("next_followup_date")[:5]

        # Today's followups
        today_followups = qs.filter(
            next_followup_date=today,
            converted_member__isnull=True
        ).order_by("next_followup_date")[:5]

        # Upcoming followups
        upcoming_followups = qs.filter(
            next_followup_date__gt=today,
            converted_member__isnull=True
        ).order_by("next_followup_date")[:5]

        # Leads without followup scheduled
        no_followups = qs.filter(
            next_followup_date__isnull=True,
            converted_member__isnull=True
        ).order_by("-created_at")[:5]

        # =========================
        # 🚨 NEEDS ATTENTION ALERTS
        # =========================

        ignored_leads = qs.filter(
            next_followup_date__isnull=True,
            converted_member__isnull=True
        )

        aging_leads = qs.filter(
            created_at__date__lte=today - timedelta(days=7),
            converted_member__isnull=True
        )

        needs_attention = {
            "ignored_count": ignored_leads.count(),
            "aging_count": aging_leads.count(),
        }

        # =========================
        # STAFF PERFORMANCE
        # =========================
        staff_stats = (
            qs.filter(assigned_to__isnull=False)
            .values("assigned_to__id", "assigned_to__email")
            .annotate(
                total_assigned=Count("id"),
                converted_assigned=Count(
                    "id",
                    filter=Q(converted_member__isnull=False)
                ),
            )
        )

        staff_performance = []

        for staff in staff_stats:
            total_assigned = staff["total_assigned"]
            converted_assigned = staff["converted_assigned"]

            conversion_percent = 0
            if total_assigned > 0:
                conversion_percent = round(
                    (converted_assigned / total_assigned) * 100, 2
                )

            staff_performance.append({
                "display": staff["assigned_to__email"],
                "total": total_assigned,
                "converted": converted_assigned,
                "conversion_rate": conversion_percent,
            })

        context.update({
            "total_enquiries": total_enquiries,
            "new_count": new_count,
            "converted_count": converted_count,
            "conversion_rate": conversion_rate,
            "stage_counts": stage_counts,
            "recent_enquiries": recent_enquiries,
            "staff_performance": staff_performance,
            "overdue_followups": overdue_followups,
            "today_followups": today_followups,
            "upcoming_followups": upcoming_followups,
            "no_followups": no_followups,
            "needs_attention": needs_attention,  # NEW
        })

        return context

# ============================================================
# ENQUIRY LIST VIEW
# ============================================================

class EnquiryListView(LoginRequiredMixin, ListView):
    model = Enquiry
    template_name = "crm/enquiry_list.html"
    context_object_name = "enquiries"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        # Stage filtering
        stage = self.request.GET.get("stage")
        if stage == "converted":
            qs = qs.filter(converted_member__isnull=False)
        elif stage == "new":
            qs = qs.filter(converted_member__isnull=True)

        # Assigned filter
        assigned = self.request.GET.get("assigned")
        if assigned:
            qs = qs.filter(assigned_to__id=assigned)

        # Search
        search = self.request.GET.get("search")
        if search:
            qs = qs.filter(full_name__icontains=search)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["selected_stage"] = self.request.GET.get("stage", "")
        context["search_query"] = self.request.GET.get("search", "")

        # Provide staff list for filter dropdown

        User = get_user_model()

        if self.request.user.is_platform_admin:
            staff_users = User.objects.filter(
                role__name__icontains="staff"
            )
        else:
            staff_users = User.objects.filter(
                tenant=self.request.user.tenant,
                role__name__icontains="staff"
            )

        context["staff_users"] = staff_users

        return context

class EnquiryKanbanView(LoginRequiredMixin, TemplateView):

    template_name = "crm/enquiry_kanban.html"

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)

        user = self.request.user

        stages = []
        enquiries = Enquiry.objects.all()

        if not user.is_superuser and hasattr(user, "tenant"):
            enquiries = enquiries.filter(tenant=user.tenant)

        from crm.models import LeadStage

        tenant_stages = LeadStage.objects.filter(
            tenant=user.tenant,
            is_active=True,
            show_in_pipeline=True
        ).order_by("order")

        for stage in tenant_stages:

            stage_enquiries = list(
                enquiries.filter(
                    current_stage=stage,
                    converted_member__isnull=True
                )
            )

            # Sort by lead priority (highest first), then newest
            stage_enquiries.sort(
                key=lambda e: (e.lead_priority, e.created_at),
                reverse=True
            )

            stages.append({
                "stage": stage,
                "enquiries": stage_enquiries
            })

        context["stages"] = stages

        # Add today's date for follow-up highlighting
        context["today"] = timezone.localdate()

        today = timezone.localdate()

        today_followups = enquiries.filter(
            next_followup_date=today,
            converted_member__isnull=True
        )

        context["today_followups_count"] = today_followups.count()

        return context


# ============================================================
# ENQUIRY DETAIL VIEW
# ============================================================

class EnquiryDetailView(LoginRequiredMixin, DetailView):
    model = Enquiry
    template_name = "crm/enquiry_detail.html"
    context_object_name = "enquiry"

    def get_queryset(self):
        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        enquiry = self.get_object()
        user = self.request.user

        can_convert = False

        if (
            enquiry.current_stage
            and enquiry.current_stage.is_conversion_stage
            and not enquiry.converted_member
            and user.has_permission("CRM", "convert_enquiry")
        ):
            can_convert = True

        # =========================
        # Lead Activity Timeline
        # =========================
        activities = enquiry.activities.select_related(
            "performed_by"
        ).order_by("-created_at")

        context["can_convert"] = can_convert
        context["activities"] = activities
        
        from crm.models import LeadStage

        stages = LeadStage.objects.filter(
            tenant=self.request.user.tenant,
            is_active=True
        ).order_by("order")

        context["stages"] = stages

        return context

from django.views.generic import CreateView
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.shortcuts import redirect

from .models import Enquiry
from .forms import EnquiryForm
from apps.core.models import Branch

class EnquiryCreateView(LoginRequiredMixin, CreateView):
    model = Enquiry
    form_class = EnquiryForm
    template_name = "crm/enquiry_form.html"


    def dispatch(self, request, *args, **kwargs):

        if request.user.is_platform_admin:
            raise PermissionDenied("Platform admins cannot create enquiries.")

        if not request.user.has_permission("CRM", "manage_enquiries"):
            raise PermissionDenied("You do not have permission to create enquiries.")

        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):

        form = EnquiryForm(
            **self.get_form_kwargs(),
            tenant=self.request.user.tenant
        )

        # Restrict stages to tenant
        form.fields["current_stage"].queryset = (
            form.fields["current_stage"].queryset.filter(
                tenant=self.request.user.tenant
            )
        )

        # Restrict assigned_to to tenant users only
        User = get_user_model()

        form.fields["assigned_to"].queryset = User.objects.filter(
            tenant=self.request.user.tenant,
            is_active=True
        )

        return form

    def form_valid(self, form):

        enquiry = form.save(commit=False)

        # Assign tenant
        enquiry.tenant = self.request.user.tenant

        # Assign first branch of tenant
        branch = Branch.objects.filter(
            tenant=self.request.user.tenant
        ).first()

        if not branch:
            raise Exception("No branch configured for this tenant.")

        enquiry.branch = branch

        # Track acting user for activity logging
        enquiry._acting_user = self.request.user

        try:
            enquiry.save()

        except (IntegrityError, ValidationError):
            form.add_error(
                "phone",
                "An enquiry with this phone number already exists."
            )
            return self.form_invalid(form)

        # -------------------------------------------------
        # Soft Duplicate Email Warning
        # -------------------------------------------------

        duplicate = getattr(form, "duplicate_email_warning", None)

        if duplicate:
            messages.warning(
                self.request,
                f"Possible duplicate email detected. Existing lead: "
                f"{duplicate.full_name} ({duplicate.phone})"
            )

        messages.success(
            self.request,
            "Enquiry created successfully."
        )

        return redirect("crm:enquiry_list")

class EnquiryUpdateView(LoginRequiredMixin, UpdateView):
    model = Enquiry
    template_name = "crm/enquiry_form.html"
    form_class = EnquiryForm
    context_object_name = "enquiry"

    def get_queryset(self):
        user = self.request.user
        qs = Enquiry.objects.all()

        # Tenant isolation
        if not user.is_superuser and hasattr(user, "tenant"):
            qs = qs.filter(tenant=user.tenant)

        return qs

    def get_form(self, form_class=None):

        form = EnquiryForm(
            **self.get_form_kwargs(),
            tenant=self.request.user.tenant
        )

        # Restrict stages to tenant
        form.fields["current_stage"].queryset = (
            form.fields["current_stage"].queryset.filter(
                tenant=self.request.user.tenant
            )
        )

        # Restrict assigned_to to tenant users only
        User = get_user_model()

        form.fields["assigned_to"].queryset = User.objects.filter(
            tenant=self.request.user.tenant,
            is_active=True
        )

        return form

    def form_valid(self, form):

        enquiry = self.get_object()

        # 🔒 Lifecycle protection
        ensure_enquiry_not_converted(enquiry)

        form.instance._acting_user = self.request.user

        return super().form_valid(form)
    
    def get_success_url(self):
         return reverse("crm:enquiry_detail", kwargs={"pk": self.object.pk})

class AssignEnquiryView(LoginRequiredMixin, View):

    def post(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)

        # Tenant protection
        if not request.user.is_superuser and hasattr(request.user, "tenant"):
            if enquiry.tenant != request.user.tenant:
                return redirect("crm:enquiry_list")

        user_id = request.POST.get("assigned_to")

        if user_id:
            User = get_user_model()
            assigned_user = User.objects.filter(id=user_id).first()

            # Ensure same tenant
            if assigned_user:
                if request.user.is_superuser or (
                    hasattr(assigned_user, "tenant")
                    and assigned_user.tenant == enquiry.tenant
                ):
                    old_user = enquiry.assigned_to

                    enquiry.assigned_to = assigned_user
                    enquiry._acting_user = request.user
                    enquiry.save()

                    EnquiryActivity.objects.create(
                        tenant=enquiry.tenant,
                        enquiry=enquiry,
                        performed_by=request.user,
                        action_type="ASSIGNED",
                        old_value=old_user.email if old_user else None,
                        new_value=assigned_user.email
                    )

        return redirect(reverse("crm:enquiry_list"))

class CRMConvertEnquiryView(LoginRequiredMixin, View):

    def post(self, request, pk):

        enquiry = get_object_or_404(
            Enquiry,
            pk=pk,
            tenant=request.user.tenant
        )

        # 🔐 Permission check
        if not request.user.has_permission("CRM", "convert_enquiry"):
            messages.error(request, "You do not have permission to convert enquiries.")
            return redirect(reverse("crm:enquiry_detail", args=[pk]))

        # 🔒 Already converted?
        if enquiry.converted_member:
            messages.warning(request, "This enquiry is already converted.")
            return redirect(reverse("crm:enquiry_detail", args=[pk]))

        # 🔒 Must be conversion stage
        if not enquiry.current_stage or not enquiry.current_stage.is_conversion_stage:
            messages.error(request, "Enquiry must be in conversion stage.")
            return redirect(reverse("crm:enquiry_detail", args=[pk]))

        try:
            member = enquiry.convert_to_member(request.user)
            messages.success(request, "Enquiry successfully converted.")
            return redirect(reverse("members:member_detail", args=[member.pk]))

        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect(reverse("crm:enquiry_detail", args=[pk]))

        except IntegrityError:
            messages.error(request, "A member with this email already exists in this tenant.")
            return redirect(reverse("crm:enquiry_detail", args=[pk]))

class AddEnquiryNoteView(LoginRequiredMixin, View):

    def post(self, request, pk):

        enquiry = get_object_or_404(
            Enquiry,
            pk=pk,
            tenant=request.user.tenant
        )

        note = request.POST.get("note")

        if note:

            from crm.models import EnquiryActivity

            EnquiryActivity.objects.create(
                tenant=enquiry.tenant,
                enquiry=enquiry,
                performed_by=request.user,
                action_type="NOTE_ADDED",
                notes=note
            )

        return redirect("crm:enquiry_detail", pk=pk)

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


class UpdateEnquiryStageView(LoginRequiredMixin, View):

    def post(self, request):

        enquiry_id = request.POST.get("enquiry_id")
        stage_id = request.POST.get("stage_id")

        
        enquiry = get_object_or_404(
            Enquiry,
            pk=enquiry_id,
            tenant=request.user.tenant
        )

        

        if enquiry.converted_member:
            return JsonResponse({"status": "blocked"})

        stage = get_object_or_404(
            LeadStage,
            pk=stage_id,
            tenant=request.user.tenant
        )

        

        EnquiryLifecycleService.change_stage(
            enquiry=enquiry,
            new_stage=stage,
            user=request.user
        )

        enquiry.refresh_from_db()

        

        return JsonResponse({"status": "success"})


# ============================================================
# CHANGE STAGE (Dropdown Version)
# ============================================================

def change_enquiry_stage(request, enquiry_id):

    enquiry = get_object_or_404(
        Enquiry,
        id=enquiry_id,
        tenant=request.user.tenant
    )

    if request.method == "POST":

        stage_id = request.POST.get("stage_id")

        try:
            stage = LeadStage.objects.get(
                id=stage_id,
                tenant=request.user.tenant
            )

            EnquiryLifecycleService.change_stage(
                enquiry=enquiry,
                new_stage=stage,
                user=request.user
            )

            messages.success(request, "Lead stage updated successfully.")

        except LeadStage.DoesNotExist:
            messages.error(request, "Invalid stage selected.")

    return redirect("crm:enquiry_detail", pk=enquiry.id)

# ============================================================
# UPDATE FOLLOW-UP DATE
# ============================================================

def update_followup_date(request, enquiry_id):

    enquiry = get_object_or_404(
        Enquiry,
        id=enquiry_id,
        tenant=request.user.tenant
    )

    if request.method == "POST":

        date_str = request.POST.get("next_followup_date")

        followup_date = None

        if date_str:
            try:
                followup_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                messages.error(request, "Invalid follow-up date.")
                return redirect("crm:enquiry_detail", pk=enquiry.id)

        enquiry.next_followup_date = followup_date
        enquiry._acting_user = request.user
        enquiry.save()

        messages.success(
            request,
            f"Follow-up scheduled for {followup_date}"
        )

    return redirect("crm:enquiry_detail", pk=enquiry.id)

# ============================================================
# QUICK LOG CALL (KANBAN)
# ============================================================

def quick_log_call(request, enquiry_id):

    enquiry = get_object_or_404(
        Enquiry,
        id=enquiry_id,
        tenant=request.user.tenant
    )

    EnquiryLifecycleService.log_call(
        enquiry=enquiry,
        user=request.user,
        notes="Quick call logged from Kanban"
    )

    return JsonResponse({"status": "success"})


# ============================================================
# QUICK FOLLOWUP (KANBAN)
# ============================================================

def quick_schedule_followup(request, enquiry_id):

    enquiry = get_object_or_404(
        Enquiry,
        id=enquiry_id,
        tenant=request.user.tenant
    )

    date_str = request.POST.get("date")

    followup_date = None

    if date_str:
        try:
            followup_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({"status": "invalid_date"})

    EnquiryLifecycleService.schedule_followup(
        enquiry=enquiry,
        followup_date=followup_date,
        user=request.user,
        notes="Quick follow-up scheduled from Kanban"
    )

    return JsonResponse({"status": "success"})