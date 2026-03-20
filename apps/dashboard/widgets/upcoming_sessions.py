from django.utils import timezone
from datetime import timedelta

from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget
from apps.platform_sessions.models import SessionInstance


@register_widget
class UpcomingSessionsWidget(BaseWidget):
    key = "upcoming_sessions"
    name = "Upcoming Sessions"

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
            .select_related("schedule")   # ✅ Correct relation
            .prefetch_related("bookings")
            .order_by("start_time")
        )

        data = []

        for session in sessions:
            total_capacity = session.capacity

            booked_count = session.bookings.filter(status="booked").count()

            available_slots = total_capacity - booked_count

            # ✅ SAFE session name handling (no schema assumption)
            session_name = "Session"

            if hasattr(session.schedule, "name"):
                session_name = session.schedule.name
            elif hasattr(session.schedule, "session_template"):
                session_name = getattr(session.schedule.session_template, "name", "Session")

            data.append({
                "id": str(session.id),
                "session_name": session_name,
                "start_time": session.start_time,
                "capacity": total_capacity,
                "booked": booked_count,
                "available": available_slots,
            })

        return {
            "total_sessions": sessions.count(),
            "sessions": data
        }