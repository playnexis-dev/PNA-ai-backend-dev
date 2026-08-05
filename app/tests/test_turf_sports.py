import unittest

from app.arena.service import _normalize_turf_sports


class TurfSportsTests(unittest.TestCase):
    def test_removes_generic_placeholder_and_duplicates(self):
        self.assertEqual(
            _normalize_turf_sports(
                ["Multi-sport", "Football", "multi sport", "Cricket", "football"]
            ),
            ["Football", "Cricket"],
        )


if __name__ == "__main__":
    unittest.main()
