import unittest

from app.core.config import Settings


class ApplicationUrlSettingsTests(unittest.TestCase):
    def build_settings(self, **overrides):
        values = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "test-key",
            "JWT_SECRET_KEY": "test-secret",
            "FRONTEND_URL": "http://localhost:5173",
            "BACKEND_URL": "http://127.0.0.1:8000",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def test_production_hostname_gets_https_scheme(self):
        settings = self.build_settings(FRONTEND_URL="playnexis.in/")
        self.assertEqual(settings.FRONTEND_URL, "https://playnexis.in")

    def test_local_hostname_gets_http_scheme(self):
        settings = self.build_settings(FRONTEND_URL="localhost:5173/")
        self.assertEqual(settings.FRONTEND_URL, "http://localhost:5173")

    def test_query_string_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build_settings(FRONTEND_URL="https://playnexis.in?broken=1")


if __name__ == "__main__":
    unittest.main()
