#!/usr/bin/env python3
"""market_data.indicators — aggregation, last close, Wilder ATR, swing lows; Stooq as the oracle.

Deterministic, offline, stdlib-only. Determinism: the pipeline depends on live Yahoo + the wall clock (the `complete` flag). Both are
frozen — Yahoo responses are captured under fixtures/yahoo_*.json (trimmed ~7 months), and `today` is
pinned to FROZEN_TODAY. Expected OHLC is anchored to Stooq CSVs (fixtures/stooq_*.csv), the independent
source we cross-checked by hand. The two known ex-dividend weeks differ from Stooq only on the pre-ex
Open/High (Stooq back-adjusts; we keep actual-traded) — asserted explicitly, not silently skipped.
"""
from __future__ import annotations

import json, unittest
from datetime import date

from support import FROZEN_TODAY, TOL, DIVIDEND_WEEKS, load_stooq, pipeline
from market_data.adapters.yahoo import range_for_days
from market_data.indicators import (_period, aggregate, atr_wilder, bars_needed, calendar_days,
                                    last_closed, swing_lows)
from quotes import quote_record


# --------------------------------------------------------------------------- unit: pure functions

class TestPeriod(unittest.TestCase):
    def test_weekly_monday_and_friday(self):
        self.assertEqual(_period("2026-07-24", "w"), ("2026-07-20", date(2026, 7, 24)))
        self.assertEqual(_period("2026-07-20", "w"), ("2026-07-20", date(2026, 7, 24)))

    def test_monthly_and_year_boundary(self):
        self.assertEqual(_period("2026-07-15", "m"), ("2026-07-01", date(2026, 7, 31)))
        self.assertEqual(_period("2026-12-31", "m"), ("2026-12-01", date(2026, 12, 31)))


class TestAggregate(unittest.TestCase):
    def _week(self, complete):
        # Mon-Wed of one week; open=Mon, high=max, low=min, close=Wed, vol=sum
        return [
            {"date": "2026-07-20", "o": 10.0, "h": 12.0, "l": 9.0, "c": 11.0, "v": 100, "complete": True},
            {"date": "2026-07-21", "o": 11.0, "h": 13.0, "l": 10.5, "c": 12.5, "v": 200, "complete": True},
            {"date": "2026-07-22", "o": 12.5, "h": 12.9, "l": 8.5, "c": 9.5, "v": 300, "complete": complete},
        ]

    def test_rollup(self):
        [b] = aggregate(self._week(True), "w", "2026-07-25")
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (10.0, 13.0, 8.5, 9.5, 600))
        self.assertEqual(b["date"], "2026-07-20")

    def test_complete_after_friday(self):   # weekend: week's Friday < today -> complete
        [b] = aggregate(self._week(True), "w", "2026-07-25")
        self.assertTrue(b["complete"])

    def test_incomplete_midweek(self):      # Wednesday: Friday 07-24 not < today 07-22 -> forming
        [b] = aggregate(self._week(False), "w", "2026-07-22")
        self.assertFalse(b["complete"])

    def _full_week(self, friday_complete):
        """Mon-Fri of one week; only Friday's completeness varies (during vs after its session)."""
        days = [{"date": f"2026-07-{20 + i}", "o": 10.0, "h": 12.0, "l": 9.0, "c": 11.0, "v": 100,
                 "complete": True} for i in range(4)]
        days.append({"date": "2026-07-24", "o": 11.0, "h": 13.0, "l": 10.0, "c": 12.0, "v": 100,
                     "complete": friday_complete})
        return days

    def test_week_complete_on_friday_evening(self):
        # Friday after the close: end 07-24 is not < today, but Friday's own bar is closed
        [b] = aggregate(self._full_week(True), "w", "2026-07-24")
        self.assertTrue(b["complete"])
        self.assertEqual(b["c"], 12.0)

    def test_week_forming_during_friday_session(self):
        [b] = aggregate(self._full_week(False), "w", "2026-07-24")
        self.assertFalse(b["complete"])

    def test_month_complete_on_its_last_session_evening(self):
        days = [{"date": "2026-07-31", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10,
                 "complete": True}]
        [b] = aggregate(days, "m", "2026-07-31")
        self.assertTrue(b["complete"])          # month-end reached and that session is closed

    def test_monthly_incomplete_midmonth(self):
        days = [{"date": "2026-07-01", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10, "complete": True}]
        [b] = aggregate(days, "m", "2026-07-25")
        self.assertFalse(b["complete"])     # month-end 07-31 not < 07-25

    def test_rolled_up_bars_carry_no_source(self):
        """Output contract (SKILL.md): daily bars name their source, W1/MN bars do not."""
        days = [dict(b, source="yahoo") for b in self._full_week(True)]
        for interval in ("w", "m"):
            [b] = aggregate(days, interval, "2026-07-25")
            self.assertNotIn("source", b)


class TestCalendarDays(unittest.TestCase):
    def test_rounds_up_at_a_bucket_boundary(self):
        """21 daily bars need 31.5 calendar days: ceil gives 32 and the 3mo bucket; floor would give
        31 and a 1mo fetch one day short."""
        self.assertEqual(calendar_days("d", 21), 32)
        self.assertEqual(range_for_days(32), "3mo")


class TestLastClosed(unittest.TestCase):
    def test_picks_latest_complete(self):
        bars = [
            {"date": "2026-07-20", "c": 1.0, "complete": True},
            {"date": "2026-07-21", "c": 2.0, "complete": True},
            {"date": "2026-07-22", "c": 3.0, "complete": False},   # forming -> skipped
        ]
        self.assertEqual(last_closed(bars), {"date": "2026-07-21", "c": 2.0})


# ----------------------------------------------------------- integration: pipeline vs Stooq oracle

class TestATR(unittest.TestCase):
    """ATR is the one number two skills must agree on (the sizer's 2-3xATR band, the monitor's hard
    2xATR trailing floor), so it is pinned from three sides: arithmetic hand-checkable at n=2,
    independence from --bars, and a regression golden at n=14."""

    # Hand-computable series, n=2. TRs: 1, 1, 3, 5 (the last one via |prevC - L| = |12 - 7|).
    # seed = (1+1)/2 = 1 -> (1x1 + 3)/2 = 2 -> (2x1 + 5)/2 = 3.5
    HAND = [
        {"date": "2026-01-01", "o": 9, "h": 10, "l": 9, "c": 10, "complete": True},
        {"date": "2026-01-02", "o": 10, "h": 11, "l": 10, "c": 11, "complete": True},
        {"date": "2026-01-05", "o": 11, "h": 12, "l": 11, "c": 11.5, "complete": True},
        {"date": "2026-01-06", "o": 12, "h": 13, "l": 10, "c": 12, "complete": True},
        {"date": "2026-01-07", "o": 8, "h": 8, "l": 7, "c": 7.5, "complete": True},
    ]

    def test_hand_computed(self):
        a = atr_wilder(self.HAND, 2)
        self.assertEqual(a["value"], 3.5)
        self.assertEqual((a["n"], a["method"], a["bars_used"], a["as_of"]),
                         (2, "wilder", 5, "2026-01-07"))
        self.assertTrue(a["short_history"])          # 4 TRs < ATR_WARMUP x 2

    def test_forming_bar_excluded(self):
        bars = [dict(b) for b in self.HAND]
        bars[-1]["complete"] = False
        a = atr_wilder(bars, 2)
        self.assertEqual(a["value"], 2.0)           # the value before the forming bar
        self.assertEqual(a["as_of"], "2026-01-06")

    def test_none_when_too_few_candles(self):
        self.assertIsNone(atr_wilder(self.HAND, 14))
        self.assertIsNone(atr_wilder(self.HAND[:2], 2))   # n+1 = 3 needed

    def test_short_history_clears_after_the_runup(self):
        long = [dict(self.HAND[i % len(self.HAND)], date=f"2026-02-{i + 1:02d}") for i in range(12)]
        self.assertFalse(atr_wilder(long, 2)["short_history"])   # 11 TRs > 5 x 2

    def test_bars_needed_covers_the_runup(self):
        self.assertEqual(bars_needed(6, None), 6)               # no ATR -> caller's ask
        self.assertEqual(bars_needed(6, 14), 71)                # 14 x 5 + 1
        self.assertEqual(bars_needed(200, 14), 200)             # caller already wants more

    def test_value_independent_of_returned_slice(self):
        """The regression that matters: a 6-bar morning check and a 70-bar sizing run must read the
        same ATR for the same instrument. Computing it from the returned slice would not."""
        daily = pipeline("PKN", "d")
        vals = {b: quote_record(daily, "d", b, FROZEN_TODAY, 14)["atr"]["value"]
                for b in (6, 20, 70, 150)}
        self.assertEqual(len(set(vals.values())), 1, vals)
        # ...and the test has teeth: the slice-based value really would have differed
        self.assertNotEqual(atr_wilder(daily[-20:], 14)["value"], vals[20])

    def test_golden_pkn_daily_n14(self):
        a = quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY, 14)["atr"]
        self.assertAlmostEqual(a["value"], 3.5264, places=4)
        self.assertEqual((a["as_of"], a["bars_used"], a["interval"]), ("2026-07-24", 71, "daily"))
        self.assertFalse(a["short_history"])

    def test_window_capped_so_a_wider_fetch_cannot_shift_it(self):
        """The other half of the same promise: more history than the run-up must change nothing."""
        daily = pipeline("PKN", "d")                     # 150 complete bars
        self.assertEqual(atr_wilder(daily, 14), atr_wilder(daily[-71:], 14))
        self.assertEqual(atr_wilder(daily, 14)["bars_used"], 71)

    def test_weekly_runs_on_aggregated_candles(self):
        a = quote_record(pipeline("PKN", "d"), "w", 6, FROZEN_TODAY, 14)["atr"]
        self.assertEqual((a["interval"], a["as_of"], a["bars_used"]), ("weekly", "2026-07-20", 32))
        self.assertAlmostEqual(a["value"], 8.8829, places=4)
        self.assertTrue(a["short_history"])         # 31 weekly TRs < 5 x 14 -> flagged, not hidden

    def test_absent_unless_asked(self):
        self.assertNotIn("atr", quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY))

    def test_monthly_fixture_is_too_short_to_report(self):
        self.assertIsNone(quote_record(pipeline("PKN", "d"), "m", 6, FROZEN_TODAY, 14)["atr"])


class TestSwingLows(unittest.TestCase):
    """Which low a trailing stop may anchor to is a rule; whether a session *is* a swing low is
    arithmetic, and two readers of the same chart disagreed on it by two grosz. So it is pinned the
    way ATR is: hand-computable detection, the derived flags, and the window invariant.

    Every confirmed low is reported, lower ones included — the caller applies the rule."""

    # Lows: 10, 9, 8, 9, 10, 9.5, 7, 8, 9. At 2 sessions each side only two qualify:
    # index 2 (8, undercut later by 7) and index 6 (7, never undercut).
    HAND = [{"date": f"2026-01-{i + 1:02d}", "o": lo, "h": lo + 1, "l": lo, "c": lo,
             "complete": True}
            for i, lo in enumerate([10, 9, 8, 9, 10, 9.5, 7, 8, 9])]

    def test_hand_computed_detection(self):
        s = swing_lows(self.HAND, 2)
        self.assertEqual([(r["date"], r["low_price"]) for r in s["detected"]],
                         [("2026-01-03", 8), ("2026-01-07", 7)])

    def test_a_lower_neighbour_on_either_side_disqualifies(self):
        """The rule that keeps a stop off structure price walked through: 9 at index 3 has an 8 on
        its left, 9.5 at index 5 has a 9 on its left. Neither is a swing low, and no number of
        sessions closing after them will change that."""
        dates = [r["date"] for r in swing_lows(self.HAND, 2)["detected"]]
        self.assertNotIn("2026-01-04", dates)
        self.assertNotIn("2026-01-06", dates)

    def test_derived_fields_carry_what_the_rule_needs(self):
        first, second = swing_lows(self.HAND, 2)["detected"]
        # Arrange / Act / Assert — the first row has no predecessor to compare with
        self.assertIsNone(first["higher_than_previous_row_low"])
        self.assertEqual((first["sessions_after_in_window"],
                          first["lowest_low_in_those_sessions"],
                          first["undercut_by_later_session"]), (6, 7, True))
        self.assertEqual((second["higher_than_previous_row_low"],
                          second["sessions_after_in_window"],
                          second["lowest_low_in_those_sessions"],
                          second["undercut_by_later_session"]), (False, 2, 8, False))

    def test_an_exact_retest_is_not_an_undercut(self):
        """`undercut` is a strict `<`: price reaching the low again has not traded through it."""
        # Lows 10, 9, 8, 9, 10, 8, 11 — one swing low at index 2, retested to the grosz at index 5.
        bars = [{"date": f"2026-02-{i + 1:02d}", "o": lo, "h": lo + 1, "l": lo, "c": lo,
                 "complete": True} for i, lo in enumerate([10, 9, 8, 9, 10, 8, 11])]
        row, = swing_lows(bars, 2)["detected"]
        self.assertEqual((row["low_price"], row["lowest_low_in_those_sessions"]), (8, 8))
        self.assertFalse(row["undercut_by_later_session"])

    def test_detectable_through_lags_the_window_by_the_confirmation(self):
        s = swing_lows(self.HAND, 2)
        self.assertEqual((s["window_last_session"], s["detectable_through"]),
                         ("2026-01-09", "2026-01-07"))
        self.assertEqual(swing_lows(self.HAND, 3)["detectable_through"], "2026-01-06")

    def test_forming_bar_excluded(self):
        bars = [dict(b) for b in self.HAND]
        bars[-1]["complete"] = False
        s = swing_lows(bars, 2)
        self.assertEqual(s["window_last_session"], "2026-01-08")
        self.assertEqual(s["detectable_through"], "2026-01-06")
        self.assertEqual([r["date"] for r in s["detected"]], ["2026-01-03"])   # 7 loses its right side

    def test_no_pivot_is_an_empty_list_not_a_missing_key(self):
        rising = [dict(b, l=10 + i, date=f"2026-03-{i + 1:02d}") for i, b in enumerate(self.HAND)]
        self.assertEqual(swing_lows(rising, 2)["detected"], [])

    def test_window_matches_atr_so_both_describe_one_stretch(self):
        """A stop distance in ATR multiples is measured against these lows; if the two blocks read
        different history, the multiple describes structure the ATR never saw."""
        daily = pipeline("PKN", "d")                     # 150 complete bars
        rec = quote_record(daily, "d", 6, FROZEN_TODAY, 14, 2)
        self.assertEqual(rec["swing_lows"]["window_sessions"], rec["atr"]["bars_used"])
        self.assertEqual(swing_lows(daily, 2), swing_lows(daily[-71:], 2))

    def test_result_independent_of_returned_slice(self):
        recs = {b: quote_record(pipeline("PKN", "d"), "d", b, FROZEN_TODAY, 14, 2)["swing_lows"]
                for b in (6, 20, 70, 150)}
        self.assertEqual(len({json.dumps(r, sort_keys=True) for r in recs.values()}), 1)

    def test_golden_pkn_daily(self):
        """Regression pin, not an independently verified one — the arithmetic rides on the hand
        tests above. Spot-checkable in the fixture: 144.20 on 2026-07-17 sits under 144.66 / 144.84
        on its left and 144.88 / 146.28 on its right, with five sessions left in the window."""
        s = quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY, 14, 2)["swing_lows"]
        self.assertEqual((s["candle_interval"], s["window_first_session"],
                          s["window_last_session"], s["window_sessions"], s["detectable_through"]),
                         ("daily", "2026-04-15", "2026-07-24", 71, "2026-07-22"))
        self.assertEqual(len(s["detected"]), 10)
        self.assertEqual(s["detected"][-1], {
            "date": "2026-07-17", "low_price": 144.2, "higher_than_previous_row_low": True,
            "sessions_after_in_window": 5, "lowest_low_in_those_sessions": 144.88,
            "undercut_by_later_session": False})

    def test_weekly_runs_on_aggregated_candles(self):
        s = quote_record(pipeline("PKN", "d"), "w", 6, FROZEN_TODAY, 14, 2)["swing_lows"]
        self.assertEqual(s["candle_interval"], "weekly")
        self.assertLess(s["window_sessions"], 71)        # 150 daily bars aggregate to fewer weeks

    def test_absent_unless_asked(self):
        self.assertNotIn("swing_lows",
                         quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY, 14))

    def test_bars_needed_covers_the_window_without_atr(self):
        self.assertEqual(bars_needed(6, None, None), 6)
        self.assertEqual(bars_needed(6, None, 2), 71)     # swings alone still widen the fetch
        self.assertEqual(bars_needed(6, 14, 2), 71)


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
                ours = {b["date"]: b for b in pipeline(ticker, iv)}
                stq = load_stooq(ticker, iv)
                lo = self.WINDOW[iv]
                overlap = sorted(k for k in set(ours) & set(stq) if k >= lo)
                self.assertGreaterEqual(len(overlap), 3, f"{ticker}/{iv}: too few overlapping periods")
                for k in overlap:
                    o, s = ours[k], stq[k]
                    div_open = DIVIDEND_WEEKS.get((ticker, iv, k))
                    with self.subTest(ticker=ticker, interval=iv, period=k):
                        # Low & Close always match the independent source
                        self.assertAlmostEqual(o["l"], s["l"], delta=TOL(s["l"]))
                        self.assertAlmostEqual(o["c"], s["c"], delta=TOL(s["c"]))
                        if div_open is None:
                            self.assertAlmostEqual(o["o"], s["o"], delta=TOL(s["o"]))
                            self.assertAlmostEqual(o["h"], s["h"], delta=TOL(s["h"]))
                        else:
                            # ex-div week: we report actual-traded open, Stooq back-adjusts it lower
                            self.assertAlmostEqual(o["o"], div_open, delta=TOL(div_open))
                            self.assertGreater(o["o"], s["o"])

    def test_completeness_and_last_closed(self):
        expect = {
            ("PKN", "d"): ("2026-07-24", 156.0), ("PKN", "w"): ("2026-07-20", 156.0),
            ("PKN", "m"): ("2026-06-01", 126.6),
            ("KGH", "d"): ("2026-07-24", 303.5), ("KGH", "w"): ("2026-07-20", 303.5),
            ("KGH", "m"): ("2026-06-01", 331.25),
            ("LPP", "d"): ("2026-07-24", 20140.0), ("LPP", "w"): ("2026-07-20", 20140.0),
            ("LPP", "m"): ("2026-06-01", 18280.0),
        }
        for (ticker, iv), (exp_date, exp_c) in expect.items():
            lc = last_closed(pipeline(ticker, iv))
            with self.subTest(ticker=ticker, interval=iv):
                self.assertEqual(lc["date"], exp_date)
                self.assertAlmostEqual(lc["c"], exp_c, delta=TOL(exp_c))

    def test_current_month_is_forming(self):
        for ticker in ("PKN", "KGH", "LPP"):
            july = {b["date"]: b for b in pipeline(ticker, "m")}["2026-07-01"]
            with self.subTest(ticker=ticker):
                self.assertFalse(july["complete"])   # month-end 07-31 not < FROZEN_TODAY


if __name__ == "__main__":
    unittest.main(verbosity=2)
