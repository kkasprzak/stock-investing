"""market_data.model — the value objects every source and the CLI share."""
from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

import support  # noqa: F401  (puts scripts/ on sys.path)
import quotes
from market_data.model import (AtrPeriod, DailyBar, DailyQuote, DateRange, Instrument, Interval,
                               Isin, PeriodBar, PeriodInterval, Price, Quality, SessionsEachSide,
                               Status, Trust, Volume)


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


class TestPeriodInterval(unittest.TestCase):
    """The interval aggregate rolls daily bars up into: weekly or monthly, never daily."""

    D = date.fromisoformat

    def test_daily_is_not_a_period_interval(self):
        with self.assertRaises(ValueError):
            PeriodInterval(Interval.DAILY)

    def test_holds_an_interval_not_its_string(self):
        with self.assertRaises(ValueError):
            PeriodInterval("w")

    def test_constants(self):
        self.assertEqual((PeriodInterval.WEEKLY.interval, PeriodInterval.MONTHLY.interval),
                         (Interval.WEEKLY, Interval.MONTHLY))
        self.assertEqual(PeriodInterval(Interval.WEEKLY), PeriodInterval.WEEKLY)

    def test_weekly_period_is_monday_to_friday(self):
        week = DateRange(self.D("2026-07-20"), self.D("2026-07-24"))
        self.assertEqual(PeriodInterval.WEEKLY.period(self.D("2026-07-24")), week)
        self.assertEqual(PeriodInterval.WEEKLY.period(self.D("2026-07-20")), week)

    def test_monthly_period_and_year_boundary(self):
        self.assertEqual(PeriodInterval.MONTHLY.period(self.D("2026-07-15")),
                         DateRange(self.D("2026-07-01"), self.D("2026-07-31")))
        self.assertEqual(PeriodInterval.MONTHLY.period(self.D("2026-12-31")),
                         DateRange(self.D("2026-12-01"), self.D("2026-12-31")))


class TestCounts(unittest.TestCase):
    """The ATR period and the sessions each side of a swing low: whole numbers, at least 1, and two
    types, so one cannot be passed where the other is meant."""

    def test_at_least_one(self):
        for cls in (AtrPeriod, SessionsEachSide):
            self.assertEqual(cls(1).value, 1)
            self.assertEqual(str(cls(14)), "14")
            for bad in (0, -3, True, 2.0, "2", None):
                with self.subTest(cls=cls.__name__, value=bad), self.assertRaises(ValueError):
                    cls(bad)

    def test_the_two_are_not_interchangeable(self):
        self.assertNotEqual(AtrPeriod(2), SessionsEachSide(2))


class TestInstrument(unittest.TestCase):
    def test_unmapped_keeps_its_isin_and_has_no_symbols(self):
        i = Instrument.unmapped(Isin.parse("US0378331005"))
        self.assertEqual(i.isin, Isin.parse("US0378331005"))
        self.assertEqual(dict(i.symbols), {})

    def test_is_named_by_its_isin_only(self):
        with self.assertRaises(TypeError):
            Instrument(key="PKN.PL", isin=Isin.parse("PLPKN0000018"), symbols={})


class TestIsin(unittest.TestCase):
    def test_accepts_every_isin_in_the_symbol_map(self):
        with open(quotes.SYMBOLS) as f:
            keys = list(json.load(f)["instruments"])
        self.assertEqual(len(keys), 145)
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
        self.assertIsNone(q.ohlc_breach)

    def test_accepts_a_regular_session(self):
        self.assertIsNone(quote("100", "104", "98", "102").ohlc_breach)

    def test_a_quote_whose_low_or_high_does_not_bracket_open_and_close_exists_and_names_the_breach(self):
        """A vendor can publish such a row (GPW did, ADR 0005); what to make of it is decided by
        whoever holds the quote, so the quote states the breach instead of refusing to exist."""
        for o, h, l, c, breach in (  # noqa: E741
                ("100", "104", "101", "102", "low 101 is above min(open 100, close 102)"),
                ("102", "104", "101", "100", "low 101 is above min(open 102, close 100)"),
                ("105", "104", "98", "102", "high 104 is below max(open 105, close 102)"),
                ("102", "104", "98", "105", "high 104 is below max(open 102, close 105)")):
            with self.subTest(o=o, h=h, l=l, c=c):
                q = quote(o, h, l, c)
                self.assertEqual((str(q.low), str(q.high)), (l, h))     # kept as given, not fixed
                self.assertEqual(q.ohlc_breach, breach)

    def test_a_low_above_the_high_is_a_breach(self):
        self.assertIsNotNone(quote("100", "99", "101", "100").ohlc_breach)

    def test_prices_and_volume_stay_strict(self):
        with self.assertRaises(ValueError):
            DailyQuote(date(2026, 10, 9), Price.parse("100"), Price.parse("104"),
                       Price.parse("98"), Price.parse("0"), Volume.parse("1000"))


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
        b = DailyBar(D1, p("100"), p("98"), p("104"), p("102"), Volume(1000), complete=True,
                     source="yahoo", trust=Trust.TRUSTED)
        self.assertEqual((b.high, b.low), (p("98"), p("104")))


class TestDailyBarAsCandle(unittest.TestCase):
    """What a daily bar tells a reading over it: its day, whether it may be read, and what it
    leaves out of the reading's quality."""

    def bar(self, complete=True, trust=Trust.TRUSTED):
        return DailyBar(D2, p("100"), p("104"), p("98"), p("102"), Volume(1000),
                        complete=complete, source="yahoo", trust=trust)

    def test_its_day_is_its_session(self):
        self.assertEqual(self.bar().day, D2)

    def test_trusted_when_its_source_vouches_for_it(self):
        self.assertTrue(self.bar(trust=Trust.TRUSTED).trusted)

    def test_not_trusted_when_its_source_does_not(self):
        self.assertFalse(self.bar(trust=Trust.untrusted("placeholder")).trusted)

    def test_a_trusted_session_leaves_nothing_out(self):
        self.assertEqual(self.bar(trust=Trust.TRUSTED).quality, Quality.GOOD)

    def test_an_untrusted_session_that_ended_leaves_itself_out(self):
        self.assertEqual(self.bar(complete=True, trust=Trust.untrusted("placeholder")).quality,
                         Quality((D2,)))

    def test_an_untrusted_forming_session_leaves_nothing_out(self):
        # not read anyway because it has not closed, so it is no left-out session (ADR 0002)
        self.assertEqual(self.bar(complete=False, trust=Trust.untrusted("placeholder")).quality,
                         Quality.GOOD)


class TestPeriodBarAsCandle(unittest.TestCase):
    def bar(self, quality=Quality.GOOD):
        return PeriodBar(D1, p("100"), p("104"), p("98"), p("102"), Volume(1000), complete=True,
                         quality=quality)

    def test_its_day_is_the_first_day_of_its_period(self):
        self.assertEqual(self.bar().day, D1)

    def test_trusted_even_when_it_left_sessions_out(self):
        # judged by its quality, not vouched for by a source
        self.assertTrue(self.bar(quality=Quality((D2,))).trusted)


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
