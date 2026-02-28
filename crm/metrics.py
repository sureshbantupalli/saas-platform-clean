from django.db.models import Count
from .models import Enquiry

from django.utils import timezone
from datetime import timedelta
from .models import Enquiry


def get_stale_enquiries(tenant, days=3):
    cutoff_date = timezone.now().date() - timedelta(days=days)

    return Enquiry.objects.filter(
        tenant=tenant,
        current_stage__is_conversion_stage=False,
        current_stage__is_loss_stage=False,
        created_at__date__lte=cutoff_date,
    ).select_related("current_stage", "branch")

def get_crm_metrics(tenant):
    """
    Returns core CRM metrics for a tenant.
    """

    total_enquiries = Enquiry.objects.filter(
        tenant=tenant
    ).count()

    converted = Enquiry.objects.filter(
        tenant=tenant,
        converted_member__isnull=False
    ).count()

    lost = Enquiry.objects.filter(
        tenant=tenant,
        current_stage__is_loss_stage=True
    ).count()

    conversion_rate = 0
    if total_enquiries > 0:
        conversion_rate = round((converted / total_enquiries) * 100, 2)

    stage_breakdown = (
        Enquiry.objects
        .filter(tenant=tenant)
        .values("current_stage__name")
        .annotate(count=Count("id"))
        .order_by("current_stage__order")
    )

    branch_breakdown = (
        Enquiry.objects
        .filter(tenant=tenant)
        .values("branch__name")
        .annotate(count=Count("id"))
    )

    return {
        "total_enquiries": total_enquiries,
        "converted": converted,
        "lost": lost,
        "conversion_rate": conversion_rate,
        "stage_breakdown": list(stage_breakdown),
        "branch_breakdown": list(branch_breakdown),
    }

from django.db.models import Count, Q


def get_staff_performance(tenant):
    from .models import Enquiry

    return (
        Enquiry.objects
        .filter(tenant=tenant, assigned_to__isnull=False)
        .values("assigned_to__email")
        .annotate(
            total=Count("id"),
            converted=Count("id", filter=Q(current_stage__is_conversion_stage=True)),
        )
        .order_by("-converted")
    )

from .models import LeadStage
from django.db.models import Count


def get_stage_funnel(tenant):
    stages = (
        LeadStage.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("order")
    )

    funnel = []

    for stage in stages:
        count = stage.enquiries.count()
        funnel.append({
            "name": stage.name,
            "count": count,
            "is_conversion": stage.is_conversion_stage,
            "is_loss": stage.is_loss_stage,
        })

    return funnel