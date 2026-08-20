import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.core.supabase as supabase_module


class SupabaseAuthKeyTests(unittest.TestCase):
    def test_public_client_prefers_anon_key_for_email_password_login(self):
        with patch.object(
            supabase_module,
            "settings",
            SimpleNamespace(
                SUPABASE_URL="https://example.supabase.co",
                SUPABASE_KEY="sb_secret_service_key",
                SUPABASE_ANON_KEY="sb_anon_test_key",
                SUPABASE_SERVICE_KEY="sb_secret_service_key",
            ),
        ):
            self.assertEqual(supabase_module.get_supabase_public_key(), "sb_anon_test_key")
            self.assertEqual(supabase_module.get_supabase_admin_key(), "sb_secret_service_key")

    def test_server_auth_client_supports_legacy_secret_key(self):
        with patch.object(
            supabase_module,
            "settings",
            SimpleNamespace(
                SUPABASE_URL="https://example.supabase.co",
                SUPABASE_KEY="sb_secret_service_key",
                SUPABASE_ANON_KEY=None,
                SUPABASE_SERVICE_KEY="sb_secret_service_key",
            ),
        ):
            self.assertEqual(
                supabase_module.get_supabase_public_key(allow_legacy_fallback=True),
                "sb_secret_service_key",
            )


if __name__ == "__main__":
    unittest.main()
