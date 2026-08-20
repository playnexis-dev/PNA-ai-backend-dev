import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from supabase_auth.errors import AuthApiError

from app.auth.service import login_user, resend_signup_verification, signup_user


def auth_user(email="player@example.com"):
    return SimpleNamespace(
        id="user-id",
        email=email,
        user_metadata={"full_name": "Player One"},
        email_confirmed_at="2026-08-20T00:00:00+00:00",
    )


def auth_session():
    return SimpleNamespace(access_token="access-token", refresh_token="refresh-token")


class PublicSignupTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.auth.service._send_application_verification_email", new_callable=AsyncMock)
    @patch("app.auth.service._upsert_verification_record")
    @patch("app.auth.service._create_profile_for_role", new_callable=AsyncMock)
    @patch("app.auth.service._ensure_role_for_user", return_value="player")
    @patch("app.auth.service.supabase.auth.sign_in_with_password")
    @patch("app.auth.service.get_supabase_admin_client")
    async def test_signup_returns_session_and_pending_app_verification(
        self,
        admin_client: MagicMock,
        sign_in: MagicMock,
        _ensure_role: MagicMock,
        create_profile: AsyncMock,
        _upsert: MagicMock,
        send_email: AsyncMock,
    ):
        user = auth_user()
        session = auth_session()
        admin_client.return_value.auth.admin.create_user.return_value = SimpleNamespace(user=user)
        sign_in.return_value = SimpleNamespace(user=user, session=session)
        create_profile.return_value = {"user_id": user.id, "phone": "9876543210"}
        send_email.return_value = {
            "message": "Verification email sent",
            "resend_available_in_seconds": 60,
        }

        response = await signup_user(
            user.email,
            "password123",
            "player",
            "Player One",
            "9876543210",
            None,
        )

        self.assertEqual(response["session"]["access_token"], "access-token")
        self.assertFalse(response["email_verified"])
        self.assertTrue(response["requires_email_verification"])
        self.assertTrue(response["verification_email_sent"])
        admin_client.return_value.auth.admin.create_user.assert_called_once()
        _upsert.assert_called_once_with(
            user.id,
            user.email,
            verified=False,
            token_version=1,
        )

    @patch("app.auth.service.get_supabase_admin_client")
    async def test_public_owner_signup_is_rejected(self, admin_client: MagicMock):
        with self.assertRaises(HTTPException) as raised:
            await signup_user(
                "owner@example.com",
                "password123",
                "owner",
                "Owner",
                "9876543210",
                None,
            )
        self.assertEqual(raised.exception.status_code, 403)
        admin_client.assert_not_called()

    @patch("app.auth.service._email_verification_status", return_value=False)
    @patch("app.auth.service._get_profile_for_role", return_value={"phone": "9876543210"})
    @patch("app.auth.service._require_role_for_user", return_value="player")
    @patch("app.auth.service._upsert_verification_record")
    @patch("app.auth.service._confirm_auth_user_for_application_verification")
    @patch("app.auth.service._find_auth_user_by_email")
    @patch("app.auth.service.supabase.auth.sign_in_with_password")
    async def test_old_unconfirmed_user_can_login_and_verify_later(
        self,
        sign_in: MagicMock,
        find_user: MagicMock,
        confirm_user: MagicMock,
        upsert: MagicMock,
        _role: MagicMock,
        _profile: MagicMock,
        _status: MagicMock,
    ):
        user = auth_user()
        session = auth_session()
        sign_in.side_effect = [
            AuthApiError("Email not confirmed", 400, "email_not_confirmed"),
            SimpleNamespace(user=user, session=session),
        ]
        find_user.return_value = user

        response = await login_user(user.email, "password123")

        self.assertEqual(response["session"]["access_token"], "access-token")
        self.assertFalse(response["email_verified"])
        self.assertTrue(response["requires_email_verification"])
        confirm_user.assert_called_once_with(user)
        upsert.assert_called_once_with(user.id, user.email, verified=False)

    @patch("app.auth.service._send_application_verification_email", new_callable=AsyncMock)
    @patch("app.auth.service._find_auth_user_by_email")
    async def test_resend_uses_application_email_service(
        self,
        find_user: MagicMock,
        send_email: AsyncMock,
    ):
        user = auth_user()
        find_user.return_value = user
        send_email.return_value = {
            "message": "Verification email sent",
            "resend_available_in_seconds": 60,
        }

        response = await resend_signup_verification(user.email)

        send_email.assert_awaited_once_with(user.id, user.email)
        self.assertEqual(response["resend_available_in_seconds"], 60)

    @patch("app.auth.service._find_auth_user_by_email", return_value=None)
    async def test_resend_does_not_reveal_unknown_email(self, _find: MagicMock):
        response = await resend_signup_verification("unknown@example.com")
        self.assertIn("if the account exists", response["message"].lower())


if __name__ == "__main__":
    unittest.main()
