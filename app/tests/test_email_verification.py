import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.auth.service import (
    _create_email_verification_token,
    _read_email_verification_token,
    confirm_application_email,
)
from app.core.auth_context import AuthContext, require_verified_email


class EmailVerificationTests(unittest.IsolatedAsyncioTestCase):
    def test_signed_verification_token_round_trip(self):
        token = _create_email_verification_token(
            "user-id",
            "Player@Example.com",
            4,
        )
        payload = _read_email_verification_token(token)
        self.assertEqual(payload["user_id"], "user-id")
        self.assertEqual(payload["email"], "player@example.com")
        self.assertEqual(payload["version"], 4)

    def test_unverified_context_is_rejected_for_sensitive_actions(self):
        context = AuthContext(
            access_token="token",
            user=SimpleNamespace(id="user-id"),
            role="player",
            profile={},
            email_verified=False,
        )
        with self.assertRaises(HTTPException) as raised:
            require_verified_email(context)
        self.assertEqual(raised.exception.status_code, 403)

    def test_verified_context_is_allowed(self):
        context = AuthContext(
            access_token="token",
            user=SimpleNamespace(id="user-id"),
            role="player",
            profile={},
            email_verified=True,
        )
        self.assertIs(require_verified_email(context), context)

    @patch("app.auth.service._upsert_verification_record")
    @patch("app.auth.service._verification_record")
    @patch("app.auth.service._read_email_verification_token")
    async def test_confirmation_marks_matching_current_token_verified(
        self,
        read_token,
        verification_record,
        upsert,
    ):
        read_token.return_value = {
            "user_id": "user-id",
            "email": "player@example.com",
            "version": 3,
        }
        verification_record.return_value = {
            "user_id": "user-id",
            "email": "player@example.com",
            "verified_at": None,
            "token_version": 3,
        }

        response = await confirm_application_email("signed-token")

        self.assertTrue(response["email_verified"])
        upsert.assert_called_once_with(
            "user-id",
            "player@example.com",
            verified=True,
            token_version=4,
        )
