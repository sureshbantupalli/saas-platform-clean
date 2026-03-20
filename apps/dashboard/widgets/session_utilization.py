from django.utils import timezone
from datetime import timedelta

from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget
from apps.platform_sessions.models import SessionInstance


@register_widget
class SessionUtilizationWidget(BaseWidget):
    key = "session_utilization"
    name = "Session Utilization"

    def get_data(self):
        tenant = self.tenant

        now = timezone.now()
        next_24_hours = now + timedelta(hours=24)

        sessions = (
            SessionInstance.objects
            .filter(
                tenant=tenant,
                start_time__gte=now,
                start_time__lte=next_24_hours
            )
            .select_related("schedule")
            .prefetch_related("bookings")
        )

        session_data = []
        total_utilization = 0
        count = 0

        for session in sessions:
            capacity = session.capacity or 0
            booked = session.bookings.filter(status="booked").count()

            if capacity > 0:
                utilization = int((booked / capacity) * 100)
            else:
                utilization = 0

            total_utilization += utilization
            count += 1

            # Safe name
            session_name = "Session"
            if hasattr(session.schedule, "name"):
                session_name = session.schedule.name

            session_data.append({
                "session_name": session_name,
                "utilization": utilization,
                "booked": booked,
                "capacity": capacity,
            })

        avg_utilization = int(total_utilization / count) if count > 0 else 0

        return {
            "total_sessions": sessions.count(),
            "average_utilization": avg_utilization,
            "sessions": session_data
        }