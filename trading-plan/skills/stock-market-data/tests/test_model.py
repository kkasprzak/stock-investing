"""market_data.model — the value objects every source and the CLI share."""
from __future__ import annotations

import unittest
from datetime import date

import support  # noqa: F401  (puts scripts/ on sys.path)
from market_data.model import DateRange, Instrument, Interval


class TestDateRange(unittest.TestCase):
    def test_days_is_the_calendar_span(self):
        self.assertEqual(DateRange(date(2026, 7, 1), date(2026, 7, 31)).days, 30)

    def test_single_day_is_allowed(self):
        self.assertEqual(DateRange(date(2026, 7, 24), date(2026, 7, 24)).days, 0)

    def test_rejects_start_after_end(self):
        with self.assertRaises(ValueError):
            DateRange(date(2026, 7, 25), date(2026, 7, 24))


class TestInterval(unittest.TestCase):
    def test_label(self):
        self.assertEqual((Interval.DAILY.label, Interval.WEEKLY.label, Interval.MONTHLY.label),
                         ("daily", "weekly", "monthly"))

    def test_calendar_factor(self):
        self.assertEqual((Interval.DAILY.calendar_factor, Interval.WEEKLY.calendar_factor,
                          Interval.MONTHLY.calendar_factor), (1.5, 7, 30))

    def test_coerces_from_the_bare_cli_string(self):
        self.assertIs(Interval("w"), Interval.WEEKLY)
        self.assertIs(Interval(Interval.WEEKLY), Interval.WEEKLY)

    def test_compares_equal_to_its_string(self):
        self.assertEqual(Interval.DAILY, "d")

    def test_unknown_value_is_rejected(self):
        with self.assertRaises(ValueError):
            Interval("x")


class TestInstrument(unittest.TestCase):
    def test_unmapped_has_no_isin_and_no_symbols(self):
        i = Instrument.unmapped("ZZZ.PL")
        self.assertEqual(i.key, "ZZZ.PL")
        self.assertIsNone(i.isin)
        self.assertEqual(dict(i.symbols), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
