# =============================
# Permission Registry
# =============================

_permission_registry = {}


def register_permission(module_key: str, permission_class):
    """
    Registers a permission class for a module.
    Example:
        register_permission("demo_record", DemoRecordPermission)
    """
    _permission_registry[module_key] = permission_class


def get_permission(module_key: str):
    """
    Returns an instance of the registered permission class.
    """
    permission_class = _permission_registry.get(module_key)

    if not permission_class:
        raise ValueError(f"No permission registered for module '{module_key}'")

    return permission_class()