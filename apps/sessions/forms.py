from django import forms
from .models import SessionTemplate


class SessionTemplateForm(forms.ModelForm):

    class Meta:
        model = SessionTemplate

        fields = [
            "name",
            "session_type",
            "capacity",
            "is_active",
        ]