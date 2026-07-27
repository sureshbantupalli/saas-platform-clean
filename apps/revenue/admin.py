from django.contrib import admin

from .models import NudgeLog


@admin.register(NudgeLog)
class NudgeLogAdmin(admin.ModelAdmin):
    # ── Display ───────────────────────────────────────────────────────────────
    list_display  = ('fired_at', 'tenant', 'member', 'event_name', 'context_summary', 'risk_reason', 'due_date')
    list_filter   = ('event_name', 'fired_at')
    search_fields = ('member__first_name', 'member__last_name', 'member__email', 'payment_id')
    ordering      = ('-fired_at',)
    date_hierarchy = 'fired_at'

    readonly_fields = [f.name for f in NudgeLog._meta.get_fields() if hasattr(f, 'name')]

    # ── Computed columns ──────────────────────────────────────────────────────

    @admin.display(description='Tenant')
    def tenant(self, obj):
        return obj.member.tenant if obj.member_id else '—'

    @admin.display(description='Context')
    def context_summary(self, obj):
        if obj.payment_id:
            return f'Payment {str(obj.payment_id)[:8]}…'
        return 'Member-level'

    @admin.display(description='Risk reason')
    def risk_reason(self, obj):
        try:
            return obj.member.revenue_signal.risk_reason or '—'
        except Exception:
            return '—'

    # ── Ledger guard — no mutations allowed ───────────────────────────────────

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
