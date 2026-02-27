# ==========================================
# Permission Definition Registry
# ==========================================
"""
Defines all module-action pairs that must exist
inside the PermissionAction table.

This file is the single source of truth
for permission definitions.
"""

PERMISSION_DEFINITIONS = {
    "student": [
        "create",
        "view",
        "update",
        "delete",
    ],
    "course": [
        "create",
        "view",
        "update",
        "delete",
    ],
    "attendance": [
        "mark",
        "view",
    ],
    "member": ["create", "view", "update", "delete"],
}