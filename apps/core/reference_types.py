from django.db import models


class ReferenceType(models.TextChoices):
    MEMBERSHIP      = "membership",       "Membership"
    BOOKING         = "booking",          "Booking"
    CLASS_SESSION   = "class_session",    "Class Session"
    CONSULTATION    = "consultation",     "Consultation"
    THERAPY_SESSION = "therapy_session",  "Therapy Session"
    ENROLLMENT      = "enrollment",        "Enrollment"
    DOCUMENT        = "document",         "Document"
    OTHER           = "other",            "Other"
