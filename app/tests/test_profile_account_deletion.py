import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.core.auth_context import AuthContext
from app.profile.schemas import AccountDeleteRequest
from app.profile.service import delete_current_account


class ProfileAccountDeletionTests(unittest.TestCase):
    def context(self, role="player"):
        return AuthContext(
            access_token="token",
            user=SimpleNamespace(id="user-id", email="player@example.com"),
            role=role,
            profile={"id": "profile-id"},
        )

    def test_only_players_can_use_self_service_deletion(self):
        with self.assertRaises(HTTPException) as raised:
            delete_current_account(
                self.context("owner"),
                AccountDeleteRequest(confirmation_email="player@example.com"),
            )

        self.assertEqual(raised.exception.status_code, 403)

    def test_confirmation_email_must_match_authenticated_user(self):
        with self.assertRaises(HTTPException) as raised:
            delete_current_account(
                self.context(),
                AccountDeleteRequest(confirmation_email="another@example.com"),
            )

        self.assertEqual(raised.exception.status_code, 400)

    @patch("app.profile.service.is_supabase_admin_configured", return_value=False)
    def test_secure_backend_configuration_is_required(self, _configured: MagicMock):
        with self.assertRaises(HTTPException) as raised:
            delete_current_account(
                self.context(),
                AccountDeleteRequest(confirmation_email="player@example.com"),
            )

        self.assertEqual(raised.exception.status_code, 503)

    @patch("app.profile.service.is_supabase_admin_configured", return_value=True)
    @patch("app.profile.service.get_supabase_admin_client")
    @patch("app.profile.service.get_supabase_client")
    def test_deletes_auth_user_when_no_active_bookings(
        self,
        get_client: MagicMock,
        get_admin_client: MagicMock,
        _configured: MagicMock,
    ):
        get_client.return_value.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = []

        result = delete_current_account(
            self.context(),
            AccountDeleteRequest(confirmation_email="PLAYER@example.com"),
        )

        self.assertEqual(result, {"deleted": True})
        get_admin_client.return_value.auth.admin.delete_user.assert_called_once_with(
            "user-id",
            should_soft_delete=True,
        )

    @patch("app.profile.service.is_supabase_admin_configured", return_value=True)
    @patch("app.booking.service.cancel_player_booking")
    @patch("app.profile.service.get_supabase_admin_client")
    @patch("app.profile.service.get_supabase_client")
    def test_active_bookings_are_cancelled_before_account_deletion(
        self,
        get_client: MagicMock,
        get_admin_client: MagicMock,
        cancel_booking: MagicMock,
        _configured: MagicMock,
    ):
        get_client.return_value.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
            {"id": "booking-id"}
        ]

        result = delete_current_account(
            self.context(),
            AccountDeleteRequest(confirmation_email="player@example.com"),
        )

        self.assertEqual(result, {"deleted": True})
        cancel_booking.assert_called_once_with(self.context(), "booking-id")
        get_admin_client.return_value.auth.admin.delete_user.assert_called_once_with(
            "user-id",
            should_soft_delete=True,
        )


if __name__ == "__main__":
    unittest.main()
