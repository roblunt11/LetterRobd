import unittest
from datetime import date

from letterboxd_stats.periods import resolve_period

AS_OF = date(2026, 11, 17)


class PeriodTests(unittest.TestCase):
    def test_rolling_month(self):
        p = resolve_period("month", AS_OF)
        self.assertEqual((p.start, p.end), (date(2026, 10, 18), AS_OF))

    def test_three_and_six_months(self):
        self.assertEqual(resolve_period("3months", AS_OF).start, date(2026, 8, 18))
        self.assertEqual(resolve_period("6months", AS_OF).start, date(2026, 5, 18))

    def test_year(self):
        p = resolve_period("year", AS_OF)
        self.assertEqual((p.start, p.end), (date(2025, 11, 18), AS_OF))

    def test_month_end_clamps(self):
        # 31 Mar minus one month lands on 28 Feb, so the window starts 1 Mar.
        p = resolve_period("month", date(2026, 3, 31))
        self.assertEqual(p.start, date(2026, 3, 1))

    def test_calendar_year(self):
        p = resolve_period("calendar-year", AS_OF, calendar_year=2025)
        self.assertEqual((p.start, p.end), (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertTrue(p.contains(date(2025, 6, 1)))
        self.assertFalse(p.contains(date(2026, 1, 1)))

    def test_calendar_year_defaults_to_as_of_year(self):
        self.assertEqual(resolve_period("calendar-year", AS_OF).label, "2026")

    def test_unknown_period(self):
        with self.assertRaises(ValueError):
            resolve_period("decade", AS_OF)


if __name__ == "__main__":
    unittest.main()
