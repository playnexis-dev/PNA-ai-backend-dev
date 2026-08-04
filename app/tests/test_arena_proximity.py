import unittest

from app.arena.proximity import haversine_distance_km, rank_arenas_by_location


class ArenaProximityTests(unittest.TestCase):
    def test_same_city_is_ranked_before_nearby_city(self):
        arenas = [
            {"id": "nearby", "name": "Nearby", "city": "Noida", "latitude": 28.57, "longitude": 77.32},
            {"id": "same", "name": "Same", "city": "Delhi", "latitude": 28.61, "longitude": 77.21},
        ]

        ranked = rank_arenas_by_location(
            arenas,
            city=" Delhi ",
            latitude=28.60,
            longitude=77.20,
            radius_km=50,
        )

        self.assertEqual([arena["id"] for arena in ranked], ["same", "nearby"])
        self.assertEqual(ranked[0]["proximity_group"], "same_city")
        self.assertIsNotNone(ranked[0]["distance_km"])

    def test_same_city_without_coordinates_remains_visible(self):
        ranked = rank_arenas_by_location(
            [{"id": "missing", "name": "Missing", "city": "Bhopal"}],
            city="Bhopal",
            latitude=23.25,
            longitude=77.41,
        )

        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0]["location_incomplete"])
        self.assertIsNone(ranked[0]["distance_km"])

    def test_arena_outside_radius_is_excluded(self):
        ranked = rank_arenas_by_location(
            [{"id": "far", "name": "Far", "city": "Agra", "latitude": 27.18, "longitude": 78.01}],
            city="Delhi",
            latitude=28.61,
            longitude=77.21,
            radius_km=50,
        )

        self.assertEqual(ranked, [])

    def test_haversine_returns_expected_short_distance(self):
        distance = haversine_distance_km(19.1136, 72.8697, 19.1146, 72.8707)
        self.assertGreater(distance, 0.1)
        self.assertLess(distance, 0.2)


if __name__ == "__main__":
    unittest.main()
