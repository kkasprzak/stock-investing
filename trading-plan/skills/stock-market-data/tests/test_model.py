"""market_data.model — the value objects every source and the CLI share."""
from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

import support  # noqa: F401  (puts scripts/ on sys.path)
import quotes
from market_data.model import (DailyBar, DailyQuote, DateRange, Instrument, Interval, Isin,
                               PeriodBar, Price, Quality, Status, Trust, Volume)


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


class TestIsin(unittest.TestCase):
    def test_accepts_every_isin_in_the_symbol_map(self):
        with open(quotes.SYMBOLS) as f:
            keys = list(json.load(f)["instruments"])
        self.assertEqual(len(keys), 144)
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(str(Isin.parse(key)), key)

    def test_rejects_a_wrong_check_digit(self):
        with self.assertRaises(ValueError):
            Isin.parse("PLPEKAO00017")          # PLPEKAO00016 is Pekao

    def test_rejects_lower_case(self):
        with self.assertRaises(ValueError):
            Isin.parse("plpkn0000018")

    def test_rejects_a_wrong_length(self):
        for text in ("PLPKN000018", "PLPKN00000018", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Isin.parse(text)

    def test_rejects_a_path(self):
        with self.assertRaises(ValueError):
            Isin.parse("../x")

    def test_rejects_a_trailing_newline(self):
        with self.assertRaises(ValueError):
            Isin.parse("PLPKN0000018\n")

    def test_constructor_holds_the_same_rule(self):
        with self.assertRaises(ValueError):
            Isin("PL0000000000")


class TestPrice(unittest.TestCase):
    def test_keeps_the_text_it_was_parsed_from(self):
        self.assertEqual(str(Price.parse("133.50")), "133.50")
        self.assertEqual(str(Price.parse("19")), "19")

    def test_equality_is_by_value(self):
        self.assertEqual(Price.parse("133.5"), Price.parse("133.50"))

    def test_value_is_a_decimal(self):
        self.assertEqual(Price.parse("0.1235").value, Decimal("0.1235"))

    def test_rejects(self):
        for text in ("0", "0.00", "-1", "inf", "nan", "1e2", " 1.5", "1.5 ", "", "1.", ".5", "1,5",
                     "1.5\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Price.parse(text)

    def test_constructor_holds_the_same_rule(self):
        for value in (Decimal("0"), Decimal("-1"), Decimal("Infinity"), Decimal("NaN")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Price(value)


class TestVolume(unittest.TestCase):
    def test_parses_a_whole_number(self):
        self.assertEqual(Volume.parse("566443").value, 566443)
        self.assertEqual(str(Volume.parse("0")), "0")

    def test_rejects(self):
        for text in ("560358.27", "-1", "", " 1", "1e3", "1\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Volume.parse(text)

    def test_constructor_holds_the_same_rule(self):
        with self.assertRaises(ValueError):
            Volume(-1)


def quote(o, h, l, c):  # noqa: E741
    return DailyQuote(date(2026, 10, 9), Price.parse(o), Price.parse(h), Price.parse(l),
                      Price.parse(c), Volume.parse("1000"))


class TestDailyQuote(unittest.TestCase):
    def test_accepts_a_flat_session(self):
        q = quote("100", "100", "100", "100")
        self.assertEqual((q.open, q.close), (Price.parse("100"), Price.parse("100")))

    def test_accepts_a_regular_session(self):
        quote("100", "104", "98", "102")

    def test_rejects_low_above_open(self):
        with self.assertRaises(ValueError):
            quote("100", "104", "101", "102")

    def test_rejects_low_above_close(self):
        with self.assertRaises(ValueError):
            quote("102", "104", "101", "100")

    def test_rejects_high_below_open(self):
        with self.assertRaises(ValueError):
            quote("105", "104", "98", "102")

    def test_rejects_high_below_close(self):
        with self.assertRaises(ValueError):
            quote("102", "104", "98", "105")


class TestTrust(unittest.TestCase):
    def test_trusted_has_no_reason(self):
        self.assertTrue(Trust.TRUSTED.trusted)
        self.assertIsNone(Trust.TRUSTED.reason)

    def test_untrusted_keeps_its_reason(self):
        t = Trust.untrusted("placeholder")
        self.assertFalse(t.trusted)
        self.assertEqual(t.reason, "placeholder")

    def test_untrusted_rejects_an_empty_or_blank_reason(self):
        for reason in ("", "   ", "\n"):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                Trust.untrusted(reason)

    def test_constructor_holds_the_same_rule(self):
        for reason in ("", "   "):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                Trust(reason)


class TestStatus(unittest.TestCase):
    def test_values(self):
        self.assertEqual((Status.GOOD, Status.UNCERTAIN, Status.NO_VALUE),
                         ("good", "uncertain", "no_value"))


D1, D2, D3 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)


class TestQuality(unittest.TestCase):
    def test_good_excludes_nothing(self):
        self.assertEqual(Quality.GOOD.excluded, ())
        self.assertIs(Quality.GOOD.status, Status.GOOD)

    def test_any_excluded_session_makes_it_uncertain(self):
        self.assertIs(Quality((D1,)).status, Status.UNCERTAIN)

    def test_excluded_is_sorted_and_unique(self):
        self.assertEqual(Quality((D3, D1, D3, D2, D1)).excluded, (D1, D2, D3))

    def test_equal_whatever_order_the_dates_came_in(self):
        self.assertEqual(Quality((D2, D1)), Quality((D1, D2, D1)))

    def test_combine_is_the_union_of_excluded(self):
        self.assertEqual(Quality.combine(Quality((D3, D1)), Quality.GOOD, Quality((D1, D2))),
                         Quality((D1, D2, D3)))

    def test_combine_of_good_is_good(self):
        self.assertEqual(Quality.combine(Quality.GOOD, Quality.GOOD), Quality.GOOD)
        self.assertEqual(Quality.combine(), Quality.GOOD)


def p(text):
    return Price.parse(text)


class TestDailyBar(unittest.TestCase):
    def test_builds_with_no_prices_and_no_volume(self):
        b = DailyBar(D1, None, None, None, None, None, complete=False, source="yahoo",
                     trust=Trust.TRUSTED)
        self.assertEqual((b.open, b.high, b.low, b.close, b.volume), (None,) * 5)

    def test_holds_no_ohlc_rules(self):
        # what a source said, not a quote: a low above the high is still a bar
        b = DailyBar(D1, p("100"), p("98"), p("104"), p("102"), Volume(0), complete=True,
                     source="yahoo", trust=Trust.untrusted("placeholder"))
        self.assertEqual((b.high, b.low), (p("98"), p("104")))
        self.assertFalse(b.trust.trusted)


class TestPeriodBar(unittest.TestCase):
    def bar(self, close, quality):
        return PeriodBar(D1, p("100"), p("104"), p("98"), close, Volume(1000), complete=True,
                         quality=quality)

    def test_good_when_close_is_there_and_nothing_excluded(self):
        self.assertIs(self.bar(p("102"), Quality.GOOD).status, Status.GOOD)

    def test_uncertain_when_close_is_there_and_sessions_were_excluded(self):
        self.assertIs(self.bar(p("102"), Quality((D2,))).status, Status.UNCERTAIN)

    def test_no_value_without_a_close(self):
        for quality in (Quality.GOOD, Quality((D2,))):
            with self.subTest(quality=quality):
                self.assertIs(self.bar(None, quality).status, Status.NO_VALUE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
