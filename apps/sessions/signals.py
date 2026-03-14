from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.sessions.models import SessionSchedule
from apps.sessions.services.session_generator import generate_sessions_for_schedule


@receiver(post_save, sender=SessionSchedule)
def create_sessions_for_schedule(sender, instance, created, **kwargs):

    if instance.is_active:
        generate_sessions_for_schedule(instance)