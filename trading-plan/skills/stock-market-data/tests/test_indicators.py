#!/usr/bin/env python3
"""market_data.indicators — aggregation, last close, Wilder ATR, swing lows; Stooq as the oracle.

Deterministic, offline, stdlib-only. Determinism: the pipeline depends on live Yahoo + the wall clock (the `complete` flag). Both are
frozen — Yahoo responses are captured under fixtures/yahoo_*.json (trimmed ~7 months), and `today` is
pinned to FROZEN_TODAY. Expected OHLC is anchored to Stooq CSVs (fixtures/stooq_*.csv), the independent
source we cross-checked by hand. The two known ex-dividend weeks differ from Stooq only on the pre-ex
Open/High (Stooq back-adjusts; we keep actual-traded) — asserted explicitly, not silently skipped.
"""
from __future__ import annotations

import dataclasses, unittest
from datetime import date

from support import (FROZEN_DATE, TOL, DIVIDEND_WEEKS, daily_bar, load_stooq, num, pipeline,
                     price)
from market_data.adapters.yahoo import range_for_days
from market_data.indicators import (AtrReading, LastClosed, SwingLow, SwingLows, aggregate,
                                    atr_wilder, bars_needed, calendar_days, last_closed,
                                    series_window, swing_lows)
from market_data.model import (AtrPeriod, DateRange, Interval, PeriodBar, PeriodInterval, Quality,
                               SessionsEachSide, Status, Trust, Volume)
from quotes import quote_record

D = date.fromisoformat
W, M = PeriodInterval.WEEKLY, PeriodInterval.MONTHLY
ATR2, ATR14 = AtrPeriod(2), AtrPeriod(14)
EACH1, EACH2, EACH3 = SessionsEachSide(1), SessionsEachSide(2), SessionsEachSide(3)


def label(b):
    """The ISO date a bar is keyed by in the output: a session, or a period's first day."""
    return (b.session if hasattr(b, "session") else b.period_start).isoformat()


# --------------------------------------------------------------------------- unit: pure functions

class TestAggregate(unittest.TestCase):
    def _week(self, complete):
        # Mon-Wed of one week; open=Mon, high=max, low=min, close=Wed, vol=sum
        return [
            daily_bar("2026-07-20", 10.0, 12.0, 9.0, 11.0, 100),
            daily_bar("2026-07-21", 11.0, 13.0, 10.5, 12.5, 200),
            daily_bar("2026-07-22", 12.5, 12.9, 8.5, 9.5, 300, complete=complete),
        ]

    def test_rollup(self):
        [b] = aggregate(self._week(True), W, D("2026-07-25"))
        self.assertEqual(b, PeriodBar(D("2026-07-20"), price(10.0), price(13.0), price(8.5),
                                      price(9.5), Volume(600), True, Quality.GOOD))

    def test_takes_only_a_period_interval(self):
        """Daily is not a rollup: given Interval.DAILY, aggregate once grouped by month."""
        for interval in (Interval.DAILY, Interval.WEEKLY, "w"):
            with self.subTest(interval=interval), self.assertRaises(TypeError):
                aggregate(self._week(True), interval, D("2026-07-25"))

    def test_complete_after_friday(self):   # weekend: week's Friday < today -> complete
        [b] = aggregate(self._week(True), W, D("2026-07-25"))
        self.assertTrue(b.complete)

    def test_incomplete_midweek(self):      # Wednesday: Friday 07-24 not < today 07-22 -> forming
        [b] = aggregate(self._week(False), W, D("2026-07-22"))
        self.assertFalse(b.complete)

    def test_columns_roll_up_separately(self):
        """A gap in one column does not drop the session from the others: o is the first open
        present, v sums the volumes present, and a period with no volume at all has none."""
        days = [daily_bar("2026-07-20", None, 12.0, 9.0, 11.0),
                daily_bar("2026-07-21", 11.0, 13.0, 10.5, 12.5)]
        [b] = aggregate(days, W, D("2026-07-25"))
        self.assertEqual((b.open, b.high, b.low, b.close, b.volume),
                         (price(11.0), price(13.0), price(9.0), price(12.5), None))

    def _full_week(self, friday_complete):
        """Mon-Fri of one week; only Friday's completeness varies (during vs after its session)."""
        days = [daily_bar(f"2026-07-{20 + i}", 10.0, 12.0, 9.0, 11.0, 100) for i in range(4)]
        days.append(daily_bar("2026-07-24", 11.0, 13.0, 10.0, 12.0, 100, complete=friday_complete))
        return days

    def test_week_complete_on_friday_evening(self):
        # Friday after the close: end 07-24 is not < today, but Friday's own bar is closed
        [b] = aggregate(self._full_week(True), W, D("2026-07-24"))
        self.assertTrue(b.complete)
        self.assertEqual(b.close, price(12.0))

    def test_week_forming_during_friday_session(self):
        [b] = aggregate(self._full_week(False), W, D("2026-07-24"))
        self.assertFalse(b.complete)

    def test_month_complete_on_its_last_session_evening(self):
        days = [daily_bar("2026-07-31", 1.0, 2.0, 0.5, 1.5, 10)]
        [b] = aggregate(days, M, D("2026-07-31"))
        self.assertTrue(b.complete)          # month-end reached and that session is closed

    def test_monthly_incomplete_midmonth(self):
        days = [daily_bar("2026-07-01", 1.0, 2.0, 0.5, 1.5, 10)]
        [b] = aggregate(days, M, D("2026-07-25"))
        self.assertFalse(b.complete)     # month-end 07-31 not < 07-25


class TestCalendarDays(unittest.TestCase):
    def test_rounds_up_at_a_bucket_boundary(self):
        """21 daily bars need 31.5 calendar days: ceil gives 32 and the 3mo bucket; floor would give
        31 and a 1mo fetch one day short."""
        self.assertEqual(calendar_days("d", 21), 32)
        self.assertEqual(range_for_days(32), "3mo")


class TestLastClosed(unittest.TestCase):
    def test_picks_latest_complete(self):
        bars = [
            daily_bar("2026-07-20", c=1.0),
            daily_bar("2026-07-21", c=2.0),
            daily_bar("2026-07-22", c=3.0, complete=False),   # forming -> skipped
        ]
        self.assertEqual(last_closed(bars), LastClosed(D("2026-07-21"), price(2), Quality.GOOD))

    def test_reads_the_whole_series_not_the_returned_slice(self):
        """--bars 1 during a session shows only the forming bar; last_closed is still the previous
        close, not null. Computing it from the slice would have lost it."""
        daily = pipeline("PKN", "d")
        forming = dataclasses.replace(daily[-1], complete=False)
        rec = quote_record([*daily[:-1], forming], "d", 1, FROZEN_DATE)
        self.assertEqual(rec["bars"], [forming])
        self.assertEqual(rec["last_closed"],
                         LastClosed(D("2026-07-23"), price("155.86"), Quality.GOOD))


# ----------------------------------------------------------- integration: pipeline vs Stooq oracle

class TestATR(unittest.TestCase):
    """ATR is the one number two skills must agree on (the sizer's 2-3xATR band, the monitor's hard
    2xATR trailing floor), so it is pinned from three sides: arithmetic hand-checkable at n=2,
    independence from --bars, and a regression golden at n=14."""

    # Hand-computable series, n=2. TRs: 1, 1, 3, 5 (the last one via |prevC - L| = |12 - 7|).
    # seed = (1+1)/2 = 1 -> (1x1 + 3)/2 = 2 -> (2x1 + 5)/2 = 3.5
    HAND = [
        daily_bar("2026-01-01", 9, 10, 9, 10),
        daily_bar("2026-01-02", 10, 11, 10, 11),
        daily_bar("2026-01-05", 11, 12, 11, 11.5),
        daily_bar("2026-01-06", 12, 13, 10, 12),
        daily_bar("2026-01-07", 8, 8, 7, 7.5),
    ]

    def test_hand_computed(self):
        a = atr_wilder(self.HAND, ATR2)
        self.assertEqual(a, AtrReading(n=ATR2, method="wilder", value=3.5, bars_used=5,
                                       as_of=D("2026-01-07"), interval=None, quality=Quality.GOOD))
        self.assertTrue(a.short_history)                        # 4 TRs < ATR_WARMUP x 2

    def test_short_history_is_read_from_bars_used_not_stored(self):
        """A reading cannot say it is settled while holding fewer TRs than the run-up: 5 x 2 TRs
        need 11 candles."""
        def reading(bars_used):
            return AtrReading(n=ATR2, method="wilder", value=1.0, bars_used=bars_used,
                              as_of=D("2026-01-07"), interval=None, quality=Quality.GOOD)
        self.assertEqual((reading(10).short_history, reading(11).short_history), (True, False))
        with self.assertRaises(TypeError):
            AtrReading(n=ATR2, method="wilder", value=1.0, bars_used=11, as_of=D("2026-01-07"),
                       short_history=True, interval=None, quality=Quality.GOOD)

    def test_the_period_is_an_atr_period_not_a_swing_count(self):
        with self.assertRaises(TypeError):
            atr_wilder(self.HAND, EACH2)
        with self.assertRaises(TypeError):
            atr_wilder(self.HAND, 2)
        with self.assertRaises(TypeError):
            series_window(EACH2)

    def test_forming_bar_excluded(self):
        bars = [*self.HAND[:-1], dataclasses.replace(self.HAND[-1], complete=False)]
        a = atr_wilder(bars, ATR2)
        self.assertEqual(a.value, 2.0)           # the value before the forming bar
        self.assertEqual(a.as_of, D("2026-01-06"))

    def test_needs_high_low_and_close(self):
        """A bar missing any of the three cannot give a true range: it is left out, as forming is."""
        for field in ("high", "low", "close"):
            bars = [*self.HAND[:-1], dataclasses.replace(self.HAND[-1], **{field: None})]
            with self.subTest(field=field):
                self.assertEqual(atr_wilder(bars, ATR2).as_of, D("2026-01-06"))

    def test_none_when_too_few_candles(self):
        self.assertIsNone(atr_wilder(self.HAND, ATR14))
        self.assertIsNone(atr_wilder(self.HAND[:2], ATR2))   # n+1 = 3 needed

    def test_short_history_clears_after_the_runup(self):
        long = [dataclasses.replace(self.HAND[i % len(self.HAND)], session=D(f"2026-02-{i + 1:02d}"))
                for i in range(12)]
        self.assertFalse(atr_wilder(long, ATR2).short_history)   # 11 TRs > 5 x 2

    def test_bars_needed_covers_the_runup(self):
        self.assertEqual(bars_needed(6, None), 6)               # no ATR -> caller's ask
        self.assertEqual(bars_needed(6, ATR14), 71)             # 14 x 5 + 1
        self.assertEqual(bars_needed(200, ATR14), 200)          # caller already wants more

    def test_value_independent_of_returned_slice(self):
        """The regression that matters: a 6-bar morning check and a 70-bar sizing run must read the
        same ATR for the same instrument. Computing it from the returned slice would not."""
        daily = pipeline("PKN", "d")
        vals = {b: quote_record(daily, "d", b, FROZEN_DATE, ATR14)["atr"].value
                for b in (6, 20, 70, 150)}
        self.assertEqual(len(set(vals.values())), 1, vals)
        # ...and the test has teeth: the slice-based value really would have differed
        self.assertNotEqual(atr_wilder(daily[-20:], ATR14).value, vals[20])

    def test_golden_pkn_daily_n14(self):
        a = quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_DATE, ATR14)["atr"]
        self.assertAlmostEqual(a.value, 3.5264, places=4)
        self.assertEqual((a.as_of, a.bars_used, a.interval), (D("2026-07-24"), 71, Interval.DAILY))
        self.assertFalse(a.short_history)

    def test_window_capped_so_a_wider_fetch_cannot_shift_it(self):
        """The other half of the same promise: more history than the run-up must change nothing."""
        daily = pipeline("PKN", "d")                     # 150 complete bars
        self.assertEqual(atr_wilder(daily, ATR14), atr_wilder(daily[-71:], ATR14))
        self.assertEqual(atr_wilder(daily, ATR14).bars_used, 71)

    def test_weekly_runs_on_aggregated_candles(self):
        a = quote_record(pipeline("PKN", "d"), "w", 6, FROZEN_DATE, ATR14)["atr"]
        self.assertEqual((a.interval, a.as_of, a.bars_used), (Interval.WEEKLY, D("2026-07-20"), 32))
        self.assertAlmostEqual(a.value, 8.8829, places=4)
        self.assertTrue(a.short_history)         # 31 weekly TRs < 5 x 14 -> flagged, not hidden

    def test_absent_unless_asked(self):
        self.assertNotIn("atr", quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_DATE))

    def test_monthly_fixture_is_too_short_to_report(self):
        self.assertIsNone(quote_record(pipeline("PKN", "d"), "m", 6, FROZEN_DATE, ATR14)["atr"])


class TestSwingLows(unittest.TestCase):
    """Which low a trailing stop may anchor to is a rule; whether a session *is* a swing low is
    arithmetic, and two readers of the same chart disagreed on it by two grosz. So it is pinned the
    way ATR is: hand-computable detection, the derived flags, and the window invariant.

    Every confirmed low is reported, lower ones included — the caller applies the rule."""

    # Lows: 10, 9, 8, 9, 10, 9.5, 7, 8, 9. At 2 sessions each side only two qualify:
    # index 2 (8, undercut later by 7) and index 6 (7, never undercut).
    HAND = [daily_bar(f"2026-01-{i + 1:02d}", lo, lo + 1, lo, lo)
            for i, lo in enumerate([10, 9, 8, 9, 10, 9.5, 7, 8, 9])]

    def test_hand_computed_detection(self):
        s = swing_lows(self.HAND, EACH2)
        self.assertEqual([(r.session, r.low_price) for r in s.detected],
                         [(D("2026-01-03"), price(8)), (D("2026-01-07"), price(7))])

    def test_a_lower_neighbour_on_either_side_disqualifies(self):
        """The rule that keeps a stop off structure price walked through: 9 at index 3 has an 8 on
        its left, 9.5 at index 5 has a 9 on its left. Neither is a swing low, and no number of
        sessions closing after them will change that."""
        dates = [r.session for r in swing_lows(self.HAND, EACH2).detected]
        self.assertNotIn(D("2026-01-04"), dates)
        self.assertNotIn(D("2026-01-06"), dates)

    def test_derived_fields_carry_what_the_rule_needs(self):
        first, second = swing_lows(self.HAND, EACH2).detected
        self.assertEqual(first, SwingLow(
            session=D("2026-01-03"), low_price=price(8),
            higher_than_previous_row_low=None,          # the first row has nothing to compare with
            sessions_after_in_window=6, lowest_low_in_those_sessions=price(7)))
        self.assertEqual(second, SwingLow(
            session=D("2026-01-07"), low_price=price(7),
            higher_than_previous_row_low=False,         # 7 is below the 8 before it
            sessions_after_in_window=2, lowest_low_in_those_sessions=price(8)))
        self.assertEqual((first.undercut_by_later_session, second.undercut_by_later_session),
                         (True, False))

    def test_undercut_is_read_from_the_two_prices_not_stored(self):
        with self.assertRaises(TypeError):
            SwingLow(session=D("2026-01-03"), low_price=price(8),
                     higher_than_previous_row_low=None, sessions_after_in_window=6,
                     lowest_low_in_those_sessions=price(7), undercut_by_later_session=False)

    def test_the_count_is_sessions_each_side_not_an_atr_period(self):
        with self.assertRaises(TypeError):
            swing_lows(self.HAND, ATR2)
        with self.assertRaises(TypeError):
            swing_lows(self.HAND, 2)
        with self.assertRaises(TypeError):
            swing_lows(self.HAND, EACH2, atr_n=EACH2)
        with self.assertRaises(TypeError):
            bars_needed(6, None, ATR2)

    def test_an_exact_retest_is_not_an_undercut(self):
        """`undercut` is a strict `<`: price reaching the low again has not traded through it."""
        # Lows 10, 9, 8, 9, 10, 8, 11 — one swing low at index 2, retested to the grosz at index 5.
        bars = [daily_bar(f"2026-02-{i + 1:02d}", lo, lo + 1, lo, lo)
                for i, lo in enumerate([10, 9, 8, 9, 10, 8, 11])]
        row, = swing_lows(bars, EACH2).detected
        self.assertEqual((row.low_price, row.lowest_low_in_those_sessions), (price(8), price(8)))
        self.assertFalse(row.undercut_by_later_session)

    def test_detectable_through_lags_the_window_by_the_confirmation(self):
        s = swing_lows(self.HAND, EACH2)
        self.assertEqual((s.window, s.detectable_through),
                         (DateRange(D("2026-01-01"), D("2026-01-09")), D("2026-01-07")))
        self.assertEqual(swing_lows(self.HAND, EACH3).detectable_through, D("2026-01-06"))

    def test_too_short_a_window_detects_nothing_and_has_no_edge(self):
        s = swing_lows(self.HAND[:2], EACH2)
        self.assertEqual((s.window_sessions, s.detectable_through, s.detected), (2, None, ()))

    # With EACH2, a window of 9 sessions (01-01..01-09) can confirm a low; one of 2 (01-01..01-02)
    # cannot, because no session has two after it.
    NINE = DateRange(D("2026-01-01"), D("2026-01-09"))
    TWO = DateRange(D("2026-01-01"), D("2026-01-02"))

    def swings(self, window, window_sessions, through):
        return SwingLows(each_side=EACH2, window=window, window_sessions=window_sessions,
                         detectable_through=through, detected=(), interval=None,
                         quality=Quality.GOOD)

    def test_a_window_that_can_confirm_has_its_edge_inside_it(self):
        self.assertEqual(self.swings(self.NINE, 9, D("2026-01-07")).detectable_through,
                         D("2026-01-07"))

    def test_a_window_too_short_to_confirm_has_no_edge(self):
        self.assertIsNone(self.swings(self.TWO, 2, None).detectable_through)

    def test_an_edge_that_does_not_fit_is_refused(self):
        cases = {
            "a window that can confirm, without an edge": (self.NINE, 9, None),
            "a window too short to confirm, with an edge": (self.TWO, 2, D("2026-01-01")),
            "the edge on the window's last session": (self.NINE, 9, D("2026-01-09")),
            "the edge before the window": (self.NINE, 9, D("2025-12-31")),
        }
        for case, (window, window_sessions, through) in cases.items():
            with self.subTest(case), self.assertRaises(ValueError):
                self.swings(window, window_sessions, through)

    def test_forming_bar_excluded(self):
        bars = [*self.HAND[:-1], dataclasses.replace(self.HAND[-1], complete=False)]
        s = swing_lows(bars, EACH2)
        self.assertEqual(s.window.end, D("2026-01-08"))
        self.assertEqual(s.detectable_through, D("2026-01-06"))
        self.assertEqual([r.session for r in s.detected], [D("2026-01-03")])   # 7 loses its right side

    def test_needs_only_the_low(self):
        """Swing lows read lows alone: a bar with no close still counts."""
        bars = [dataclasses.replace(b, open=None, high=None, close=None) for b in self.HAND]
        self.assertEqual(swing_lows(bars, EACH2).detected, swing_lows(self.HAND, EACH2).detected)

    def test_no_pivot_is_an_empty_list_not_a_missing_key(self):
        rising = [dataclasses.replace(b, low=price(10 + i), session=D(f"2026-03-{i + 1:02d}"))
                  for i, b in enumerate(self.HAND)]
        self.assertEqual(swing_lows(rising, EACH2).detected, ())

    def test_window_matches_atr_so_both_describe_one_stretch(self):
        """A stop distance in ATR multiples is measured against these lows; if the two blocks read
        different history, the multiple describes structure the ATR never saw."""
        daily = pipeline("PKN", "d")                     # 150 complete bars
        rec = quote_record(daily, "d", 6, FROZEN_DATE, ATR14, EACH2)
        self.assertEqual(rec["swing_lows"].window_sessions, rec["atr"].bars_used)
        self.assertEqual(swing_lows(daily, EACH2), swing_lows(daily[-71:], EACH2))

    def test_result_independent_of_returned_slice(self):
        recs = [quote_record(pipeline("PKN", "d"), "d", b, FROZEN_DATE, ATR14, EACH2)["swing_lows"]
                for b in (6, 20, 70, 150)]
        self.assertTrue(all(r == recs[0] for r in recs), recs)

    def test_golden_pkn_daily(self):
        """Regression pin, not an independently verified one — the arithmetic rides on the hand
        tests above. Spot-checkable in the fixture: 144.20 on 2026-07-17 sits under 144.66 / 144.84
        on its left and 144.88 / 146.28 on its right, with five sessions left in the window."""
        s = quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_DATE, ATR14, EACH2)["swing_lows"]
        self.assertEqual((s.interval, s.window, s.window_sessions, s.detectable_through),
                         (Interval.DAILY, DateRange(D("2026-04-15"), D("2026-07-24")), 71,
                          D("2026-07-22")))
        self.assertEqual(len(s.detected), 10)
        self.assertEqual(s.detected[-1],
                         SwingLow(session=D("2026-07-17"), low_price=price("144.2"),
                                  higher_than_previous_row_low=True, sessions_after_in_window=5,
                                  lowest_low_in_those_sessions=price("144.88")))
        self.assertFalse(s.detected[-1].undercut_by_later_session)

    def test_weekly_runs_on_aggregated_candles(self):
        s = quote_record(pipeline("PKN", "d"), "w", 6, FROZEN_DATE, ATR14, EACH2)["swing_lows"]
        self.assertEqual(s.interval, Interval.WEEKLY)
        self.assertLess(s.window_sessions, 71)        # 150 daily bars aggregate to fewer weeks

    def test_absent_unless_asked(self):
        self.assertNotIn("swing_lows",
                         quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_DATE, ATR14))

    def test_bars_needed_covers_the_window_without_atr(self):
        self.assertEqual(bars_needed(6, None, None), 6)
        self.assertEqual(bars_needed(6, None, EACH2), 71)     # swings alone still widen the fetch
        self.assertEqual(bars_needed(6, ATR14, EACH2), 71)


PLACEHOLDER = Trust.untrusted("placeholder")


def placeholder(b, at):
    """Session `b` as the vendor served it when it had no trades: one price in all four fields,
    no volume, complete, and marked untrusted by its source."""
    return dataclasses.replace(b, open=at, high=at, low=at, close=at, volume=Volume(0),
                               complete=True, trust=PLACEHOLDER)


def with_placeholders(daily, k=5):
    """The last `k` sessions replaced by placeholders at the close of the session before them."""
    at = daily[-k - 1].close
    return [*daily[:-k], *(placeholder(b, at) for b in daily[-k:])]


def sessions(bars):
    return tuple(b.session for b in bars)


class TestReadingsCarryQuality(unittest.TestCase):
    """Without a session the source does not vouch for, every reading is GOOD and every value is the
    one it always was (the golden values above are read on the same series)."""

    def test_every_reading_is_good(self):
        daily = pipeline("PKN", "d")
        readings = [atr_wilder(daily), swing_lows(daily), last_closed(daily),
                    *aggregate(daily, W, FROZEN_DATE)]
        self.assertEqual({r.quality for r in readings}, {Quality.GOOD})
        self.assertEqual({b.status for b in aggregate(daily, W, FROZEN_DATE)}, {Status.GOOD})
        self.assertIsInstance(swing_lows(daily), SwingLows)


class TestPlaceholderSessions(unittest.TestCase):
    """The vendor once served five placeholder sessions in a row (ADR 0002). A derived value is read
    from the sessions the source vouches for only, and names the ones it left out. Here PKN's last
    week, 07-20..07-24, is five placeholders at the close of Friday 07-17."""

    def setUp(self):
        self.daily = pipeline("PKN", "d")
        self.clean = self.daily[:-5]                     # up to the last real session, 07-17
        self.served = with_placeholders(self.daily)
        self.left_out = sessions(self.daily[-5:])

    def test_atr_is_the_atr_as_of_the_last_real_session(self):
        a, clean = atr_wilder(self.served, ATR14), atr_wilder(self.clean, ATR14)
        self.assertEqual((a.value, a.as_of, a.bars_used), (clean.value, clean.as_of, clean.bars_used))
        self.assertEqual(a.as_of, D("2026-07-17"))
        self.assertEqual(a.quality, Quality(self.left_out))
        self.assertEqual(a.quality.status, Status.UNCERTAIN)
        # ...and the test has teeth: read as real sessions, the placeholders pull ATR down
        trusted = [dataclasses.replace(b, trust=Trust.TRUSTED) for b in self.served]
        self.assertLess(atr_wilder(trusted, ATR14).value, clean.value)

    def _placeholder_inside_the_window(self):
        """The real series with one session, well inside the window, served as a placeholder; and
        the series with that session simply missing."""
        gap = len(self.daily) - series_window(ATR14) // 2
        served = [*self.daily[:gap], placeholder(self.daily[gap], self.daily[gap - 1].close),
                  *self.daily[gap + 1:]]
        without = [*self.daily[:gap], *self.daily[gap + 1:]]
        return served, without, self.daily[gap].session

    def test_atr_reads_past_a_gap_inside_the_window_and_names_it(self):
        served, without, gap = self._placeholder_inside_the_window()
        self.assertEqual(atr_wilder(served, ATR14),
                         dataclasses.replace(atr_wilder(without, ATR14), quality=Quality((gap,))))

    def test_a_gap_inside_the_swing_window_pushes_its_start_one_session_back_and_is_named(self):
        served, _, gap = self._placeholder_inside_the_window()
        window = series_window(ATR14)
        s = swing_lows(served, EACH2, atr_n=ATR14)
        # the window still holds `window` trusted sessions, so it begins one session earlier
        self.assertEqual((s.window.start, s.window_sessions, s.quality),
                         (self.daily[-(window + 1)].session, window, Quality((gap,))))

    def test_no_swing_low_is_confirmed_by_a_placeholder(self):
        s, clean = swing_lows(self.served, EACH2), swing_lows(self.clean, EACH2)
        self.assertEqual(s, dataclasses.replace(clean, quality=Quality(self.left_out)))
        self.assertEqual((s.window.end, s.detectable_through),
                         (D("2026-07-17"), D("2026-07-15")))
        # ...and the test has teeth: read as real sessions, the placeholders confirm 07-17
        trusted = [dataclasses.replace(b, trust=Trust.TRUSTED) for b in self.served]
        self.assertIn(D("2026-07-17"), [r.session for r in swing_lows(trusted, EACH2).detected])

    def test_a_low_is_confirmed_once_real_sessions_follow_the_gap(self):
        """Lows 10, 9, 8 (close 8.5), then two placeholders at 8.5: as real sessions they would
        confirm the 8. Not as placeholders; two real sessions with higher lows after them do."""
        real = [daily_bar(f"2026-01-0{i + 1}", lo, lo + 1, lo, lo + 0.5)
                for i, lo in enumerate([10, 9, 8])]
        gap = [placeholder(daily_bar(f"2026-01-0{d}"), price(8.5)) for d in (4, 5)]
        after = [daily_bar("2026-01-06", 9, 10, 9, 9.5), daily_bar("2026-01-07", 10, 11, 10, 10.5)]
        self.assertEqual(swing_lows([*real, *gap], EACH2).detected, ())
        s = swing_lows([*real, *gap, *after], EACH2)
        self.assertEqual(s.detected, (SwingLow(
            session=D("2026-01-03"), low_price=price(8), higher_than_previous_row_low=None,
            sessions_after_in_window=2, lowest_low_in_those_sessions=price(9)),))
        self.assertEqual(s.quality, Quality((D("2026-01-04"), D("2026-01-05"))))

    def test_last_closed_is_the_last_real_session(self):
        self.assertEqual(last_closed(self.served),
                         LastClosed(D("2026-07-17"), price("146.2"), Quality(self.left_out)))

    def test_last_closed_reads_the_whole_series_when_the_slice_is_all_placeholders(self):
        rec = quote_record(self.served, "d", 5, FROZEN_DATE)
        self.assertEqual(sessions(rec["bars"]), self.left_out)
        self.assertEqual(rec["last_closed"],
                         LastClosed(D("2026-07-17"), price("146.2"), Quality(self.left_out)))

    def test_a_week_of_placeholders_stays_in_the_series_with_no_value(self):
        week = aggregate(self.served, W, FROZEN_DATE)[-1]
        self.assertEqual(week, PeriodBar(D("2026-07-20"), None, None, None, None, None, True,
                                         Quality(self.left_out)))
        self.assertEqual(week.status, Status.NO_VALUE)

    def test_a_week_with_two_real_sessions_is_read_from_those_two(self):
        served = with_placeholders(self.daily, 3)                    # Wed..Fri placeholders
        week = aggregate(served, W, FROZEN_DATE)[-1]
        mon_tue = aggregate(self.daily[:-3], W, FROZEN_DATE)[-1]
        self.assertEqual(week, dataclasses.replace(mon_tue, quality=Quality(sessions(self.daily[-3:]))))
        self.assertEqual(week.status, Status.UNCERTAIN)

    def test_a_placeholder_friday_still_closes_the_week_on_friday_evening(self):
        served = with_placeholders(self.daily, 1)
        week = aggregate(served, W, D("2026-07-24"))[-1]
        self.assertTrue(week.complete)
        self.assertEqual((week.close, week.quality), (self.daily[-2].close,
                                                      Quality((D("2026-07-24"),))))

    def test_weekly_readings_skip_the_week_with_no_value_and_name_its_sessions(self):
        weeks = aggregate(self.served, W, FROZEN_DATE)
        clean = aggregate(self.clean, W, FROZEN_DATE)
        a = atr_wilder(weeks, ATR14, Interval.WEEKLY)
        self.assertEqual(a, dataclasses.replace(atr_wilder(clean, ATR14, Interval.WEEKLY),
                                                quality=Quality(self.left_out)))
        self.assertEqual(a.as_of, D("2026-07-13"))
        self.assertEqual(last_closed(weeks),
                         dataclasses.replace(last_closed(clean), quality=Quality(self.left_out)))

    def test_a_forming_untrusted_bar_enters_no_period(self):
        """Before the open the vendor serves today as one flat price with no volume. It is not part
        of the week in progress: not its values, and not a session it left out either, since the
        session has not ended."""
        mon_tue = [daily_bar("2026-07-20", 10, 12, 9, 11, 100),
                   daily_bar("2026-07-21", 11, 13, 10.5, 12.5, 200)]
        forming = daily_bar("2026-07-22", 20, 20, 20, 20, 0, complete=False, trust=PLACEHOLDER)
        self.assertEqual(aggregate([*mon_tue, forming], W, D("2026-07-22")),
                         aggregate(mon_tue, W, D("2026-07-22")))


class TestClosedPlaceholderInThePeriodInProgress(unittest.TestCase):
    """Tuesday 10-13 during the session: Monday 10-12 was a closed placeholder, Tuesday is a forming
    one, 10-05..10-09 were real. The week in progress gives no reading, but the closed Monday it
    left out lies after every weekly reading's own date, so each of them names it, as D1 does."""

    TODAY = D("2026-10-13")
    MONDAY = D("2026-10-12")

    def setUp(self):
        lows = iter([10, 9, 8, 9, 10, 9.5, 8.5, 7, 8, 9, 11, 10, 9, 10, 12])   # Mon..Fri, 3 weeks
        self.real = [daily_bar(f"2026-{m:02d}-{d:02d}", lo + 0.5, lo + 2, lo, lo + 1, 100)
                     for m, days in ((9, (21, 22, 23, 24, 25, 28, 29, 30)), (10, (1, 2, 5, 6, 7, 8, 9)))
                     for d, lo in zip(days, lows)]
        at = self.real[-1].close
        self.served = [*self.real,
                       placeholder(daily_bar("2026-10-12"), at),
                       dataclasses.replace(placeholder(daily_bar("2026-10-13"), at), complete=False)]
        self.weeks = aggregate(self.served, W, self.TODAY)
        self.clean = aggregate(self.real, W, self.TODAY)

    def test_the_week_in_progress_is_forming_and_names_its_closed_monday(self):
        self.assertEqual(self.weeks[-1], PeriodBar(D("2026-10-12"), None, None, None, None, None,
                                                   False, Quality((self.MONDAY,))))

    def test_daily_last_closed_names_the_monday(self):
        self.assertEqual(last_closed(self.served),
                         dataclasses.replace(last_closed(self.real), quality=Quality((self.MONDAY,))))

    def test_weekly_last_closed_names_the_monday(self):
        lc = last_closed(self.weeks)
        self.assertEqual(lc, dataclasses.replace(last_closed(self.clean),
                                                 quality=Quality((self.MONDAY,))))
        self.assertEqual((lc.session, lc.quality.status), (D("2026-10-05"), Status.UNCERTAIN))

    def test_weekly_atr_names_the_monday(self):
        a = atr_wilder(self.weeks, ATR2, Interval.WEEKLY)
        self.assertIsNotNone(a)
        self.assertEqual(a, dataclasses.replace(atr_wilder(self.clean, ATR2, Interval.WEEKLY),
                                                quality=Quality((self.MONDAY,))))

    def test_weekly_swing_lows_name_the_monday(self):
        s = swing_lows(self.weeks, EACH1, Interval.WEEKLY)
        self.assertEqual(s, dataclasses.replace(swing_lows(self.clean, EACH1, Interval.WEEKLY),
                                                quality=Quality((self.MONDAY,))))

    def test_a_forming_daily_placeholder_is_still_not_named(self):
        """The fix is for period bars only: Tuesday has not ended, so no D1 reading names it."""
        self.assertNotIn(self.TODAY, last_closed(self.served).quality.excluded)


class TestStooqOracle(unittest.TestCase):
    """Golden: our aggregated bars must equal Stooq to the grosz on every clean period; on the two
    known ex-dividend weeks, Low/Close still match while Open/High stay at our unadjusted value.

    Scope = the hand-verified recent window per interval. Older history is out of scope on purpose:
    the trimmed fixture starts mid-period (so the oldest week/month is partial), and deep history
    reintroduces every past corporate action, which we did not verify by hand."""

    CASES = [("PKN", ("d", "w", "m")), ("KGH", ("d", "w", "m")), ("LPP", ("d", "w", "m"))]
    WINDOW = {"d": "2026-07-03", "w": "2026-06-01", "m": "2026-04-01"}   # inclusive lower bound

    def test_ohlc_against_stooq(self):
        for ticker, intervals in self.CASES:
            for iv in intervals:
                ours = {label(b): b for b in pipeline(ticker, iv)}
                stq = load_stooq(ticker, iv)
                lo = self.WINDOW[iv]
                overlap = sorted(k for k in set(ours) & set(stq) if k >= lo)
                self.assertGreaterEqual(len(overlap), 3, f"{ticker}/{iv}: too few overlapping periods")
                for k in overlap:
                    o, s = ours[k], stq[k]
                    div_open = DIVIDEND_WEEKS.get((ticker, iv, k))
                    with self.subTest(ticker=ticker, interval=iv, period=k):
                        # Low & Close always match the independent source
                        self.assertAlmostEqual(num(o.low), s["l"], delta=TOL(s["l"]))
                        self.assertAlmostEqual(num(o.close), s["c"], delta=TOL(s["c"]))
                        if div_open is None:
                            self.assertAlmostEqual(num(o.open), s["o"], delta=TOL(s["o"]))
                            self.assertAlmostEqual(num(o.high), s["h"], delta=TOL(s["h"]))
                        else:
                            # ex-div week: we report actual-traded open, Stooq back-adjusts it lower
                            self.assertAlmostEqual(num(o.open), div_open, delta=TOL(div_open))
                            self.assertGreater(num(o.open), s["o"])

    # The newest closed period on Saturday FROZEN_TODAY, the same for every ticker.
    LAST_CLOSED = {
        "d": "2026-07-24",   # Friday, the last session in the fixtures
        "w": "2026-07-20",   # that Friday closed its week
        "m": "2026-06-01",   # July is still forming, so June
    }

    def test_last_closed_is_the_newest_closed_period_at_stooqs_close(self):
        for ticker, intervals in self.CASES:
            for iv in intervals:
                lc = last_closed(pipeline(ticker, iv))
                stooq_close = load_stooq(ticker, iv)[self.LAST_CLOSED[iv]]["c"]
                with self.subTest(ticker=ticker, interval=iv):
                    self.assertEqual(lc.session, D(self.LAST_CLOSED[iv]))
                    self.assertAlmostEqual(num(lc.close), stooq_close, delta=TOL(stooq_close))

    def test_current_month_is_forming(self):
        for ticker in ("PKN", "KGH", "LPP"):
            july = {label(b): b for b in pipeline(ticker, "m")}["2026-07-01"]
            with self.subTest(ticker=ticker):
                self.assertFalse(july.complete)   # month-end 07-31 not < FROZEN_TODAY


if __name__ == "__main__":
    unittest.main(verbosity=2)
