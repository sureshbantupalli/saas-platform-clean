from rest_framework import serializers
from .models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = "__all__"

    def validate(self, data):
        attendance_type = data.get("attendance_type")
        member = data.get("member")
        staff = data.get("staff")
        booking = data.get("booking")
        session_code = data.get("session_code")

        # Session-based
        if attendance_type == "session":
            if not member or not booking:
                raise serializers.ValidationError(
                    "Session attendance requires member and booking"
                )

        # Walk-in
        if attendance_type == "walkin":
            if not member:
                raise serializers.ValidationError(
                    "Walk-in attendance requires member"
                )

        # Staff
        if attendance_type == "staff":
            if not staff:
                raise serializers.ValidationError(
                    "Staff attendance requires staff user"
                )

        # Online
        if attendance_type == "online":
            if not member or not session_code:
                raise serializers.ValidationError(
                    "Online attendance requires member and session_code"
                )

        return data

from rest_framework import serializers


class BulkAttendanceItemSerializer(serializers.Serializer):
    member_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["present", "absent", "no_show"])


class BulkAttendanceSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    session_date = serializers.DateField()
    attendance_type = serializers.ChoiceField(
        choices=["session", "walkin", "staff", "online"]
    )
    attendances = BulkAttendanceItemSerializer(many=True)