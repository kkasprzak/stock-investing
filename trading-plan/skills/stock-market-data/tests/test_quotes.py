#!/usr/bin/env python3
"""Regression tests for quotes.py — deterministic, offline, stdlib-only.

Run:  python3 -m unittest discover .claude/skills/stock-market-data/tests
  or: python3 .claude/skills/stock-market-data/tests/test_quotes.py
Opt-in live check (hits Yahoo): RUN_LIVE_SMOKE=1 python3 -m unittest ...

Determinism: the pipeline depends on live Yahoo + the wall clock (the `complete` flag). Both are
frozen — Yahoo responses are captured under fixtures/yahoo_*.json (trimmed ~7 months), and `today` is
pinned to FROZEN_TODAY. Expected OHLC is anchored to Stooq CSVs (fixtures/stooq_*.csv), the independent
source we cross-checked by hand. The two known ex-dividend weeks differ from Stooq only on the pre-ex
Open/High (Stooq back-adjusts; we keep actual-traded) — asserted explicitly, not silently skipped.
"""
import os, sys, csv, json, tempfile, shutil, unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import quotes  # noqa: E402

FROZEN_TODAY = "2026-07-25"          # a Saturday; last session in fixtures is Fri 2026-07-24
FROZEN_NOW = 1784973600              # that Saturday 12:00 Warsaw — epoch for session-close checks
GPW_CLOSE = 17 * 3600 + 5 * 60       # WSE regular session ends 17:05 local (per Yahoo's own calendar)


def warsaw(y, m, d, secs):
    """Epoch for a Warsaw wall-clock moment (CEST, +2h) — session-boundary fixtures."""
    return (date(y, m, d) - date(1970, 1, 1)).days * 86400 + secs - 7200

TOL = lambda v: max(0.01, 0.0005 * abs(v))   # noqa: E731  price tolerance (rounding)

# Ex-dividend weeks: Stooq back-adjusts the pre-ex Open/High; we keep actual-traded (unadjusted).
# (ticker, interval, period_label) -> known unadjusted Open we must still report.
DIVIDEND_WEEKS = {
    ("PKN", "w", "2026-06-15"): 146.0,   # PKN ex-div 2026-06-17 (8.00)
    ("KGH", "w", "2026-06-22"): 375.0,   # KGH ex-div 2026-06-24 (1.50)
}


def load_yahoo(ticker):
    with open(os.path.join(FX, f"yahoo_{ticker}.json")) as f:
        return json.load(f)


def load_stooq(ticker, interval):
    """{our_date_label: {o,h,l,c}} from a Stooq CSV, aligned to our labels:
    daily = same date; weekly Sunday -> that week's Monday; monthly month-end -> 1st."""
    path = os.path.join(FX, f"stooq_{ticker.lower()}_{interval}.csv")
    out = {}
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        d = date.fromisoformat(row["Data"])
        if interval == "d":
            key = d.isoformat()
        elif interval == "w":
            key = (d - timedelta(days=6)).isoformat()
        else:
            key = f"{d.year}-{d.month:02d}-01"
        out[key] = {"o": float(row["Otwarcie"]), "h": float(row["Najwyzszy"]),
                    "l": float(row["Najnizszy"]), "c": float(row["Zamkniecie"])}
    return out


def pipeline(ticker, interval):
    """Run the offline pipeline for a fixture at FROZEN_TODAY -> list of bars."""
    daily = quotes.build_daily(load_yahoo(ticker), today=FROZEN_TODAY, now=FROZEN_NOW)
    if interval == "d":
        return daily
    return quotes.aggregate(daily, interval, FROZEN_TODAY)


# --------------------------------------------------------------------------- unit: pure functions

class TestResolve(unittest.TestCase):
    def setUp(self):
        self.idx = quotes.load_index()

    def test_mapped(self):
        self.assertEqual(quotes.resolve("PKN.PL", self.idx), ("PKN.WA", "symbols.json"))

    def test_rename_guard(self):            # xStation SPL.PL <-> Yahoo EBP.WA, bridged by ISIN
        self.assertEqual(quotes.resolve("SPL.PL", self.idx), ("EBP.WA", "symbols.json"))

    def test_suffix_guess(self):            # unmapped GPW -> blind .PL->.WA, flagged
        self.assertEqual(quotes.resolve("ZZZ.PL", self.idx), ("ZZZ.WA", "suffix_guess"))

    def test_foreign_passthrough(self):
        self.assertEqual(quotes.resolve("V80A.DE", self.idx), ("V80A.DE", "symbols.json"))


class TestBrokerSymbol(unittest.TestCase):
    """The execution-venue ticker a caller needs to name a state-file row. Never guessed."""

    def setUp(self):
        self.idx = quotes.load_index()

    def test_by_isin(self):                 # sourcing keys by ISIN, writes the broker ticker
        self.assertEqual(quotes.broker_symbol("PLPKN0000018", self.idx), "PKN.PL")

    def test_by_broker_ticker(self):        # already a broker ticker -> itself
        self.assertEqual(quotes.broker_symbol("PKN.PL", self.idx), "PKN.PL")

    def test_rename_guard(self):            # broker keeps the old root; Yahoo moved off it
        self.assertEqual(quotes.broker_symbol("PLCCC0000016", self.idx), "CCC.PL")

    def test_unlisted_is_none(self):        # mapped instrument the broker does not offer
        self.assertIsNone(quotes.broker_symbol("PLROBYG00321", self.idx))

    def test_unmapped_is_none(self):        # never inferred from the GPW root
        self.assertIsNone(quotes.broker_symbol("ZZZ.PL", self.idx))


class TestRangeFor(unittest.TestCase):
    """#1 — fetch a Yahoo range wide enough to yield the requested bar count (from a daily series).
    Pins the intent behind the daily-history fix: small callers stay cheap; triage gets ~252 D1."""

    def test_daily_small_caller_stays_cheap(self):     # morning check: a few bars -> minimal fetch
        self.assertEqual(quotes.range_for("d", 6), "1mo")

    def test_daily_mid(self):
        self.assertEqual(quotes.range_for("d", 60), "3mo")

    def test_daily_triage_gets_a_year_plus(self):      # the unblocker: ~252 D1 needs a wide range
        self.assertEqual(quotes.range_for("d", 252), "2y")

    def test_weekly_enough_for_screen(self):           # ~40 weekly bars from ~1y of daily
        self.assertEqual(quotes.range_for("w", 40), "1y")

    def test_monthly_modest(self):
        self.assertEqual(quotes.range_for("m", 12), "1y")

    def test_never_returns_a_range_shorter_than_needed(self):
        span = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10**9}
        factor = {"d": 1.0, "w": 7, "m": 28}   # loose minimum: a range can't be shorter than the data needs
        for iv in ("d", "w", "m"):
            for bars in (1, 6, 40, 100, 252, 400):
                self.assertGreaterEqual(span[quotes.range_for(iv, bars)], bars * factor[iv])


class TestCache(unittest.TestCase):
    """#3 — opt-in, model-decided cache. Default (no --cache) is always-live (fail-safe); with
    caching enabled, a same-market-day closed-candle series is reused, keyed by market date so a
    new session invalidates it. Fetch is injected (offline); CACHE_DIR is a temp dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = quotes.CACHE_DIR
        quotes.CACHE_DIR = self.tmp
        self.raw = load_yahoo("PKN")
        self.calls = []
        def fake_fetch(yahoo, rng):
            self.calls.append((yahoo, rng)); return self.raw, None
        self.fetch = fake_fetch

    def tearDown(self):
        quotes.CACHE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_is_always_live_and_writes_nothing(self):     # fail-safe default
        quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, False, self.fetch)
        _, src = quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, False, self.fetch)
        self.assertEqual(src, "live")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(os.listdir(self.tmp), [])                # nothing cached

    def test_opt_in_miss_then_hit_same_day(self):
        _, s1 = quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, True, self.fetch)
        _, s2 = quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, True, self.fetch)
        self.assertEqual((s1, s2), ("live", "cache"))
        self.assertEqual(len(self.calls), 1)

    def test_new_market_day_refetches(self):
        quotes.get_daily("PKN.WA", "1y", "2026-07-24", True, self.fetch)
        _, s2 = quotes.get_daily("PKN.WA", "1y", "2026-07-27", True, self.fetch)
        self.assertEqual(s2, "live")
        self.assertEqual(len(self.calls), 2)

    def test_bigger_range_same_day_refetches(self):               # cached history too short
        quotes.get_daily("PKN.WA", "1mo", FROZEN_TODAY, True, self.fetch)
        _, s2 = quotes.get_daily("PKN.WA", "2y", FROZEN_TODAY, True, self.fetch)
        self.assertEqual(s2, "live")
        self.assertEqual(len(self.calls), 2)

    def test_smaller_range_same_day_hits(self):                   # cached history covers it
        quotes.get_daily("PKN.WA", "2y", FROZEN_TODAY, True, self.fetch)
        _, s2 = quotes.get_daily("PKN.WA", "1mo", FROZEN_TODAY, True, self.fetch)
        self.assertEqual(s2, "cache")
        self.assertEqual(len(self.calls), 1)

    def test_live_and_cache_return_identical_bars(self):
        b1, _ = quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, True, self.fetch)
        b2, _ = quotes.get_daily("PKN.WA", "1y", FROZEN_TODAY, True, self.fetch)
        self.assertEqual(b1, b2)


class TestSessionClose(unittest.TestCase):
    """The `complete` flag must track the venue's session, not the calendar date. Before the fix an
    evening run on a closed exchange still reported today's candle as forming, which is exactly the
    candle a daily close check has to decide on."""

    DAY = date(2026, 7, 28)          # a Tuesday, WSE trading

    def raw(self, close_epoch=None, price=144.84):
        """One-bar WSE response for self.DAY; close_epoch = that day's regular session end."""
        period = ({"regular": {"start": close_epoch - 8 * 3600, "end": close_epoch}}
                  if close_epoch is not None else None)
        meta = {"gmtoffset": 7200, "regularMarketPrice": price,
                "regularMarketTime": warsaw(2026, 7, 28, 17 * 3600)}
        if period:
            meta["currentTradingPeriod"] = period
        return {"meta": meta,
                "timestamp": [warsaw(2026, 7, 28, 9 * 3600)],
                "indicators": {"quote": [{"open": [149.48], "high": [150.8], "low": [144.5],
                                          "close": [price], "volume": [1631410]}]}}

    def bar_at(self, secs, close_epoch=warsaw(2026, 7, 28, GPW_CLOSE)):
        now = warsaw(2026, 7, 28, secs)
        return quotes.build_daily(self.raw(close_epoch), now=now)[-1]

    def test_forming_during_the_session(self):
        b = self.bar_at(12 * 3600)                       # 12:00, market open
        self.assertEqual(b["date"], "2026-07-28")
        self.assertFalse(b["complete"])

    def test_complete_right_after_the_close(self):
        self.assertTrue(self.bar_at(GPW_CLOSE + 60)["complete"])

    def test_complete_in_the_evening(self):              # the bug: 23:03 local, GPW shut for 6h
        self.assertTrue(self.bar_at(23 * 3600)["complete"])

    def test_not_complete_one_second_before_the_close(self):
        self.assertFalse(self.bar_at(GPW_CLOSE - 1)["complete"])

    def test_missing_trading_period_stays_conservative(self):
        # vendor omits currentTradingPeriod -> we can't prove the close -> keep calling it forming
        b = quotes.build_daily(self.raw(None), now=warsaw(2026, 7, 28, 23 * 3600))[-1]
        self.assertFalse(b["complete"])

    def test_market_tz_not_machine_tz(self):
        """Machine in the Americas, market in Warsaw: at 21:00 UTC it is already 07-29 in Warsaw, so
        the 07-28 bar is a past date — complete regardless of any close time."""
        b = quotes.build_daily(self.raw(warsaw(2026, 7, 28, GPW_CLOSE)),
                               now=warsaw(2026, 7, 29, 3 * 3600))[-1]
        self.assertEqual(b["date"], "2026-07-28")
        self.assertTrue(b["complete"])

    def test_last_closed_is_todays_candle_after_the_close(self):
        bars = quotes.build_daily(self.raw(warsaw(2026, 7, 28, GPW_CLOSE)),
                                  now=warsaw(2026, 7, 28, 23 * 3600))
        self.assertEqual(quotes.last_closed(bars), {"date": "2026-07-28", "c": 144.84})

    def _cached(self, write_at, read_at, midday, final):
        """Write the cache at `write_at` from `midday`, read it at `read_at` (live would give `final`).
        Returns (bars, src) from the second call."""
        tmp = tempfile.mkdtemp()
        orig, quotes.CACHE_DIR = quotes.CACHE_DIR, tmp
        try:
            quotes.get_daily("PKN.WA", "1mo", "2026-07-28", True,
                             lambda y, r: (midday, None), now=write_at)
            return quotes.get_daily("PKN.WA", "1mo", "2026-07-28", True,
                                    lambda y, r: (final, None), now=read_at)
        finally:
            quotes.CACHE_DIR = orig
            shutil.rmtree(tmp, ignore_errors=True)

    def test_midsession_cache_is_not_reused_after_the_close(self):
        """The forming bar's OHLC keeps moving until the close, so a series cached mid-session is
        stale the moment the session ends — reusing it would report a midday snapshot as the day's
        closed candle (the dangerous direction: a wrong number dressed as a fact)."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        midday, final = self.raw(close, price=147.2), self.raw(close, price=144.84)
        bars, src = self._cached(warsaw(2026, 7, 28, 12 * 3600), warsaw(2026, 7, 28, 23 * 3600),
                                 midday, final)
        self.assertEqual(src, "live")                       # crossing the close invalidates
        self.assertEqual(bars[-1]["c"], 144.84)             # the real close, not the snapshot
        self.assertTrue(bars[-1]["complete"])

    def test_cache_written_after_the_close_is_reused(self):
        """Same side of the close: the candle is final, so the entry stays good (that's the point of
        --cache — an evening re-read must not refetch)."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        final, other = self.raw(close, price=144.84), self.raw(close, price=999.0)
        bars, src = self._cached(warsaw(2026, 7, 28, 18 * 3600), warsaw(2026, 7, 28, 23 * 3600),
                                 final, other)
        self.assertEqual(src, "cache")
        self.assertEqual(bars[-1]["c"], 144.84)
        self.assertTrue(bars[-1]["complete"])

    def test_midsession_cache_is_reused_within_the_session(self):
        """Two mid-session reads still hit: --cache means 'reuse the day's candles', and the forming
        bar must be dropped by the caller anyway — its flag stays false."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        midday = self.raw(close, price=147.2)
        bars, src = self._cached(warsaw(2026, 7, 28, 11 * 3600), warsaw(2026, 7, 28, 12 * 3600),
                                 midday, self.raw(close, price=148.0))
        self.assertEqual(src, "cache")
        self.assertFalse(bars[-1]["complete"])

    def test_preopen_cache_is_not_reused_after_the_close(self):
        """Written before the open (no bar for today yet) -> after the close it must refetch, or the
        evening run would see yesterday's candle as the newest one."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        _, src = self._cached(warsaw(2026, 7, 28, 7 * 3600), warsaw(2026, 7, 28, 23 * 3600),
                              self.raw(close, price=151.0), self.raw(close, price=144.84))
        self.assertEqual(src, "live")


class TestPeriod(unittest.TestCase):
    def test_weekly_monday_and_friday(self):
        self.assertEqual(quotes._period("2026-07-24", "w"), ("2026-07-20", date(2026, 7, 24)))
        self.assertEqual(quotes._period("2026-07-20", "w"), ("2026-07-20", date(2026, 7, 24)))

    def test_monthly_and_year_boundary(self):
        self.assertEqual(quotes._period("2026-07-15", "m"), ("2026-07-01", date(2026, 7, 31)))
        self.assertEqual(quotes._period("2026-12-31", "m"), ("2026-12-01", date(2026, 12, 31)))


class TestAggregate(unittest.TestCase):
    def _week(self, complete):
        # Mon-Wed of one week; open=Mon, high=max, low=min, close=Wed, vol=sum
        return [
            {"date": "2026-07-20", "o": 10.0, "h": 12.0, "l": 9.0, "c": 11.0, "v": 100, "complete": True},
            {"date": "2026-07-21", "o": 11.0, "h": 13.0, "l": 10.5, "c": 12.5, "v": 200, "complete": True},
            {"date": "2026-07-22", "o": 12.5, "h": 12.9, "l": 8.5, "c": 9.5, "v": 300, "complete": complete},
        ]

    def test_rollup(self):
        [b] = quotes.aggregate(self._week(True), "w", "2026-07-25")
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (10.0, 13.0, 8.5, 9.5, 600))
        self.assertEqual(b["date"], "2026-07-20")

    def test_complete_after_friday(self):   # weekend: week's Friday < today -> complete
        [b] = quotes.aggregate(self._week(True), "w", "2026-07-25")
        self.assertTrue(b["complete"])

    def test_incomplete_midweek(self):      # Wednesday: Friday 07-24 not < today 07-22 -> forming
        [b] = quotes.aggregate(self._week(False), "w", "2026-07-22")
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
        [b] = quotes.aggregate(self._full_week(True), "w", "2026-07-24")
        self.assertTrue(b["complete"])
        self.assertEqual(b["c"], 12.0)

    def test_week_forming_during_friday_session(self):
        [b] = quotes.aggregate(self._full_week(False), "w", "2026-07-24")
        self.assertFalse(b["complete"])

    def test_month_complete_on_its_last_session_evening(self):
        days = [{"date": "2026-07-31", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10,
                 "complete": True}]
        [b] = quotes.aggregate(days, "m", "2026-07-31")
        self.assertTrue(b["complete"])          # month-end reached and that session is closed

    def test_monthly_incomplete_midmonth(self):
        days = [{"date": "2026-07-01", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10, "complete": True}]
        [b] = quotes.aggregate(days, "m", "2026-07-25")
        self.assertFalse(b["complete"])     # month-end 07-31 not < 07-25


class TestLastClosed(unittest.TestCase):
    def test_picks_latest_complete(self):
        bars = [
            {"date": "2026-07-20", "c": 1.0, "complete": True},
            {"date": "2026-07-21", "c": 2.0, "complete": True},
            {"date": "2026-07-22", "c": 3.0, "complete": False},   # forming -> skipped
        ]
        self.assertEqual(quotes.last_closed(bars), {"date": "2026-07-21", "c": 2.0})


class TestBuildDailyBackfill(unittest.TestCase):
    def test_trailing_null_close_backfilled_from_regularmarketprice(self):
        # two bars; the latest trails close=None -> patched from regularMarketPrice, dated by rmt
        r = {
            "meta": {"gmtoffset": 7200, "regularMarketPrice": 156.0,
                     "regularMarketTime": int((date(2026, 7, 24) - date(1970, 1, 1)).days * 86400) + 12 * 3600},
            "timestamp": [int((date(2026, 7, 23) - date(1970, 1, 1)).days * 86400) + 7 * 3600,
                          int((date(2026, 7, 24) - date(1970, 1, 1)).days * 86400) + 7 * 3600],
            "indicators": {"quote": [{"open": [152.0, 155.7], "high": [156.5, 156.3],
                                      "low": [151.92, 153.42], "close": [155.86, None], "volume": [1, 2]}]},
        }
        bars = quotes.build_daily(r, today=FROZEN_TODAY)
        self.assertEqual(bars[-1]["date"], "2026-07-24")
        self.assertEqual(bars[-1]["c"], 156.0)          # backfilled
        self.assertTrue(bars[-1]["complete"])           # 07-24 < 07-25


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
        a = quotes.atr_wilder(self.HAND, 2)
        self.assertEqual(a["value"], 3.5)
        self.assertEqual((a["n"], a["method"], a["bars_used"], a["as_of"]),
                         (2, "wilder", 5, "2026-01-07"))
        self.assertTrue(a["short_history"])          # 4 TRs < ATR_WARMUP x 2

    def test_forming_bar_excluded(self):
        bars = [dict(b) for b in self.HAND]
        bars[-1]["complete"] = False
        a = quotes.atr_wilder(bars, 2)
        self.assertEqual(a["value"], 2.0)           # the value before the forming bar
        self.assertEqual(a["as_of"], "2026-01-06")

    def test_none_when_too_few_candles(self):
        self.assertIsNone(quotes.atr_wilder(self.HAND, 14))
        self.assertIsNone(quotes.atr_wilder(self.HAND[:2], 2))   # n+1 = 3 needed

    def test_short_history_clears_after_the_runup(self):
        long = [dict(self.HAND[i % len(self.HAND)], date=f"2026-02-{i + 1:02d}") for i in range(12)]
        self.assertFalse(quotes.atr_wilder(long, 2)["short_history"])   # 11 TRs > 5 x 2

    def test_bars_needed_covers_the_runup(self):
        self.assertEqual(quotes.bars_needed(6, None), 6)               # no ATR -> caller's ask
        self.assertEqual(quotes.bars_needed(6, 14), 71)                # 14 x 5 + 1
        self.assertEqual(quotes.bars_needed(200, 14), 200)             # caller already wants more

    def test_value_independent_of_returned_slice(self):
        """The regression that matters: a 6-bar morning check and a 70-bar sizing run must read the
        same ATR for the same instrument. Computing it from the returned slice would not."""
        daily = pipeline("PKN", "d")
        vals = {b: quotes.quote_record(daily, "d", b, FROZEN_TODAY, 14)["atr"]["value"]
                for b in (6, 20, 70, 150)}
        self.assertEqual(len(set(vals.values())), 1, vals)
        # ...and the test has teeth: the slice-based value really would have differed
        self.assertNotEqual(quotes.atr_wilder(daily[-20:], 14)["value"], vals[20])

    def test_golden_pkn_daily_n14(self):
        a = quotes.quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY, 14)["atr"]
        self.assertAlmostEqual(a["value"], 3.5264, places=4)
        self.assertEqual((a["as_of"], a["bars_used"], a["interval"]), ("2026-07-24", 71, "1d"))
        self.assertFalse(a["short_history"])

    def test_window_capped_so_a_wider_fetch_cannot_shift_it(self):
        """The other half of the same promise: more history than the run-up must change nothing."""
        daily = pipeline("PKN", "d")                     # 150 complete bars
        self.assertEqual(quotes.atr_wilder(daily, 14), quotes.atr_wilder(daily[-71:], 14))
        self.assertEqual(quotes.atr_wilder(daily, 14)["bars_used"], 71)

    def test_weekly_runs_on_aggregated_candles(self):
        a = quotes.quote_record(pipeline("PKN", "d"), "w", 6, FROZEN_TODAY, 14)["atr"]
        self.assertEqual((a["interval"], a["as_of"], a["bars_used"]), ("1wk", "2026-07-20", 32))
        self.assertAlmostEqual(a["value"], 8.8829, places=4)
        self.assertTrue(a["short_history"])         # 31 weekly TRs < 5 x 14 -> flagged, not hidden

    def test_absent_unless_asked(self):
        self.assertNotIn("atr", quotes.quote_record(pipeline("PKN", "d"), "d", 6, FROZEN_TODAY))

    def test_monthly_fixture_is_too_short_to_report(self):
        self.assertIsNone(quotes.quote_record(pipeline("PKN", "d"), "m", 6, FROZEN_TODAY, 14)["atr"])


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
            lc = quotes.last_closed(pipeline(ticker, iv))
            with self.subTest(ticker=ticker, interval=iv):
                self.assertEqual(lc["date"], exp_date)
                self.assertAlmostEqual(lc["c"], exp_c, delta=TOL(exp_c))

    def test_current_month_is_forming(self):
        for ticker in ("PKN", "KGH", "LPP"):
            july = {b["date"]: b for b in pipeline(ticker, "m")}["2026-07-01"]
            with self.subTest(ticker=ticker):
                self.assertFalse(july["complete"])   # month-end 07-31 not < FROZEN_TODAY


# ---------------------------------------------------------------------- opt-in live check (network)

@unittest.skipUnless(os.environ.get("RUN_LIVE_SMOKE"), "set RUN_LIVE_SMOKE=1 to hit live Yahoo")
class TestLiveSmoke(unittest.TestCase):
    def test_yahoo_response_shape_unchanged(self):
        r, reason = quotes.fetch_chart("PKN.WA", "1mo")
        self.assertIsNone(reason, f"fetch failed: {reason}")
        self.assertIn("regularMarketPrice", r["meta"])
        self.assertIn("close", r["indicators"]["quote"][0])
        bars = quotes.build_daily(r)
        self.assertTrue(bars and bars[-1]["c"] is not None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
