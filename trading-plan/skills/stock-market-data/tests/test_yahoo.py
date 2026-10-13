"""market_data.adapters.yahoo — YahooQuotes: resolve, range buckets, cache, session close, backfill.

Offline: Yahoo responses are fixtures (fixtures/yahoo_*.json) or hand-built dicts, served through an
injected fetch; the clock is an injected epoch; throttling goes to an injected sleep. Opt-in live
check (hits Yahoo): RUN_LIVE_SMOKE=1.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from support import FX, FROZEN_TODAY, FROZEN_NOW, GPW_CLOSE, num, price, warsaw, load_yahoo
import quotes
from market_data.adapters import yahoo
from market_data.adapters.symbol_index import SymbolIndex
from market_data.adapters.yahoo import YahooQuotes, range_days, range_for_days
from market_data.indicators import LastClosed, calendar_days, last_closed
from market_data.model import DailyBar, DateRange, Instrument, Quality, Trust, Volume
from market_data.ports import QuoteSourceUnavailableError, Resolution, ResolvedBy, SourceFailure

INDEX = SymbolIndex(quotes.SYMBOLS)
PKN = INDEX.lookup("PKN.PL")                    # mapped: yahoo PKN.WA via symbols.json


def period(days, end=FROZEN_TODAY):
    """A DateRange of `days` calendar days ending on `end` (the cache key's day)."""
    end = date.fromisoformat(end)
    return DateRange(end - timedelta(days=days), end)


# Days that land in the same Yahoo bucket as the labels the pre-adapter tests passed directly.
ONE_MONTH, ONE_YEAR, TWO_YEARS = 20, 300, 500   # "1mo" <= 31, "1y" 184-365, "2y" 366-730


def no_sleep(_seconds):
    pass


class TestResolve(unittest.TestCase):
    def resolve(self, key):
        return YahooQuotes().resolve(INDEX.lookup(key))

    def test_mapped(self):
        r = self.resolve("PKN.PL")
        self.assertEqual((r.symbol, r.by), ("PKN.WA", ResolvedBy.SYMBOLS_JSON))

    def test_rename_guard(self):            # xStation SPL.PL <-> Yahoo EBP.WA, bridged by ISIN
        r = self.resolve("SPL.PL")
        self.assertEqual((r.symbol, r.by), ("EBP.WA", ResolvedBy.SYMBOLS_JSON))

    def test_suffix_guess(self):            # unmapped GPW -> blind .PL->.WA, flagged
        r = self.resolve("ZZZ.PL")
        self.assertEqual((r.symbol, r.by), ("ZZZ.WA", ResolvedBy.SUFFIX_GUESS))

    def test_foreign_passthrough(self):
        r = self.resolve("V80A.DE")
        self.assertEqual((r.symbol, r.by), ("V80A.DE", ResolvedBy.SYMBOLS_JSON))

    def test_unmapped_foreign_passthrough(self):   # V80A.DE above is mapped; this hits the fallback
        r = self.resolve("ZZZ.DE")
        self.assertEqual((r.symbol, r.by), ("ZZZ.DE", ResolvedBy.SUFFIX_GUESS))


class TestRangeFor(unittest.TestCase):
    """#1 — fetch a Yahoo range wide enough to yield the requested bar count (from a daily series).
    Pins the intent behind the daily-history fix: small callers stay cheap; triage gets ~252 D1."""

    def range_for(self, interval, bars):
        return range_for_days(calendar_days(interval, bars))

    def test_daily_small_caller_stays_cheap(self):     # morning check: a few bars -> minimal fetch
        self.assertEqual(self.range_for("d", 6), "1mo")

    def test_daily_mid(self):
        self.assertEqual(self.range_for("d", 60), "3mo")

    def test_daily_triage_gets_a_year_plus(self):      # the unblocker: ~252 D1 needs a wide range
        self.assertEqual(self.range_for("d", 252), "2y")

    def test_weekly_enough_for_screen(self):           # ~40 weekly bars from ~1y of daily
        self.assertEqual(self.range_for("w", 40), "1y")

    def test_monthly_modest(self):
        self.assertEqual(self.range_for("m", 12), "1y")

    def test_never_returns_a_range_shorter_than_needed(self):
        span = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10**9}
        factor = {"d": 1.0, "w": 7, "m": 28}   # loose minimum: a range can't be shorter than the data needs
        for iv in ("d", "w", "m"):
            for bars in (1, 6, 40, 100, 252, 400):
                self.assertGreaterEqual(span[self.range_for(iv, bars)], bars * factor[iv])

    def test_range_days_reads_a_cached_label_back(self):   # the cache compares stored vs wanted range
        self.assertEqual((range_days("1mo"), range_days("1y"), range_days("10y")), (31, 365, 3650))
        self.assertEqual((range_days("max"), range_days("bogus")), (10 ** 9, 10 ** 9))


class TestCache(unittest.TestCase):
    """#3 — opt-in, model-decided cache. With a cache_dir, a same-market-day closed-candle series is
    reused, keyed by the caller's date (period.end) so a new day invalidates it. Fetch is injected (offline) and
    counts its calls: a call is a live fetch, no call is a cache hit."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.raw = load_yahoo("PKN")
        self.calls = []
        def fake_fetch(sym, rng):
            self.calls.append((sym, rng)); return self.raw, None
        self.source = YahooQuotes(fetch=fake_fetch, cache_dir=self.tmp, throttle=0, sleep=no_sleep)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def daily(self, days, end=FROZEN_TODAY):
        return self.source.daily(PKN, period(days, end), now=FROZEN_NOW)

    def test_opt_in_miss_then_hit_same_day(self):
        self.daily(ONE_YEAR)
        self.daily(ONE_YEAR)
        self.assertEqual(self.calls, [("PKN.WA", "1y")])

    def test_new_market_day_refetches(self):
        self.daily(ONE_YEAR, "2026-07-24")
        self.daily(ONE_YEAR, "2026-07-27")
        self.assertEqual(len(self.calls), 2)

    def test_bigger_range_same_day_refetches(self):               # cached history too short
        self.daily(ONE_MONTH)
        self.daily(TWO_YEARS)
        self.assertEqual(self.calls, [("PKN.WA", "1mo"), ("PKN.WA", "2y")])

    def test_smaller_range_same_day_hits(self):                   # cached history covers it
        self.daily(TWO_YEARS)
        self.daily(ONE_MONTH)
        self.assertEqual(self.calls, [("PKN.WA", "2y")])

    def test_live_and_cache_return_identical_bars(self):
        b1 = self.daily(ONE_YEAR).bars
        b2 = self.daily(ONE_YEAR).bars
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(b1, b2)

    def test_entry_written_without_source_comes_back_with_it(self):
        """Stored bars never carry `source` (the adapter labels them after writing, and entries from
        before the adapter look the same); a hit must come out labelled like a live answer."""
        daily = yahoo.build_daily(self.raw, now=FROZEN_NOW)
        self.assertNotIn("source", daily[-1])
        with open(self.tmp / "PKN.WA.json", "w") as f:
            json.dump({"market_date": FROZEN_TODAY, "range": "2y", "gmtoffset": 7200,
                       "session_end": None, "session_over": False, "daily": daily}, f)
        bars = self.daily(ONE_YEAR).bars
        self.assertEqual(self.calls, [])                          # a hit, not a refetch
        self.assertEqual({b.source for b in bars}, {"yahoo"})

    def test_symbol_with_path_separator_is_flattened_into_one_file(self):
        """A vendor symbol containing os.sep must not escape into a subdirectory of the cache."""
        odd = Instrument(key="A/B", isin=None, symbols={"yahoo": "A" + os.sep + "B"})
        self.source.daily(odd, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertEqual(os.listdir(self.tmp), ["A_B.json"])


class TestDaily(unittest.TestCase):
    """The port contract as Yahoo keeps it: bars labelled with their source, a failure to answer
    raised with its raw reason and the resolution made before it, throttling only after real
    requests."""

    def setUp(self):
        self.sleeps = []

    def source(self, fetch, cache_dir=None):
        return YahooQuotes(fetch=fetch, cache_dir=cache_dir, throttle=0, sleep=self.sleeps.append)

    def test_every_bar_carries_source(self):
        s = self.source(lambda sym, rng: (load_yahoo("PKN"), None)).daily(
            PKN, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertTrue(s.bars)
        self.assertEqual({(b.source, b.trust) for b in s.bars}, {("yahoo", Trust.TRUSTED)})
        self.assertEqual(s.resolved, (Resolution("yahoo", "PKN.WA", ResolvedBy.SYMBOLS_JSON),))

    def test_description_is_the_header_text_of_0_4_0(self):    # the output header names the chain
        with open(os.path.join(FX, "cli_0_4_0_PKN.json")) as f:
            self.assertEqual(YahooQuotes.description, json.load(f)["source"])

    def test_unanswered_fetch_raises_with_raw_reason_and_resolution(self):
        src = self.source(lambda sym, rng: (None, "rate_limited"))
        with self.assertRaises(QuoteSourceUnavailableError) as cm:
            src.daily(PKN, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertEqual(cm.exception.failures, (SourceFailure("yahoo", "rate_limited"),))
        self.assertEqual(cm.exception.resolved,
                         (Resolution("yahoo", "PKN.WA", ResolvedBy.SYMBOLS_JSON),))

    def test_not_found_is_unavailable_too(self):         # Yahoo's not_found is not an empty answer
        src = self.source(lambda sym, rng: (None, "not_found"))
        with self.assertRaises(QuoteSourceUnavailableError) as cm:
            src.daily(INDEX.lookup("XXXX.PL"), period(ONE_YEAR), now=FROZEN_NOW)
        self.assertEqual(cm.exception.failures, (SourceFailure("yahoo", "not_found"),))
        self.assertEqual(cm.exception.resolved,
                         (Resolution("yahoo", "XXXX.WA", ResolvedBy.SUFFIX_GUESS),))

    def test_sleeps_once_after_a_live_fetch(self):
        self.source(lambda sym, rng: (load_yahoo("PKN"), None)).daily(
            PKN, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertEqual(len(self.sleeps), 1)

    def test_does_not_sleep_after_a_cache_hit(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            src = self.source(lambda sym, rng: (load_yahoo("PKN"), None), cache_dir=tmp)
            src.daily(PKN, period(ONE_YEAR), now=FROZEN_NOW)          # live: writes the entry
            self.sleeps.clear()
            src.daily(PKN, period(ONE_YEAR), now=FROZEN_NOW)          # hit
            self.assertEqual(self.sleeps, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_does_not_sleep_after_a_failure(self):
        with self.assertRaises(QuoteSourceUnavailableError):
            self.source(lambda sym, rng: (None, "http_503")).daily(
                PKN, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertEqual(self.sleeps, [])


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
        return yahoo.build_daily(self.raw(close_epoch), now=now)[-1]

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
        b = yahoo.build_daily(self.raw(None), now=warsaw(2026, 7, 28, 23 * 3600))[-1]
        self.assertFalse(b["complete"])

    def test_market_tz_not_machine_tz(self):
        """Machine in the Americas, market in Warsaw: at 21:00 UTC it is already 07-29 in Warsaw, so
        the 07-28 bar is a past date — complete regardless of any close time."""
        b = yahoo.build_daily(self.raw(warsaw(2026, 7, 28, GPW_CLOSE)),
                              now=warsaw(2026, 7, 29, 3 * 3600))[-1]
        self.assertEqual(b["date"], "2026-07-28")
        self.assertTrue(b["complete"])

    def test_last_closed_is_todays_candle_after_the_close(self):
        rows = yahoo.build_daily(self.raw(warsaw(2026, 7, 28, GPW_CLOSE)),
                                 now=warsaw(2026, 7, 28, 23 * 3600))
        self.assertEqual(last_closed([yahoo.to_bar(r) for r in rows]),
                         LastClosed(self.DAY, 144.84, Quality.GOOD))

    def _cached(self, write_at, read_at, midday, final):
        """Write the cache at `write_at` from `midday`, read it at `read_at` (live would give `final`).
        Returns (bars, "live"|"cache") from the second call; "live" iff it reached the fetch."""
        tmp = Path(tempfile.mkdtemp())
        day = period(ONE_MONTH, "2026-07-28")
        try:
            YahooQuotes(fetch=lambda y, r: (midday, None), cache_dir=tmp, throttle=0,
                        sleep=no_sleep).daily(PKN, day, now=write_at)
            calls = []
            def fetch(y, r):
                calls.append(y); return final, None
            s = YahooQuotes(fetch=fetch, cache_dir=tmp, throttle=0,
                            sleep=no_sleep).daily(PKN, day, now=read_at)
            return list(s.bars), ("live" if calls else "cache")
        finally:
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
        self.assertEqual(num(bars[-1].close), 144.84)       # the real close, not the snapshot
        self.assertTrue(bars[-1].complete)

    def test_cache_written_after_the_close_is_reused(self):
        """Same side of the close: the candle is final, so the entry stays good (that's the point of
        --cache — an evening re-read must not refetch)."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        final, other = self.raw(close, price=144.84), self.raw(close, price=999.0)
        bars, src = self._cached(warsaw(2026, 7, 28, 18 * 3600), warsaw(2026, 7, 28, 23 * 3600),
                                 final, other)
        self.assertEqual(src, "cache")
        self.assertEqual(num(bars[-1].close), 144.84)
        self.assertTrue(bars[-1].complete)

    def test_midsession_cache_is_reused_within_the_session(self):
        """Two mid-session reads still hit: --cache means 'reuse the day's candles', and the forming
        bar must be dropped by the caller anyway — its flag stays false."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        midday = self.raw(close, price=147.2)
        bars, src = self._cached(warsaw(2026, 7, 28, 11 * 3600), warsaw(2026, 7, 28, 12 * 3600),
                                 midday, self.raw(close, price=148.0))
        self.assertEqual(src, "cache")
        self.assertFalse(bars[-1].complete)

    def test_preopen_cache_is_not_reused_after_the_close(self):
        """Written before the open (no bar for today yet) -> after the close it must refetch, or the
        evening run would see yesterday's candle as the newest one."""
        close = warsaw(2026, 7, 28, GPW_CLOSE)
        _, src = self._cached(warsaw(2026, 7, 28, 7 * 3600), warsaw(2026, 7, 28, 23 * 3600),
                              self.raw(close, price=151.0), self.raw(close, price=144.84))
        self.assertEqual(src, "live")

    def test_cache_hit_restamps_complete_against_the_read_clock(self):
        """`complete` is never trusted from disk. With no trading period from the vendor, an evening
        write stores the day's bar as forming (conservative); read back after the market's midnight
        by a caller whose own date is still 07-28, the entry is a hit, and that bar is now a past
        market date, so the hit must report it closed."""
        write_at, read_at = warsaw(2026, 7, 28, 23 * 3600), warsaw(2026, 7, 29, 1 * 3600)
        self.assertFalse(yahoo.build_daily(self.raw(None), now=write_at)[-1]["complete"])
        bars, src = self._cached(write_at, read_at, self.raw(None), self.raw(None, price=999.0))
        self.assertEqual(src, "cache")
        self.assertEqual(bars[-1].session, self.DAY)
        self.assertEqual(num(bars[-1].close), 144.84)
        self.assertTrue(bars[-1].complete)


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
        bars = yahoo.build_daily(r, today=FROZEN_TODAY)
        self.assertEqual(bars[-1]["date"], "2026-07-24")
        self.assertEqual(bars[-1]["c"], 156.0)          # backfilled
        self.assertTrue(bars[-1]["complete"])           # 07-24 < 07-25


class TestToBar(unittest.TestCase):
    """A row of build_daily (or of the cache) as the port's DailyBar. Whatever Yahoo sends, this
    must not raise: an exception out of an adapter is a bug, not an answer."""

    ROW = {"date": "2026-07-24", "o": 155.7, "h": 156.3, "l": 153.42, "c": 156.0, "v": 1516341,
           "complete": True}

    def test_row_becomes_a_trusted_yahoo_bar(self):
        self.assertEqual(yahoo.to_bar(self.ROW),
                         DailyBar(date(2026, 7, 24), price(155.7), price(156.3), price(153.42),
                                  price(156.0), Volume(1516341), complete=True, source="yahoo",
                                  trust=Trust.TRUSTED))

    def test_a_price_reads_back_as_the_same_float(self):
        bar = yahoo.to_bar(dict(self.ROW, c=144.8400001))
        self.assertEqual(num(bar.close), 144.84)            # rounded to 4 places, like build_daily

    def test_zero_prices_from_yahoo_become_gaps_not_an_exception(self):
        """Yahoo sometimes sends 0 for open/high/low. A Price is positive, so 0 is no price."""
        bar = yahoo.to_bar(dict(self.ROW, o=0, h=0.0, l=0.00001))   # the last rounds to 0.0
        self.assertEqual((bar.open, bar.high, bar.low, bar.close),
                         (None, None, None, price(156.0)))

    def test_negative_or_non_finite_numbers_become_gaps(self):
        bar = yahoo.to_bar(dict(self.ROW, o=-1.0, h=float("nan"), l=float("inf"), v=-5))
        self.assertEqual((bar.open, bar.high, bar.low, bar.volume), (None, None, None, None))
        self.assertIsNone(yahoo.to_bar(dict(self.ROW, v=float("inf"))).volume)

    def test_a_whole_number_close_prints_as_a_float(self):
        self.assertEqual(quotes.to_json(yahoo.to_bar(dict(self.ROW, c=156)))["c"], 156.0)

    def test_zero_prices_through_the_port(self):
        r = load_yahoo("PKN")
        q = r["indicators"]["quote"][0]
        for k in ("open", "high", "low"):
            q[k] = [0 for _ in q[k]]
        s = YahooQuotes(fetch=lambda sym, rng: (r, None), throttle=0, sleep=no_sleep).daily(
            PKN, period(ONE_YEAR), now=FROZEN_NOW)
        self.assertTrue(s.bars)
        self.assertEqual({(b.open, b.high, b.low) for b in s.bars}, {(None, None, None)})
        self.assertTrue(all(b.close is not None for b in s.bars))


@unittest.skipUnless(os.environ.get("RUN_LIVE_SMOKE"), "set RUN_LIVE_SMOKE=1 to hit live Yahoo")
class TestLiveSmoke(unittest.TestCase):
    def test_yahoo_response_shape_unchanged(self):
        r, reason = yahoo.fetch_chart("PKN.WA", "1mo")
        self.assertIsNone(reason, f"fetch failed: {reason}")
        self.assertIn("regularMarketPrice", r["meta"])
        self.assertIn("close", r["indicators"]["quote"][0])
        bars = yahoo.build_daily(r)
        self.assertTrue(bars and bars[-1]["c"] is not None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
