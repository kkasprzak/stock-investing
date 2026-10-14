"""market_data.adapters.yahoo — YahooQuotes: resolve, range buckets, session close, backfill.

Offline: Yahoo responses are fixtures (fixtures/yahoo_*.json) or hand-built dicts, served through an
injected fetch; the clock is an injected epoch; throttling goes to an injected sleep. Opt-in live
check (hits Yahoo): RUN_LIVE_SMOKE=1.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date, timedelta

from support import FX, FROZEN_TODAY, FROZEN_NOW, GPW_CLOSE, num, price, warsaw, load_yahoo
import quotes
from market_data.adapters import yahoo
from market_data.adapters.symbol_index import SymbolIndex
from market_data.adapters.yahoo import YahooQuotes, range_for_days
from market_data.indicators import LastClosed, calendar_days, last_closed
from market_data.model import DailyBar, DateRange, Quality, Trust, Volume
from market_data.ports import QuoteSourceUnavailableError, Resolution, ResolvedBy, SourceFailure

INDEX = SymbolIndex(quotes.SYMBOLS)
PKN = INDEX.lookup("PKN.PL")                    # mapped: yahoo PKN.WA via symbols.json


def period(days, end=FROZEN_TODAY):
    """A DateRange of `days` calendar days ending on `end`."""
    end = date.fromisoformat(end)
    return DateRange(end - timedelta(days=days), end)


# Days that land in the same Yahoo bucket as the labels the pre-adapter tests passed directly.
ONE_MONTH, ONE_YEAR = 20, 300                   # "1mo" <= 31, "1y" 184-365


def no_sleep(_seconds):
    pass


UNUSABLE = Trust.untrusted("unusable_price")


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


class TestDaily(unittest.TestCase):
    """The port contract as Yahoo keeps it: bars labelled with their source, a failure to answer
    raised with its raw reason and the resolution made before it, throttling only after real
    requests."""

    def setUp(self):
        self.sleeps = []

    def source(self, fetch):
        return YahooQuotes(fetch=fetch, throttle=0, sleep=self.sleeps.append)

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
                         LastClosed(self.DAY, price("144.84"), Quality.GOOD))


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
    """A row of build_daily as the port's DailyBar. Whatever Yahoo sends, this
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

    def test_a_price_yahoo_sent_but_that_is_no_price_makes_the_session_untrusted(self):
        """The gap is not silent: Yahoo said something about the session that cannot be read."""
        for bad in (0, 0.0, 0.00001, -1.0, float("nan"), float("inf")):
            for k in ("o", "h", "l", "c"):
                with self.subTest(field=k, value=bad):
                    self.assertEqual(yahoo.to_bar(dict(self.ROW, **{k: bad})).trust, UNUSABLE)

    def test_a_price_yahoo_did_not_send_is_a_gap_on_a_trusted_session(self):
        for k in ("o", "h", "l", "c"):
            with self.subTest(field=k):
                bar = yahoo.to_bar(dict(self.ROW, **{k: None}))
                self.assertEqual((getattr(bar, {"o": "open", "h": "high", "l": "low",
                                                "c": "close"}[k]), bar.trust), (None, Trust.TRUSTED))

    def test_an_unusable_volume_alone_keeps_the_session_trusted(self):
        self.assertEqual(yahoo.to_bar(dict(self.ROW, v=-5)).trust, Trust.TRUSTED)

    def test_a_flat_session_at_zero_with_no_volume_is_unusable_not_a_placeholder(self):
        """Flat with no volume, but at a price that is no price: there is no price to have filled
        the session with, so the unreadable number is the reason."""
        bar = yahoo.to_bar(dict(self.ROW, o=0, h=0, l=0, c=0, v=0))
        self.assertEqual((bar.close, bar.trust), (None, UNUSABLE))

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
        self.assertEqual({b.trust for b in s.bars}, {UNUSABLE})


PLACEHOLDER = Trust.untrusted("placeholder")


class TestPlaceholder(unittest.TestCase):
    """Yahoo fills a session it has no trades for with one price in all four fields and no volume.
    The adapter does not guess that session's price and does not drop it: it marks it untrusted.
    The rule looks at the bar alone, never at the session before it."""

    ROW = {"date": "2026-07-24", "o": 155.7, "h": 156.3, "l": 153.42, "c": 156.0, "v": 1516341,
           "complete": True}

    def flat(self, p=156.0, v=0, **row):
        return {**self.ROW, "o": p, "h": p, "l": p, "c": p, "v": v, **row}

    def response(self, rows):
        """A Yahoo chart response holding `rows` ((o, h, l, c, v) per session from 07-20 on)."""
        day0 = (date(2026, 7, 20) - date(1970, 1, 1)).days * 86400 + 7 * 3600
        cols = list(zip(*rows))
        return {"meta": {"gmtoffset": 7200},
                "timestamp": [day0 + i * 86400 for i in range(len(rows))],
                "indicators": {"quote": [dict(zip(("open", "high", "low", "close", "volume"),
                                                  map(list, cols)))]}}

    def test_flat_bar_without_volume_is_an_untrusted_placeholder(self):
        bar = yahoo.to_bar(self.flat())
        self.assertEqual(bar.trust, PLACEHOLDER)
        self.assertEqual(num(bar.close), 156.0)              # marked, not guessed or dropped

    def test_missing_volume_counts_as_none_traded(self):
        self.assertEqual(yahoo.to_bar(self.flat(v=None)).trust, PLACEHOLDER)

    def test_flat_bar_with_volume_is_a_real_session(self):
        self.assertEqual(yahoo.to_bar(self.flat(v=10)).trust, Trust.TRUSTED)

    def test_a_bar_with_a_range_and_no_volume_is_trusted(self):
        self.assertEqual(yahoo.to_bar(dict(self.ROW, v=0)).trust, Trust.TRUSTED)

    def test_a_bar_with_a_missing_price_is_not_a_placeholder(self):
        """All four prices must be there and equal; a gap is a gap, not a placeholder."""
        self.assertEqual(yahoo.to_bar(self.flat(o=None)).trust, Trust.TRUSTED)

    def test_forming_flat_bar_is_judged_too(self):
        bar = yahoo.to_bar(self.flat(complete=False))
        self.assertEqual((bar.trust, bar.complete), (PLACEHOLDER, False))

    def test_five_in_a_row_are_all_placeholders_and_so_is_the_first(self):
        """No look at the previous close: the first bar of the answer is judged like the rest."""
        real = (150.0, 152.0, 149.0, 151.0, 900)
        rows = [(151.0, 151.0, 151.0, 151.0, 0)] * 5 + [real]
        s = YahooQuotes(fetch=lambda sym, rng: (self.response(rows), None), throttle=0,
                        sleep=no_sleep).daily(PKN, period(ONE_MONTH), now=FROZEN_NOW)
        self.assertEqual([b.trust for b in s.bars], [PLACEHOLDER] * 5 + [Trust.TRUSTED])


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
