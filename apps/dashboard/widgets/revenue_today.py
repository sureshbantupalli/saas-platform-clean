from datetime import date

from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget
from apps.platform_sessions.models import Booking


@register_widget
class RevenueTodayWidget(BaseWidget):
    key = "revenue_today"
    name = "Today's Revenue"

    def get_data(self):
        today = date.today()

        # ⚠️ TEMP: Remove tenant filter until middleware is ready
        bookings = (
            Booking.objects
            .filter(
                created_at__date=today,
                status=Booking.STATUS_BOOKED
            )
            .select_related("session_instance__schedule__template__session_type")
        )

        total_revenue = 0

        for booking in bookings:
            price = 0

            # ✅ Safe traversal (no silent failure)
            if booking.session_instance and booking.session_instance.schedule:
                schedule = booking.session_instance.schedule

                if schedule.template and schedule.template.session_type:
                    price = schedule.template.session_type.price or 0

            total_revenue += price

        return {
            "date": str(today),
            "total_revenue": float(total_revenue),
            "total_bookings": bookings.count()
        }