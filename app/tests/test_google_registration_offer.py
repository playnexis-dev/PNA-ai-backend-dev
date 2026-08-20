import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.auth.service import (
    GOOGLE_ACCOUNT_NOT_REGISTERED_MESSAGE,
    complete_google_code,
)


class GoogleRegistrationOfferTests(unittest.IsolatedAsyncioTestCase):
    def _auth_response(self):
        return SimpleNamespace(
            user=SimpleNamespace(id="google-user", email="new@example.com"),
            session=SimpleNamespace(
                access_token="access-token",
                refresh_token="refresh-token",
            ),
        )

    @patch("app.auth.service._get_profile_for_role", return_value=None)
    @patch("app.auth.service._get_role_for_user", return_value=None)
    @patch("app.auth.service.supabase.auth.exchange_code_for_session")
    @patch("app.auth.service._read_google_oauth_ticket")
    async def test_unregistered_google_login_returns_registration_offer_error(
        self,
        read_ticket: MagicMock,
        exchange_code: MagicMock,
        _get_role: MagicMock,
        get_profile: MagicMock,
    ):
        read_ticket.return_value = {
            "intent": "login",
            "role": None,
            "code_verifier": "verifier",
        }
        exchange_code.return_value = self._auth_response()

        with self.assertRaises(HTTPException) as raised:
            await complete_google_code("authorization-code", "oauth-ticket")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, GOOGLE_ACCOUNT_NOT_REGISTERED_MESSAGE)
        self.assertEqual(get_profile.call_count, 3)

    @patch("app.auth.service._get_profile_for_role")
    @patch("app.auth.service._get_role_for_user", return_value=None)
    @patch("app.auth.service.supabase.auth.exchange_code_for_session")
    @patch("app.auth.service._read_google_oauth_ticket")
    async def test_orphaned_profile_remains_incomplete_instead_of_offering_signup(
        self,
        read_ticket: MagicMock,
        exchange_code: MagicMock,
        _get_role: MagicMock,
        get_profile: MagicMock,
    ):
        read_ticket.return_value = {
            "intent": "login",
            "role": None,
            "code_verifier": "verifier",
        }
        exchange_code.return_value = self._auth_response()
        get_profile.side_effect = [{"user_id": "google-user"}, None, None]

        with self.assertRaises(HTTPException) as raised:
            await complete_google_code("authorization-code", "oauth-ticket")

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "Account setup is incomplete")


if __name__ == "__main__":
    unittest.main()
