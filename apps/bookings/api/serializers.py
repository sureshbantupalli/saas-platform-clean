from rest_framework import serializers


# ✅ INPUT SERIALIZER (for create booking)
class CreateBookingSerializer(serializers.Serializer):
    member_id = serializers.UUIDField()
    schedule_id = serializers.UUIDField()


# ✅ RESPONSE SERIALIZER
class BookingResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    member_id = serializers.UUIDField()
    schedule_id = serializers.UUIDField()
    status = serializers.CharField()


# ✅ BULK ATTENDANCE
class BulkAttendanceSerializer(serializers.Serializer):
    booking_ids = serializers.ListField(
        child=serializers.UUIDField()
    )
    status = serializers.ChoiceField(
        choices=["PRESENT", "ABSENT", "CANCELLED"]
    )