from datetime import timedelta
from django.utils import timezone
from apps.sessions.models import SessionInstance


def generate_sessions_for_schedule(schedule, days_ahead=90):

    start_date = schedule.start_date
    end_limit = timezone.now().date() + timedelta(days=days_ahead)

    if schedule.end_date:
        end_limit = min(end_limit, schedule.end_date)

    current_date = start_date
    created_sessions = []

    while current_date <= end_limit:

        if current_date.isoweekday() == schedule.day_of_week:

            capacity = (
                schedule.capacity_override
                if schedule.capacity_override
                else schedule.template.capacity
            )

            session, created = SessionInstance.objects.get_or_create(
                tenant=schedule.tenant,   # ⭐ IMPORTANT FIX
                schedule=schedule,
                session_date=current_date,
                start_time=schedule.start_time,
                defaults={
                    "capacity": capacity
                }
            )

            if created:
                created_sessions.append(session)

        current_date += timedelta(days=1)

    return created_sessions