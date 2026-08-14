import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.site.service import record_home_page_visit


class FakeRpc:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return SimpleNamespace(data=self.value)


class FakeSupabaseClient:
    def __init__(self, value):
        self.value = value
        self.function_name = None
        self.parameters = None

    def rpc(self, function_name, parameters):
        self.function_name = function_name
        self.parameters = parameters
        return FakeRpc(self.value)


class SiteVisitTests(unittest.TestCase):
    @patch("app.site.service.get_supabase_client")
    def test_home_visit_uses_atomic_counter_function(self, get_client):
        client = FakeSupabaseClient(8911)
        get_client.return_value = client

        count = record_home_page_visit()

        self.assertEqual(count, 8911)
        self.assertEqual(client.function_name, "increment_site_counter")
        self.assertEqual(client.parameters["p_counter_key"], "home_page")
        self.assertEqual(client.parameters["p_baseline"], 8910)

    @patch("app.site.service.get_supabase_client")
    def test_home_visit_accepts_postgrest_list_response(self, get_client):
        get_client.return_value = FakeSupabaseClient([8912])

        self.assertEqual(record_home_page_visit(), 8912)


if __name__ == "__main__":
    unittest.main()
