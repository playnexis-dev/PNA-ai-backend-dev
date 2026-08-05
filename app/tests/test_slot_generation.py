import unittest
from datetime import date

from app.arena.service import _full_day_slot_windows, _slot_price_for_date


class SlotGenerationTests(unittest.TestCase):
    def test_sixty_minute_window_covers_the_full_day(self):
        windows = _full_day_slot_windows(60)

        self.assertEqual(len(windows), 24)
        self.assertEqual(windows[0], ("00:00:00", "01:00:00", "00:00-01:00"))
        self.assertEqual(windows[-1], ("23:00:00", "23:59:59", "23:00-24:00"))

    def test_ninety_minute_window_creates_sixteen_slots(self):
        self.assertEqual(len(_full_day_slot_windows(90)), 16)

    def test_peak_and_discount_days_adjust_generated_price(self):
        turf = {
            "price_per_slot": 500,
            "metadata": {
                "peak_days": ["Mon"],
                "peak_surcharge": 100,
                "discount_days": ["Tue"],
                "discount_amount": 50,
            },
        }

        self.assertEqual(_slot_price_for_date(turf, date(2026, 8, 3)), 600)
        self.assertEqual(_slot_price_for_date(turf, date(2026, 8, 4)), 450)


if __name__ == "__main__":
    unittest.main()
