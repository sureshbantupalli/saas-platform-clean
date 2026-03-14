from datetime import date

from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget
from apps.sessions.models import SessionInstance


@register_widget
class TodaySessionsWidget(BaseWidget):
    """
    Dashboard widget showing today's sessions.
    """

    key = "today_sessions"
    title = "Today's Sessions"

    def get_data(self, tenant, branch=None):

        queryset = SessionInstance.objects.filter(
            tenant=tenant,
            session_date=date.today()
        )

        if branch:
            queryset = queryset.filter(branch=branch)

        count = queryset.count()

        return {
            "title": self.title,
            "count": count
        }