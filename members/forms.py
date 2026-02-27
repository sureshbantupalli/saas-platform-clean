from django import forms
from .models import Member
from apps.core.tenant_context import get_current_tenant
from apps.core.models import Branch


class MemberForm(forms.ModelForm):

    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "branches",
        ]

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields["branches"].queryset = Branch.objects.filter(
                tenant=tenant,
                is_active=True
            )
        else:
            self.fields["branches"].queryset = Branch.objects.none()

    def clean_branches(self):
        branches = self.cleaned_data.get("branches")

        if not branches or branches.count() == 0:
            raise forms.ValidationError(
                "Active member must belong to at least one branch."
            )

        return branches