from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Attendance
from .serializers import AttendanceSerializer
from apps.members.models import Member

class MarkAttendanceAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        tenant = user.tenant

        member_id = request.data.get("member_id")
        session_type = request.data.get("session_type")

        try:
            member = Member.objects.get(id=member_id, tenant=tenant)
        except Member.DoesNotExist:
            return Response({"error": "Member not found"}, status=404)

        attendance = Attendance.objects.create(
            tenant=tenant,
            member=member,
            session_type=session_type
        )

        return Response({
            "message": "Attendance marked",
            "id": attendance.id
        })