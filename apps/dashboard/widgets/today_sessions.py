from datetime import date

from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget
from apps.platform_sessions.models import SessionInstance


@register_widget
class TodaySessionsWidget(BaseWidget):
    """
    Dashboard widget showing today's sessions.
    """

    key = "today_sessions"
    name = "Today's Sessions"

    def get_data(self):
        tenant = self.tenant

        today = date.today()

        sessions = (
            SessionInstance.objects
            .filter(
                tenant=tenant,
                session_date=today   # ✅ FIXED
            )
            .select_related("schedule")
            .prefetch_related("bookings")
            .order_by("start_time")
        )

        data = []

        for session in sessions:
            booked = session.bookings.filter(status="booked").count()
            capacity = session.capacity or 0

            session_name = "Session"
            if hasattr(session.schedule, "name"):
                session_name = session.schedule.name

            data.append({
                "session_name": session_name,
                "session_date": session.session_date,
                "start_time": session.start_time,
                "booked": booked,
                "capacity": capacity,
            })

        return {
            "total_sessions": sessions.count(),
            "sessions": data
        }