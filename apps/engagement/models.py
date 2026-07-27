from django.db import models


class AttemptStatus(models.TextChoices):
    SENT   = 'sent',   'Sent'
    FAILED = 'failed', 'Failed'


class RetryPriority(models.TextChoices):
    HIGH   = 'high',   'High'
    NORMAL = 'normal', 'Normal'
    LOW    = 'low',    'Low'


class MessageAttempt(models.Model):
    tenant            = models.ForeignKey('core.Tenant',    on_delete=models.CASCADE,  related_name='message_attempts')
    member            = models.ForeignKey('members.Member', on_delete=models.SET_NULL, null=True, blank=True, related_name='message_attempts')
    communication_log = models.ForeignKey('communications.CommunicationLog', on_delete=models.SET_NULL, null=True, blank=True, related_name='attempts')
    event_name        = models.CharField(max_length=100)
    channel           = models.CharField(max_length=20)
    status            = models.CharField(max_length=10, choices=AttemptStatus.choices)
    attempt_number    = models.PositiveIntegerField(default=1)
    sent_at           = models.DateTimeField(auto_now_add=True)
    # Failure intelligence: carrier errors, invalid addresses, template rejections, etc.
    error_code        = models.CharField(max_length=100, blank=True)
    error_message     = models.TextField(blank=True)

    class Meta:
        db_table = 'engagement_message_attempt'
        ordering = ['-sent_at']


class RetryRule(models.Model):
    event_name          = models.CharField(max_length=100)
    channel             = models.CharField(max_length=20)
    max_attempts        = models.PositiveSmallIntegerField(default=3)
    retry_delay_minutes = models.PositiveIntegerField(default=60)
    # Priority governs processing order: high rules run before normal before low.
    priority            = models.CharField(max_length=10, choices=RetryPriority.choices, default=RetryPriority.NORMAL)

    class Meta:
        db_table        = 'engagement_retry_rule'
        unique_together = [('event_name', 'channel')]
        ordering        = ['event_name', 'channel']

    def __str__(self):
        return (
            f"{self.event_name}/{self.channel} — "
            f"{self.max_attempts}x every {self.retry_delay_minutes}m [{self.priority}]"
        )


class MemberEngagementScore(models.Model):
    member               = models.OneToOneField('members.Member', on_delete=models.CASCADE, related_name='engagement_score')
    preferred_channel    = models.CharField(max_length=20, blank=True)
    success_count        = models.PositiveIntegerField(default=0)
    failure_count        = models.PositiveIntegerField(default=0)
    last_engaged_at      = models.DateTimeField(null=True, blank=True)
    # Recency signal: overrides preferred_channel when within RECENCY_THRESHOLD_DAYS.
    last_success_channel = models.CharField(max_length=20, blank=True)
    last_success_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'engagement_member_score'

    def __str__(self):
        return (
            f"{self.member_id} — pref={self.preferred_channel or 'none'} "
            f"recent={self.last_success_channel or 'none'} "
            f"ok={self.success_count} fail={self.failure_count}"
        )
