from apps.dashboard.widgets.base_widget import BaseWidget
from apps.dashboard.registry import register_widget


@register_widget
class PaymentStatusWidget(BaseWidget):
    key  = "payment_status"
    name = "Payment Status"

    def get_data(self):
        from apps.payments.services.payment_intelligence_service import get_payment_metrics
        if not self.tenant:
            return {
                'total_collected_last_30_days': 0,
                'total_pending':                0,
                'overdue_count':                0,
            }
        return get_payment_metrics(self.tenant)
