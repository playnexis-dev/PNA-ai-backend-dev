import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.auth.service import signup_user


class PublicSignupTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.auth.service._create_profile_for_role", new_callable=AsyncMock)
    @patch("app.auth.service._ensure_role_for_user", return_value="player")
    @patch("app.auth.service.supabase.auth.sign_up")
    async def test_email_confirmation_signup_returns_verification_success(
        self,
        sign_up: MagicMock,
        _ensure_role: MagicMock,
        create_profile: AsyncMock,
    ):
        user = SimpleNamespace(id="user-id", email="player@example.com")
        sign_up.return_value = SimpleNamespace(user=user, session=None)
        create_profile.return_value = {
            "user_id": user.id,
            "email": user.email,
            "full_name": "Player One",
            "phone": "9876543210",
        }

        response = await signup_user(
            user.email,
            "password123",
            "player",
            "Player One",
            "9876543210",
            None,
        )

        self.assertTrue(response["requires_email_verification"])
        self.assertIsNone(response["session"]["access_token"])
        self.assertIn("Verification email sent", response["message"])
        credentials = sign_up.call_args.args[0]
        self.assertEqual(credentials["options"]["data"]["role"], "player")
        self.assertIn("/auth/login?email_verified=1", credentials["options"]["email_redirect_to"])
        create_profile.assert_awaited_once()

    @patch("app.auth.service.supabase.auth.sign_up")
    async def test_public_owner_signup_is_rejected(self, sign_up: MagicMock):
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
        sign_up.assert_not_called()


if __name__ == "__main__":
    unittest.main()
