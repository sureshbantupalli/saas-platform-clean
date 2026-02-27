from apps.core.services.base_service import BaseService
from members.models import Member


class MemberService(BaseTenantService):

    def __init__(self):
        super().__init__(
            module_key="member",
            model_class=Member
        )

    # ----------------------------------
    # Create Member
    # ----------------------------------
    def create_member(self, user, data):

        # 1️⃣ Permission check
        self.check(user, "create")

        # 2️⃣ Create member inside tenant scope
        member = self.model_class.objects.create(
            tenant=user.tenant,
            created_by=user,
            **data
        )

        return member
    # ----------------------------------
    # List Members
    # ----------------------------------
    def list_members(self, user):

        # 1️⃣ Permission check
        self.check(user, "view")

        # 2️⃣ Return scoped queryset
        return self.get_queryset(user)

    # ----------------------------------
    # Update Member
    # ----------------------------------
    def update_member(self, user, member_id, data):

        # 1️⃣ Permission + Scope enforced via get_object
        member = self.get_object(user, member_id, action="update")

        # 2️⃣ Prevent changing tenant or created_by
        data.pop("tenant", None)
        data.pop("created_by", None)

        # 3️⃣ If branch provided → validate belongs to same tenant
        if "branch" in data:
            branch = data["branch"]

            if branch.tenant != user.tenant:
                raise PermissionDenied(
                    "Invalid branch for this tenant."
                )

        # 4️⃣ Update allowed fields
        for field, value in data.items():
            setattr(member, field, value)

        member.save()

        return member

    # ----------------------------------
    # Deactivate Member (Soft Delete)
    # ----------------------------------
    def deactivate_member(self, user, member_id):

        member = self.get_object(user, member_id, action="delete")

        member.is_active = False
        member.save()

        return member