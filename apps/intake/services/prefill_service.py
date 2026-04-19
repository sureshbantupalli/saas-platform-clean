"""
Maps field_key identifiers to entity attribute paths for prefilling intake forms.
"""

LEAD_MAP = {
    "name": "full_name",
    "phone": "phone",
    "email": "email",
    "notes": "notes",
}

MEMBER_MAP = {
    "name": lambda m: f"{m.first_name} {m.last_name}".strip(),
    "first_name": "first_name",
    "last_name": "last_name",
    "phone": "phone",
    "email": "email",
}


def _resolve(entity, spec):
    if callable(spec):
        return spec(entity)
    val = entity
    for part in spec.split("."):
        val = getattr(val, part, None)
        if val is None:
            return ""
    return val or ""


class PrefillService:

    @staticmethod
    def prefill_from_lead(form, lead):
        data = {}
        for field in form.fields.filter(is_deleted=False).order_by("order"):
            spec = LEAD_MAP.get(field.field_key)
            if spec:
                data[field.field_key] = _resolve(lead, spec)
        return data

    @staticmethod
    def prefill_from_member(form, member):
        data = {}
        for field in form.fields.filter(is_deleted=False).order_by("order"):
            spec = MEMBER_MAP.get(field.field_key)
            if spec:
                data[field.field_key] = _resolve(member, spec)
        return data
