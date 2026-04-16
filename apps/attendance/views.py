import json

from django.views.decorators.csrf import ensure_csrf_cookie
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from members.models import Member
from apps.bookings.models import Booking
from apps.memberships.models import Membership
from .models import Attendance
from .serializers import BulkAttendanceSerializer


# =====================================================
# ✅ UI PAGE
# =====================================================
@ensure_csrf_cookie
@login_required
def attendance_ui(request):
    return render(request, "attendance/attendance_ui.html")


# =====================================================
# 🔍 SEARCH MEMBERS
# =====================================================
@login_required
def search_members(request):
    query = request.GET.get("q", "")
    tenant = request.user.tenant

    members = Member.objects.filter(
        tenant=tenant
    ).filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(phone__icontains=query)
    ).order_by("first_name")[:10]

    data = []

    for m in members:
        membership = Membership.objects.filter(
            member=m,
            status="active"
        ).order_by("-start_date").first()

        if membership:
            plan_name = membership.plan.name
            remaining_sessions = membership.remaining_sessions
        else:
            plan_name = "No Active Plan"
            remaining_sessions = 0

        data.append({
            "id": str(m.id),
            "name": f"{m.first_name} {m.last_name}",
            "phone": m.phone,
            "plan": plan_name,
            "remaining_sessions": remaining_sessions
        })

    return JsonResponse(data, safe=False)


# =====================================================
# ✅ MARK ATTENDANCE (WALK-IN)
# =====================================================
@login_required
def mark_attendance_ui(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    try:
        body = json.loads(request.body)

        member_id = body.get("member_id")
        attendance_type = body.get("attendance_type", "walkin")

        tenant = request.user.tenant

        member = Member.objects.get(id=member_id, tenant=tenant)

        attendance = Attendance.objects.create(
            tenant=tenant,
            member=member,
            attendance_type=attendance_type,
            session_date=timezone.now().date(),
            check_in_time=timezone.now(),
            marked_by=request.user,
            status="present"
        )

        return JsonResponse({
            "message": "Attendance marked successfully",
            "id": str(attendance.id)
        })

    except Member.DoesNotExist:
        return JsonResponse({"error": "Member not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# =====================================================
# 📅 LIST BOOKINGS (SESSIONS)
# =====================================================
@login_required
def list_bookings(request):
    tenant = request.user.tenant

    bookings = Booking.objects.filter(
        tenant=tenant
    ).select_related("session")

    unique_sessions = {}

    for b in bookings:
        session = b.session

        if session.id not in unique_sessions:
            unique_sessions[session.id] = {
                "id": str(session.id),
                "name": str(session)
            }

    return JsonResponse(list(unique_sessions.values()), safe=False)

# =====================================================
# 👥 BOOKING DETAILS (MEMBERS IN SESSION)
# =====================================================
@login_required
def booking_detail(request, booking_id):
    tenant = request.user.tenant

    try:
        booking = Booking.objects.get(id=booking_id, tenant=tenant)
    except Booking.DoesNotExist:
        return JsonResponse({"error": "Booking not found"}, status=404)

    members = Member.objects.filter(id=booking.member_id)

    data = {
        "id": str(booking.id),
        "session": str(booking.session),
        "members": [
            {
                "id": str(m.id),
                "name": f"{m.first_name} {m.last_name}"
            }
            for m in members
        ]
    }

    return JsonResponse(data)


# =====================================================
# 🔥 BULK ATTENDANCE API (SESSION BASED)
# =====================================================
class BulkAttendanceAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BulkAttendanceSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data

        tenant = request.user.tenant
        booking_id = data.get("booking_id")
        session_date = data.get("session_date")
        attendance_type = data.get("attendance_type")
        attendances = data.get("attendances")

        try:
            booking = Booking.objects.get(id=booking_id, tenant=tenant)
        except Booking.DoesNotExist:
            return Response({"error": "Booking not found"}, status=404)

        created_records = []

        for item in attendances:
            member_id = item.get("member_id")
            status = item.get("status")

            try:
                member = Member.objects.get(id=member_id, tenant=tenant)
            except Member.DoesNotExist:
                continue

            attendance, created = Attendance.objects.get_or_create(
                tenant=tenant,
                member=member,
                booking=booking,
                session_date=session_date,
                defaults={
                    "attendance_type": attendance_type,
                    "status": status,
                    "marked_by": request.user,
                    "check_in_time": timezone.now() if status == "present" else None
                }
            )

            if not created:
                attendance.status = status
                attendance.marked_by = request.user
                if status == "present":
                    attendance.check_in_time = timezone.now()
                attendance.save()

            created_records.append(str(attendance.id))

        return Response({
            "message": "Bulk attendance processed",
            "count": len(created_records),
            "records": created_records
        })


# =====================================================
# 📊 ATTENDANCE LIST
# =====================================================
@login_required
def attendance_list(request):
    tenant = request.user.tenant

    records = Attendance.objects.filter(
        tenant=tenant
    ).order_by("-session_date")[:50]

    data = [
        {
            "id": str(a.id),
            "member": f"{a.member.first_name} {a.member.last_name}" if a.member else None,
            "date": a.session_date,
            "status": a.status,
            "type": a.attendance_type
        }
        for a in records
    ]

    return JsonResponse(data, safe=False)

from django.views.decorators.http import require_GET

@require_GET
@login_required
def get_session_members(request, session_id):
    tenant = request.user.tenant

    bookings = (
        Booking.objects
        .filter(tenant=tenant, session_id=session_id)
        .select_related("member")
    )

    members = [
        {"id": str(b.member.id), "name": f"{b.member.first_name} {b.member.last_name}"}
        for b in bookings
        if b.member is not None
    ]

    return JsonResponse({"members": members})