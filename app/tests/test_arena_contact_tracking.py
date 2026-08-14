import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from app.arena.schemas import ArenaContactEventCreate
from app.arena.service import track_arena_contact_event
from app.core.auth_context import AuthContext


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeContactEventsQuery:
    def __init__(self, rows):
        self.rows = rows
        self.action = "select"
        self.payload = None
        self.filters = []

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def select(self, _columns):
        self.action = "select"
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def is_(self, field, value):
        self.filters.append(("is", field, value))
        return self

    def maybe_single(self):
        return self

    def _matches(self, row):
        for operation, field, value in self.filters:
            if operation == "eq" and str(row.get(field)) != str(value):
                return False
            if operation == "is" and value == "null" and row.get(field) is not None:
                return False
        return True

    def execute(self):
        if self.action == "insert":
            row = {"id": "00000000-0000-0000-0000-000000000001", **self.payload}
            self.rows.append(row)
            return FakeResponse([row])

        matches = [row for row in self.rows if self._matches(row)]
        if self.action == "update":
            for row in matches:
                row.update(self.payload)
            return FakeResponse(matches)
        return FakeResponse(matches[0] if matches else None)


class FakeAdminClient:
    def __init__(self):
        self.rows = []

    def table(self, name):
        if name != "arena_contact_events":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeContactEventsQuery(self.rows)


class ArenaContactTrackingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeAdminClient()
        self.anonymous_id = UUID("2e1f8f36-faf7-4a0c-a1dc-a2819e27e26a")

    @patch("app.arena.service.get_arena_detail", return_value={"id": "arena-1", "name": "Demo Arena"})
    @patch("app.arena.service.get_supabase_admin_client")
    def test_guest_event_is_created_without_user_id(self, admin_client, _arena):
        admin_client.return_value = self.client

        result = track_arena_contact_event(None, "arena-1", ArenaContactEventCreate(
            event_type="view_number",
            anonymous_id=self.anonymous_id,
        ))

        self.assertEqual(result["event_type"], "view_number")
        self.assertIsNone(result["user_id"])
        self.assertEqual(result["arena_name"], "Demo Arena")

    @patch("app.arena.service.get_arena_detail", return_value={"id": "arena-1", "name": "Demo Arena"})
    @patch("app.arena.service.get_supabase_admin_client")
    def test_login_attributes_existing_guest_event_without_duplicate(self, admin_client, _arena):
        admin_client.return_value = self.client
        guest = track_arena_contact_event(None, "arena-1", ArenaContactEventCreate(
            event_type="whatsapp",
            anonymous_id=self.anonymous_id,
        ))
        context = AuthContext(
            access_token="token",
            user=SimpleNamespace(id="user-1"),
            role="player",
            profile={"id": "player-1"},
        )

        result = track_arena_contact_event(context, "arena-1", ArenaContactEventCreate(
            event_type="whatsapp",
            anonymous_id=self.anonymous_id,
            event_id=UUID(guest["id"]),
        ))

        self.assertEqual(guest["arena_id"], "arena-1")
        self.assertEqual(result["user_id"], "user-1")
        self.assertEqual(len(self.client.rows), 1)


if __name__ == "__main__":
    unittest.main()
