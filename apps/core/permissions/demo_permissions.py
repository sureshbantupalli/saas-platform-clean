from apps.core.permissions.base import DatabasePermission
from apps.core.permissions.registry import register_permission


class DemoRecordPermission(DatabasePermission):
    pass


register_permission("demo_record", DemoRecordPermission)