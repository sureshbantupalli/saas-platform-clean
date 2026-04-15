from django import forms
from .models import Member
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

        # ✅ Tenant-based branch filtering
        if tenant:
            self.fields["branches"].queryset = Branch.objects.filter(
                tenant=tenant,
                is_active=True
            )
        else:
            self.fields["branches"].queryset = Branch.objects.none()

        # ==============================
        # ✅ UI IMPROVEMENTS (Bootstrap)
        # ==============================

        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                "class": "form-control",
                "placeholder": f"Enter {field.label}"
            })

        # 🔥 Special handling for multi-select (branches)
        self.fields["branches"].widget.attrs.update({
            "class": "form-select",
            "multiple": True,
            "size": "4"   # better UX (shows 4 rows)
        })

    # ==============================
    # ✅ VALIDATION
    # ==============================

    def clean_branches(self):
        branches = self.cleaned_data.get("branches")

        if not branches or branches.count() == 0:
            raise forms.ValidationError(
                "Member must belong to at least one branch."
            )

        return branches