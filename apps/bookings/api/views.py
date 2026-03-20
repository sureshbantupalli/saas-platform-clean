from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.bookings.api.serializers import (
    CreateBookingSerializer,
    BulkAttendanceSerializer,
)
from apps.bookings.services.booking_service import (
    create_booking,
    mark_bulk_attendance,
)


# ==========================================
# CREATE BOOKING API (SECURED)
# ==========================================
class CreateBookingAPIView(APIView):

    def post(self, request):

        tenant = getattr(request, "tenant", None)

        if tenant is None:
            return Response({
                "error": "Tenant context missing"
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreateBookingSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            booking = create_booking(
                tenant=tenant,
                data=serializer.validated_data
            )

            return Response({
                "message": "Booking created successfully",
                "booking_id": str(booking.id),
                "status": booking.status
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


# ==========================================
# BULK ATTENDANCE API (SECURED)
# ==========================================
class BulkAttendanceAPIView(APIView):

    def post(self, request):

        tenant = getattr(request, "tenant", None)

        if tenant is None:
            return Response({
                "error": "Tenant context missing"
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = BulkAttendanceSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            mark_bulk_attendance(
                tenant=tenant,
                booking_ids=serializer.validated_data["booking_ids"],
                status=serializer.validated_data["status"]
            )

            return Response({
                "message": "Attendance marked successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


# ==========================================
# CONFIRM BOOKING (PLACEHOLDER)
# ==========================================
class ConfirmBookingAPI(APIView):

    def post(self, request, booking_id):
        return Response({
            "message": "Confirm booking - coming soon"
        })


# ==========================================
# LIST BOOKINGS (SECURED)
# ==========================================
class ListBookingsAPI(APIView):

    def get(self, request):

        tenant = getattr(request, "tenant", None)

        if tenant is None:
            return Response({
                "error": "Tenant context missing"
            }, status=status.HTTP_400_BAD_REQUEST)

        from apps.bookings.models import Booking

        bookings = Booking.objects.filter(tenant=tenant)

        data = [
            {
                "id": str(b.id),
                "member_id": str(b.user_id),
                "schedule_id": str(b.session_id),
                "status": b.status,
                "date": str(b.booking_date),
            }
            for b in bookings
        ]

        return Response(data, status=status.HTTP_200_OK)