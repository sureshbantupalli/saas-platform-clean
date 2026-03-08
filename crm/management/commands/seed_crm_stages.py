from django.core.management.base import BaseCommand
from apps.core.models import Tenant
from crm.models import LeadStage


class Command(BaseCommand):

    help = "Seed default CRM stages for all tenants"

    def handle(self, *args, **kwargs):

        stages = [
            ("New", False, False, 1),
            ("Contacted", False, False, 2),
            ("Demo Done", False, False, 3),
            ("Converted", True, False, 4),
            ("Lost", False, True, 5),
        ]

        for tenant in Tenant.objects.all():

            for name, system, order in stages:

                LeadStage.objects.get_or_create(
                    tenant=tenant,
                    name=name,
                    defaults={
                        "is_conversion_stage": is_conversion,
                        "is_loss_stage": is_loss,
                        "order": order
                    }
                )

        self.stdout.write(self.style.SUCCESS("CRM stages seeded successfully"))