"""quotes.py — the composition root (build_source) and the CLI (main) over an injected source.

Offline, no mocks: build_source gets a temp cache directory and a fake fetch; main gets a fake
QuoteSource that records what it was asked and answers with fixed bars or a fixed failure.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from support import FROZEN_TODAY, FROZEN_NOW, load_yahoo
import quotes
from market_data.adapters import yahoo
from market_data.model import DateRange, Instrument
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)

PKN = Instrument(key="PKN.PL", isin=None, symbols={"yahoo": "PKN.WA"})
PERIOD = DateRange(date.fromisoformat(FROZEN_TODAY) - timedelta(days=300),
                   date.fromisoformat(FROZEN_TODAY))


class TestBuildSource(unittest.TestCase):
    """The fail-safe: without --cache nothing touches the disk and every call goes live."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self, sym, rng):
        self.calls.append((sym, rng))
        return load_yahoo("PKN"), None

    def ask_twice(self, cache):
        source = quotes.build_source(cache, cache_dir=self.tmp, fetch=self.fetch,
                                     sleep=lambda s: None)
        for _ in range(2):
            source.daily(PKN, PERIOD, now=FROZEN_NOW)

    def test_without_cache_writes_nothing_and_always_fetches(self):
        self.ask_twice(cache=False)
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertEqual(len(self.calls), 2)

    def test_with_cache_writes_one_file_and_reuses_it(self):
        self.ask_twice(cache=True)
        self.assertEqual(os.listdir(self.tmp), ["PKN.WA.json"])
        self.assertEqual(len(self.calls), 1)


def bar(day, close, source="yahoo"):
    return {"date": day, "o": close, "h": close, "l": close, "c": close, "v": 1, "complete": True,
            "source": source}


BARS = tuple(bar(f"2026-07-{d:02d}", float(d)) for d in (20, 21, 22, 23, 24))
YAHOO_PKN = Resolution("yahoo", "PKN.WA", ResolvedBy.SYMBOLS_JSON)
STORE_PKN = Resolution("store", "PKN", ResolvedBy.SYMBOLS_JSON)


class FakeSource:
    """A QuoteSource giving every instrument the same answer, or raising `error`."""

    name = "fake"

    def __init__(self, series=None, error=None):
        self._series = series
        self._error = error
        self.asked = []                     # (instrument key, period)

    def daily(self, instrument, period, *, now):
        self.asked.append((instrument.key, period))
        if self._error is not None:
            raise self._error
        return self._series


def run(argv, source):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        quotes.main(argv, source=source)
    return json.loads(out.getvalue())


class TestMain(unittest.TestCase):
    def test_answered_record(self):
        src = FakeSource(QuoteSeries(BARS, (STORE_PKN, YAHOO_PKN)))
        doc = run(["PKN.PL", "--bars", "3"], src)
        self.assertEqual(doc["source"], yahoo.DESCRIPTION)
        self.assertEqual(doc["interval"], "daily")
        rec = doc["quotes"]["PKN.PL"]
        self.assertEqual((rec["yahoo_symbol"], rec["xtb"], rec["resolved_by"], rec["ok"]),
                         ("PKN.WA", "PKN.PL", "symbols.json", True))
        self.assertEqual(rec["bars"], [dict(b) for b in BARS[-3:]])
        self.assertNotIn("unavailable", rec)                # empty -> absent, as today

    def test_answered_record_lists_sources_that_did_not_answer(self):
        failures = (SourceFailure("store", "timeout"),)
        rec = run(["PKN.PL"], FakeSource(QuoteSeries(BARS, (YAHOO_PKN,), failures)))["quotes"]["PKN.PL"]
        self.assertEqual(rec["unavailable"], [{"source": "store", "reason": "timeout"}])

    def test_unanswered_record_carries_yahoos_raw_reason(self):
        err = QuoteSourceUnavailableError(
            (SourceFailure("store", "timeout"), SourceFailure("yahoo", "not_found")),
            (STORE_PKN, Resolution("yahoo", "XXXX.WA", ResolvedBy.SUFFIX_GUESS)))
        doc = run(["XXXX.PL"], FakeSource(error=err))
        self.assertEqual(doc["quotes"]["XXXX.PL"],
                         {"yahoo_symbol": "XXXX.WA", "xtb": None, "resolved_by": "suffix_guess",
                          "ok": False, "reason": "not_found", "value": "[NO DATA]"})

    def test_no_yahoo_entry_gives_none_fields_instead_of_crashing(self):
        ok = run(["PKN.PL"], FakeSource(QuoteSeries(BARS, (STORE_PKN,))))["quotes"]["PKN.PL"]
        self.assertEqual((ok["yahoo_symbol"], ok["resolved_by"], ok["ok"]), (None, None, True))
        err = QuoteSourceUnavailableError((SourceFailure("store", "timeout"),), (STORE_PKN,))
        bad = run(["PKN.PL"], FakeSource(error=err))["quotes"]["PKN.PL"]
        self.assertEqual((bad["yahoo_symbol"], bad["resolved_by"], bad["reason"], bad["ok"]),
                         (None, None, None, False))

    def test_every_ticker_is_asked_for_one_period_ending_today(self):
        src = FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))
        run(["PKN.PL", "ALE.PL"], src)
        self.assertEqual([k for k, _ in src.asked], ["PKN.PL", "ALE.PL"])
        self.assertEqual({p for _, p in src.asked}, {src.asked[0][1]})
        self.assertEqual(src.asked[0][1].end, date.today())

    def period_days(self, *argv):
        src = FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))
        run(["PKN.PL", *argv], src)
        return src.asked[0][1].days

    def test_period_spans_at_least_nine_days(self):
        """The port promises empty never means 'weekend': --bars 1 alone needs only 2 days."""
        self.assertEqual(self.period_days("--bars", "1"), quotes.MIN_PERIOD_DAYS)
        self.assertEqual(quotes.MIN_PERIOD_DAYS, 9)

    def test_non_positive_bars_ask_for_one_candle(self):
        """--bars <= 0 never failed; it fetches what one candle needs (one month for MN)."""
        self.assertEqual(self.period_days("--bars", "-5", "--interval", "m"), 30)
        self.assertEqual(self.period_days("--bars", "0", "--interval", "m"), 30)

    def test_huge_bars_are_capped(self):
        self.assertEqual(self.period_days("--bars", "500000"), quotes.MAX_PERIOD_DAYS)

    def test_negative_bars_do_not_crash(self):
        rec = run(["PKN.PL", "--bars", "-5"], FakeSource(QuoteSeries(BARS, (YAHOO_PKN,))))
        self.assertTrue(rec["quotes"]["PKN.PL"]["ok"])


if __name__ == "__main__":
    unittest.main()
