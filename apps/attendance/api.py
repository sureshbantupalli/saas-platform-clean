from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils.dateparse import parse_date

from apps.platform_sessions.models import SessionInstance
from apps.attendance.services.attendance_service import bulk_mark_attendance
from apps.attendance.models import Attendance


# =========================================================
# BULK MARK ATTENDANCE API
# =========================================================
class BulkMarkAttendanceAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # ✅ Safe tenant extraction
        tenant = getattr(request.user, "tenant", None)

        if not tenant:
            return Response({"error": "Tenant not found for user"}, status=400)

        session_id = request.data.get("session_id")

        # 🔥 CRITICAL FIX — ensure string
        if not isinstance(session_id, str):
            session_id = str(session_id)
        member_ids = request.data.get("member_ids", [])

        # 🔥 Ensure all are strings
        member_ids = [str(mid) for mid in member_ids]

        # 🔴 Basic validation
        if not session_id:
            return Response({"error": "session_id is required"}, status=400)

        if not isinstance(member_ids, list) or not member_ids:
            return Response({"error": "member_ids must be a non-empty list"}, status=400)

        # 🔥 Ensure session_id is string
        session_id = str(session_id)

        # 🔥 IMPORTANT FIX — bypass tenant manager filtering
        session = SessionInstance._base_manager.filter(id=session_id).first()

        if not session:
            return Response({"error": "Session not found"}, status=404)

        # ⚠️ Strict tenant validation
        if session.tenant != tenant:
            return Response({"error": "Session does not belong to this tenant"}, status=403)

        # 🔥 Ensure all member_ids are strings
        member_ids = [str(mid) for mid in member_ids]

        result = bulk_mark_attendance(
            session=session,
            member_ids=member_ids,
            tenant=tenant
        )

        return Response(result)


# =========================================================
# ATTENDANCE HISTORY API
# =========================================================
class AttendanceHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request.user, "tenant", None)

        if not tenant:
            return Response({"error": "Tenant not found for user"}, status=400)

        member_id = request.query_params.get("member_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        attendances = Attendance.objects.filter(tenant=tenant)

        # 🔹 Filter by member
        if member_id:
            attendances = attendances.filter(member_id=str(member_id))

        # 🔥 SAFE DATE HANDLING (Fix for your error)
        if start_date and isinstance(start_date, str):
            parsed_start = parse_date(start_date)
            if parsed_start:
                attendances = attendances.filter(
                    session_date__gte=parsed_start
                )

        if end_date and isinstance(end_date, str):
            parsed_end = parse_date(end_date)
            if parsed_end:
                attendances = attendances.filter(
                    session_date__lte=parsed_end
                )

        # 🔹 Latest first
        attendances = attendances.order_by("-session_date", "-created_at")

        data = []

        for att in attendances:
            data.append({
                "id": str(att.id),

                # Member
                "member_id": str(att.member.id) if att.member else None,
                "member_name": str(att.member) if att.member else None,

                # Attendance info
                "attendance_type": att.attendance_type,
                "status": att.status,

                # Session info
                "session_date": att.session_date,
                "check_in_time": att.check_in_time,
                "session_code": att.session_code,

                # Optional: booking reference
                "booking_id": str(att.booking.id) if att.booking else None,
            })

        return Response({
            "count": len(data),
            "results": data
        })