from django.db.models import Count, Sum, Q

from apps.sessions.models import SessionInstance, Attendance


def get_session_utilization_basic():
    """
    Returns session utilization metrics grouped by session template
    """

    data = (
        SessionInstance.objects
        .values("schedule__template__name")
        .annotate(
            total_sessions=Count("id"),
            total_capacity=Sum("capacity"),

            total_bookings=Count("bookings"),

            attended=Count(
                "attendances",
                filter=Q(attendances__status=Attendance.STATUS_PRESENT)
            ),

            no_show=Count(
                "attendances",
                filter=Q(attendances__status=Attendance.STATUS_ABSENT)
            ),
        )
    )

    results = []

    for row in data:

        capacity = row["total_capacity"] or 0
        bookings = row["total_bookings"] or 0
        attended = row["attended"] or 0
        no_show = row["no_show"] or 0

        utilization_percent = 0
        attendance_rate = 0
        no_show_rate = 0

        if capacity > 0:
            utilization_percent = (bookings / capacity) * 100

        if bookings > 0:
            attendance_rate = (attended / bookings) * 100
            no_show_rate = (no_show / bookings) * 100

        row["utilization_percent"] = round(utilization_percent, 2)
        row["attendance_rate"] = round(attendance_rate, 2)
        row["no_show_rate"] = round(no_show_rate, 2)

        results.append(row)

    return results


def get_tenant_session_dashboard():
    """
    Returns overall tenant session analytics
    """

    data = SessionInstance.objects.aggregate(

        total_sessions=Count("id"),

        total_capacity=Sum("capacity"),

        total_bookings=Count("bookings"),

        attended=Count(
            "attendances",
            filter=Q(attendances__status=Attendance.STATUS_PRESENT)
        ),

        no_show=Count(
            "attendances",
            filter=Q(attendances__status=Attendance.STATUS_ABSENT)
        ),
    )

    capacity = data["total_capacity"] or 0
    bookings = data["total_bookings"] or 0
    attended = data["attended"] or 0
    no_show = data["no_show"] or 0

    utilization_percent = 0
    attendance_rate = 0
    no_show_rate = 0

    if capacity > 0:
        utilization_percent = (bookings / capacity) * 100

    if bookings > 0:
        attendance_rate = (attended / bookings) * 100
        no_show_rate = (no_show / bookings) * 100

    data["utilization_percent"] = round(utilization_percent, 2)
    data["attendance_rate"] = round(attendance_rate, 2)
    data["no_show_rate"] = round(no_show_rate, 2)

    return data

def get_session_performance_dashboard():

    data = (
        SessionInstance.objects
        .values("schedule__template__name")
        .annotate(
            total_sessions=Count("id"),
            total_capacity=Sum("capacity"),
            total_bookings=Count("bookings"),
        )
    )

    results = []

    for row in data:

        capacity = row["total_capacity"] or 0
        bookings = row["total_bookings"] or 0

        utilization_percent = 0

        if capacity > 0:
            utilization_percent = (bookings / capacity) * 100

        results.append({
            "session_name": row["schedule__template__name"],
            "total_sessions": row["total_sessions"],
            "capacity": capacity,
            "bookings": bookings,
            "utilization_percent": round(utilization_percent, 2),
        })

    return results

def get_peak_day_demand():

    data = (
        SessionInstance.objects
        .values("schedule__day_of_week")
        .annotate(
            total_sessions=Count("id"),
            total_capacity=Sum("capacity"),
            total_bookings=Count("bookings")
        )
    )

    results = []

    for row in data:

        capacity = row["total_capacity"] or 0
        bookings = row["total_bookings"] or 0

        utilization_percent = 0

        if capacity > 0:
            utilization_percent = (bookings / capacity) * 100

        results.append({
            "day_of_week": row["schedule__day_of_week"],
            "total_sessions": row["total_sessions"],
            "capacity": capacity,
            "bookings": bookings,
            "utilization_percent": round(utilization_percent, 2),
        })

    return results

def get_peak_time_demand():

    data = (
        SessionInstance.objects
        .values("start_time")
        .annotate(
            total_sessions=Count("id"),
            total_capacity=Sum("capacity"),
            total_bookings=Count("bookings")
        )
        .order_by("start_time")
    )

    results = []

    for row in data:

        capacity = row["total_capacity"] or 0
        bookings = row["total_bookings"] or 0

        utilization_percent = 0

        if capacity > 0:
            utilization_percent = (bookings / capacity) * 100

        results.append({
            "start_time": row["start_time"],
            "total_sessions": row["total_sessions"],
            "capacity": capacity,
            "bookings": bookings,
            "utilization_percent": round(utilization_percent, 2),
        })

    return results

def get_underutilized_sessions(threshold=30):

    data = (
        SessionInstance.objects
        .values(
            "schedule__template__name",
            "session_date",
            "start_time"
        )
        .annotate(
            capacity=Sum("capacity"),
            bookings=Count("bookings")
        )
    )

    results = []

    for row in data:

        capacity = row["capacity"] or 0
        bookings = row["bookings"] or 0

        utilization_percent = 0

        if capacity > 0:
            utilization_percent = (bookings / capacity) * 100

        if utilization_percent < threshold:

            results.append({
                "session_name": row["schedule__template__name"],
                "session_date": row["session_date"],
                "start_time": row["start_time"],
                "capacity": capacity,
                "bookings": bookings,
                "utilization_percent": round(utilization_percent, 2),
            })

    return results

def get_schedule_optimization_suggestions():

    # Demand by time
    demand_data = (
        SessionInstance.objects
        .values("start_time")
        .annotate(
            capacity=Sum("capacity"),
            bookings=Count("bookings")
        )
    )

    demand_map = {}

    for row in demand_data:

        capacity = row["capacity"] or 0
        bookings = row["bookings"] or 0

        utilization = 0

        if capacity > 0:
            utilization = (bookings / capacity) * 100

        demand_map[row["start_time"]] = utilization

    # Detect low-performing sessions
    sessions = (
        SessionInstance.objects
        .values(
            "schedule__template__name",
            "session_date",
            "start_time"
        )
        .annotate(
            capacity=Sum("capacity"),
            bookings=Count("bookings")
        )
    )

    suggestions = []

    for row in sessions:

        capacity = row["capacity"] or 0
        bookings = row["bookings"] or 0

        utilization = 0

        if capacity > 0:
            utilization = (bookings / capacity) * 100

        if utilization < 30:

            best_time = None
            best_demand = 0

            for time, demand in demand_map.items():

                if demand > best_demand:
                    best_demand = demand
                    best_time = time

            suggestions.append({

                "session_name": row["schedule__template__name"],
                "session_date": row["session_date"],
                "current_time": row["start_time"],
                "current_utilization": round(utilization, 2),

                "suggested_time": best_time,
                "expected_utilization": round(best_demand, 2),

            })

    return suggestions