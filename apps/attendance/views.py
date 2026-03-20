from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Attendance
from .serializers import AttendanceSerializer


class MarkAttendanceAPIView(APIView):

    def post(self, request):
        serializer = AttendanceSerializer(data=request.data)

        if serializer.is_valid():
            attendance = serializer.save()
            return Response(
                {
                    "message": "Attendance marked successfully",
                    "data": AttendanceSerializer(attendance).data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Attendance
from .serializers import BulkAttendanceSerializer
from members.models import Member
from apps.bookings.models import Booking


class BulkAttendanceAPIView(APIView):

    def post(self, request):
        serializer = BulkAttendanceSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        booking_id = serializer.validated_data["booking_id"]
        session_date = serializer.validated_data["session_date"]
        attendance_type = serializer.validated_data["attendance_type"]
        attendances_data = serializer.validated_data["attendances"]

        # Validate booking
        try:
            booking = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            return Response({"error": "Booking not found"}, status=404)

        results = []

        for item in attendances_data:
            member_id = item["member_id"]
            status_value = item["status"]

            try:
                member = Member.objects.get(id=member_id)
            except Member.DoesNotExist:
                results.append({
                    "member_id": str(member_id),
                    "error": "Member not found"
                })
                continue

            attendance, created = Attendance.objects.update_or_create(
                member=member,
                booking=booking,
                session_date=session_date,
                defaults={
                    "status": status_value,
                    "attendance_type": attendance_type,
                    "marked_by": request.user if request.user.is_authenticated else None
                }
            )

            results.append({
                "member_id": str(member_id),
                "status": attendance.status,
                "created": created
            })

        return Response({
            "booking_id": str(booking_id),
            "session_date": session_date,
            "results": results
        }, status=status.HTTP_200_OK)