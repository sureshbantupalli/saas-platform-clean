from apps.core.models import DemoRecord
from apps.core.services.base_service import BaseService


# Initialize reusable service
service = BaseTenantService(
    module_key="demo_record",
    model_class=DemoRecord
)


# ==================================
# VIEW
# ==================================
def get_demo_records(user):
    service.check(user, "view")
    return service.get_queryset(user)


# ==================================
# CREATE
# ==================================
def create_demo_record(user, title, description=""):
    service.check(user, "create")

    record = DemoRecord(
        tenant=user.tenant,
        title=title,
        description=description,
        created_by=user
    )

    record.save()
    return record


# ==================================
# UPDATE
# ==================================
def update_demo_record(user, record_id, **kwargs):
    service.check(user, "update")

    record = service.get_object(user, record_id, action="update")

    for field, value in kwargs.items():
        setattr(record, field, value)

    record.save()
    return record


# ==================================
# DELETE
# ==================================
def delete_demo_record(user, record_id):
    service.check(user, "delete")

    record = service.get_object(user, record_id, action="delete")

    record.delete()
    return True