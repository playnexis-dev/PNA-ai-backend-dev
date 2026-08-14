import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.admin.service import set_arena_management
from app.arena.service import _sanitize_public_arena
from app.core.auth_context import AuthContext, require_role


class AdminRoleSecurityTests(unittest.TestCase):
    def admin_context(self, status="active"):
        return AuthContext(
            access_token="test-token",
            user=SimpleNamespace(id="admin-user", email="admin@playnexis.test"),
            role="admin",
            profile={"id": "admin-profile", "status": status},
        )

    def test_active_admin_role_is_distinct_from_owner(self):
        context = self.admin_context()
        self.assertEqual(require_role(context, "admin")["id"], "admin-profile")
        with self.assertRaises(HTTPException):
            require_role(context, "owner")

    def test_management_mode_is_not_exposed_publicly(self):
        public = _sanitize_public_arena({
            "id": "arena-id",
            "management_mode": "admin",
            "metadata": {"contact_number": "9876543210"},
        })
        self.assertNotIn("management_mode", public)
        self.assertEqual(public["metadata"]["contact_number_masked"], "9876******")

    def test_owner_cannot_change_arena_management_mode(self):
        context = AuthContext(
            access_token="token",
            user=SimpleNamespace(id="owner-user"),
            role="owner",
            profile={"id": "owner-profile"},
        )

        with self.assertRaises(HTTPException) as raised:
            set_arena_management(context, "arena-id", "admin")

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
