import time
import os
import traceback
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from apps.memberships.models import Membership
from apps.lifecycles.models import LifecycleRun


class Command(BaseCommand):
    help = "Synchronize membership database status with computed lifecycle intelligence"

    def handle(self, *args, **kwargs):

        start_time = time.time()
        log_path = os.path.join(settings.BASE_DIR, "lifecycle_log.txt")

        # Create observability record
        lifecycle_run = LifecycleRun.objects.create(
            status=LifecycleRun.Status.RUNNING,
            triggered_by=LifecycleRun.TriggerSource.SCHEDULER,
        )

        total_checked = 0
        total_updated = 0
        total_errors = 0

        try:
            with open(log_path, "a") as log_file:
                log_file.write(
                    f"\n--- Lifecycle Run: {datetime.now()} ---\n"
                )

                memberships = Membership._base_manager.select_related("tenant")

                total_checked = memberships.count()

                for membership in memberships:
                    previous_status = membership.status

                    try:
                        membership.sync_status_with_lifecycle()

                        if membership.status != previous_status:
                            membership.save(update_fields=["status"])
                            total_updated += 1

                            log_file.write(
                                f"Updated {membership.id}: "
                                f"{previous_status} → {membership.status}\n"
                            )

                    except Exception:
                        total_errors += 1
                        log_file.write(
                            f"Error processing membership {membership.id}\n"
                        )
                        log_file.write(traceback.format_exc())
                        log_file.write("\n")

                log_file.write(f"Total Checked: {total_checked}\n")
                log_file.write(f"Total Updated: {total_updated}\n")
                log_file.write(f"Total Errors: {total_errors}\n")

            lifecycle_run.status = (
                LifecycleRun.Status.PARTIAL
                if total_errors > 0
                else LifecycleRun.Status.SUCCESS
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Lifecycle sync complete. Checked: {total_checked}, Updated: {total_updated}"
                )
            )

        except Exception as e:

            lifecycle_run.status = LifecycleRun.Status.FAILED
            lifecycle_run.notes = str(e)
            total_errors += 1

            with open(log_path, "a") as log_file:
                log_file.write("ERROR OCCURRED DURING LIFECYCLE SYNC:\n")
                log_file.write(traceback.format_exc())
                log_file.write("\n")

            self.stderr.write(
                self.style.ERROR("Lifecycle sync failed. Check lifecycle_log.txt.")
            )

        finally:
            end_time = time.time()

            lifecycle_run.completed_at = timezone.now()
            lifecycle_run.duration_ms = int((end_time - start_time) * 1000)
            lifecycle_run.total_checked = total_checked
            lifecycle_run.total_updated = total_updated
            lifecycle_run.total_errors = total_errors

            lifecycle_run.save()