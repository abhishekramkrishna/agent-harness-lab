import unittest
from datetime import date

from dates import days_in_range, nights


class TestDates(unittest.TestCase):
    def test_nights(self):
        self.assertEqual(nights(date(2026, 1, 1), date(2026, 1, 4)), 3)

    def test_inclusive_range(self):
        self.assertEqual(days_in_range(date(2026, 1, 1), date(2026, 1, 31)), 31)

    def test_single_day(self):
        self.assertEqual(days_in_range(date(2026, 3, 5), date(2026, 3, 5)), 1)

    def test_reversed_range_rejected(self):
        with self.assertRaises(ValueError):
            days_in_range(date(2026, 3, 5), date(2026, 3, 1))


if __name__ == "__main__":
    unittest.main()
