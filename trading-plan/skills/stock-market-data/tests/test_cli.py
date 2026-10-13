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

from support import (FX, FROZEN_TODAY, FROZEN_NOW, FakeSource, daily_bar, flat_bar, load_yahoo,
                     price, warsaw)
import quotes
from market_data.adapters.store import StoreQuotes
from market_data.indicators import AtrReading, LastClosed, SwingLow, SwingLows
from market_data.model import (AtrPeriod, DateRange, Instrument, Interval, Isin, PeriodBar,
                               Quality, SessionsEachSide, Trust, Volume)
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)
from market_data.quote_chain import QuoteChain

PKN = Instrument(key="PKN.PL", isin=None, symbols={"yahoo": "PKN.WA"})
PKN_ISIN = Instrument(key="PKN.PL", isin=Isin.parse("PLPKN0000018"), symbols={"yahoo": "PKN.WA"})
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

    def test_with_a_store_the_store_is_asked_before_yahoo(self):
        """Order shows in behaviour: on a date both have, the store's bar is the one that comes."""
        store_dir = self.tmp / "store"
        store_dir.mkdir()
        (store_dir / "PLPKN0000018.csv").write_text(
            "date,open,high,low,close,volume,source\n2026-07-24,1,1,1,1,7,stooq\n")
        source = quotes.build_source(False, store_dir=store_dir, cache_dir=self.tmp / "cache",
                                     fetch=self.fetch, sleep=lambda s: None)
        bars = source.daily(PKN_ISIN, PERIOD, now=FROZEN_NOW).bars
        self.assertEqual([(b.session, b.close, b.source) for b in bars[-2:]],
                         [(bars[-2].session, bars[-2].close, "yahoo"),
                          (date(2026, 7, 24), price(1), "store")])
        self.assertEqual(len(self.calls), 1)


def bar(day, close, source="yahoo"):
    return flat_bar(day, close, source)


def bar_json(day, close, source="yahoo"):
    """What bar(day, close, source) prints."""
    return {"date": day, "o": close, "h": close, "l": close, "c": close, "v": 1, "complete": True,
            "source": source, "trusted": True}


BARS = tuple(bar(f"2026-07-{d:02d}", float(d)) for d in (20, 21, 22, 23, 24))
YAHOO_PKN = Resolution("yahoo", "PKN.WA", ResolvedBy.SYMBOLS_JSON)
STORE_PKN = Resolution("store", "PLPKN0000018", ResolvedBy.ISIN)


def run(argv, source=None, **seams):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        quotes.main(argv, source=source, **seams)
    return json.loads(out.getvalue())


class TestMain(unittest.TestCase):
    def test_answered_record(self):
        src = FakeSource(QuoteSeries(BARS, (STORE_PKN, YAHOO_PKN)))
        doc = run(["PKN.PL", "--bars", "3"], src)
        self.assertEqual(doc["source"], src.description)      # the header describes the source asked
        self.assertEqual(doc["interval"], "daily")
        rec = doc["quotes"]["PKN.PL"]
        self.assertEqual((rec["yahoo_symbol"], rec["xtb"], rec["resolved_by"], rec["ok"]),
                         ("PKN.WA", "PKN.PL", "symbols.json", True))
        self.assertEqual(rec["bars"], [bar_json(f"2026-07-{d}", float(d)) for d in (22, 23, 24)])
        self.assertNotIn("unavailable", rec)                # empty -> absent, as today

    def test_a_bar_the_source_does_not_vouch_for_is_printed_untrusted_with_its_reason(self):
        placeholder = daily_bar("2026-07-24", 24, 24, 24, 24, 0,
                                trust=Trust.untrusted("placeholder"))
        rec = run(["PKN.PL", "--bars", "2"],
                  FakeSource(QuoteSeries(BARS[:-1] + (placeholder,), (YAHOO_PKN,))))["quotes"]["PKN.PL"]
        self.assertEqual([(b["trusted"], b.get("untrusted_reason")) for b in rec["bars"]],
                         [(True, None), (False, "placeholder")])
        self.assertNotIn("untrusted_reason", rec["bars"][0])

    def test_with_a_store_the_header_names_it_before_yahoo(self):
        store_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, store_dir, True)

        def build(cache, *, store_dir=None):
            return quotes.build_source(cache, store_dir=store_dir,
                                       fetch=lambda sym, rng: (load_yahoo("PKN"), None),
                                       sleep=lambda s: None)

        doc = run(["--store", str(store_dir), "PKN.PL"], build=build)
        self.assertEqual(doc["source"], "own candle store (one CSV per ISIN) > "
                                        "Yahoo Finance v8 chart (~15 min delayed)")

    def test_answered_record_lists_sources_that_did_not_answer(self):
        failures = (SourceFailure("store", "timeout"),)
        rec = run(["PKN.PL"], FakeSource(QuoteSeries(BARS, (YAHOO_PKN,), failures)))["quotes"]["PKN.PL"]
        self.assertEqual(rec["unavailable"], [{"source": "store", "reason": "timeout"}])

    def test_unanswered_record_carries_yahoos_raw_reason_and_every_failure(self):
        err = QuoteSourceUnavailableError(
            (SourceFailure("store", "timeout"), SourceFailure("yahoo", "not_found")),
            (STORE_PKN, Resolution("yahoo", "XXXX.WA", ResolvedBy.SUFFIX_GUESS)))
        doc = run(["XXXX.PL"], FakeSource(error=err))
        self.assertEqual(doc["quotes"]["XXXX.PL"],
                         {"yahoo_symbol": "XXXX.WA", "xtb": None, "resolved_by": "suffix_guess",
                          "ok": False, "reason": "not_found", "value": "[NO DATA]",
                          "unavailable": [{"source": "store", "reason": "timeout"},
                                          {"source": "yahoo", "reason": "not_found"}]})

    def test_no_yahoo_entry_gives_none_fields_and_the_first_failures_reason(self):
        ok = run(["PKN.PL"], FakeSource(QuoteSeries(BARS, (STORE_PKN,))))["quotes"]["PKN.PL"]
        self.assertEqual((ok["yahoo_symbol"], ok["resolved_by"], ok["ok"]), (None, None, True))
        err = QuoteSourceUnavailableError((SourceFailure("store", "timeout"),
                                           SourceFailure("broker", "http_503")), (STORE_PKN,))
        bad = run(["PKN.PL"], FakeSource(error=err))["quotes"]["PKN.PL"]
        self.assertEqual((bad["yahoo_symbol"], bad["resolved_by"], bad["reason"], bad["ok"]),
                         (None, None, "timeout", False))

    def test_no_bars_while_a_source_did_not_answer_is_no_data(self):
        """The store answered with nothing, Yahoo did not answer: the same ok:false record as
        when nothing answered, not an ok:true with an empty bars list."""
        store_empty = FakeSource(QuoteSeries((), (STORE_PKN,)))
        yahoo_down = FakeSource(error=QuoteSourceUnavailableError(
            (SourceFailure("yahoo", "http_503"),), (YAHOO_PKN,)))
        rec = run(["PKN.PL"], QuoteChain([store_empty, yahoo_down]))["quotes"]["PKN.PL"]
        self.assertEqual(rec, {"yahoo_symbol": "PKN.WA", "xtb": "PKN.PL",
                               "resolved_by": "symbols.json", "ok": False, "reason": "http_503",
                               "value": "[NO DATA]",
                               "unavailable": [{"source": "yahoo", "reason": "http_503"}]})

    def test_chain_where_nothing_answered_lists_both_failures(self):
        store_down = FakeSource(error=QuoteSourceUnavailableError(
            (SourceFailure("store", "no_store"),)))
        yahoo_down = FakeSource(error=QuoteSourceUnavailableError(
            (SourceFailure("yahoo", "rate_limited"),), (YAHOO_PKN,)))
        rec = run(["PKN.PL"], QuoteChain([store_down, yahoo_down]))["quotes"]["PKN.PL"]
        self.assertEqual((rec["ok"], rec["reason"], rec["unavailable"]),
                         (False, "rate_limited", [{"source": "store", "reason": "no_store"},
                                                  {"source": "yahoo", "reason": "rate_limited"}]))

    def test_project_without_a_store_still_gets_yahoos_bars_and_is_told_so(self):
        missing = Path(tempfile.mkdtemp()) / "missing"
        self.addCleanup(shutil.rmtree, missing.parent, True)
        yahoo_ok = FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))
        rec = run(["PKN.PL"], QuoteChain([StoreQuotes(missing), yahoo_ok]))["quotes"]["PKN.PL"]
        self.assertEqual((rec["ok"], rec["bars"][-1], rec["unavailable"]),
                         (True, bar_json("2026-07-24", 24.0),
                          [{"source": "store", "reason": "no_store"}]))

    def test_no_bars_from_a_source_that_answered_stays_ok(self):
        """Yahoo alone answering with nothing is an answer: ok:true, as before the store."""
        rec = run(["PKN.PL"], FakeSource(QuoteSeries((), (YAHOO_PKN,))))["quotes"]["PKN.PL"]
        self.assertEqual((rec["ok"], rec["bars"]), (True, []))
        self.assertNotIn("unavailable", rec)

    def test_today_seam_ends_the_period(self):
        src = FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))
        run(["PKN.PL"], src, today=date(2026, 7, 25))
        self.assertEqual(src.asked[0][1].end, date(2026, 7, 25))

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


class TestToJson(unittest.TestCase):
    """The types become JSON here and nowhere else: keys and their order as the output contract has
    them, prices as floats, dates as ISO text. The pin below covers the daily path end to end."""

    def dumped(self, obj):
        return json.loads(json.dumps(obj, default=quotes.to_json))

    def test_daily_bar_prints_its_source_and_gaps_as_null(self):
        b = daily_bar("2026-10-09", None, 108, 102, "107.50", 1500000, source="store")
        self.assertEqual(list(quotes.to_json(b)),
                         ["date", "o", "h", "l", "c", "v", "complete", "source", "trusted"])
        self.assertEqual(self.dumped(b), {"date": "2026-10-09", "o": None, "h": 108.0, "l": 102.0,
                                          "c": 107.5, "v": 1500000, "complete": True,
                                          "source": "store", "trusted": True})

    def test_untrusted_daily_bar_says_why(self):
        b = daily_bar("2026-10-09", 107, 107, 107, 107, 0, trust=Trust.untrusted("placeholder"))
        self.assertEqual(list(quotes.to_json(b))[-2:], ["trusted", "untrusted_reason"])
        self.assertEqual(self.dumped(b)["trusted"], False)
        self.assertEqual(self.dumped(b)["untrusted_reason"], "placeholder")

    def test_rolled_up_bars_carry_no_source(self):
        """Output contract (SKILL.md): daily bars name their source, W1/MN bars do not."""
        b = PeriodBar(date(2026, 7, 20), price(10), price(13), price(8.5), price(9.5), Volume(600),
                      True, Quality.GOOD)
        self.assertEqual(list(quotes.to_json(b)), ["date", "o", "h", "l", "c", "v", "complete",
                                                   "status", "excluded_sessions"])
        self.assertEqual(self.dumped(b), {"date": "2026-07-20", "o": 10.0, "h": 13.0, "l": 8.5,
                                          "c": 9.5, "v": 600, "complete": True, "status": "good",
                                          "excluded_sessions": []})

    def test_a_period_with_no_trusted_session_has_no_value_and_names_its_sessions(self):
        left_out = Quality((date(2026, 10, 9), date(2026, 10, 5), date(2026, 10, 7)))
        b = PeriodBar(date(2026, 10, 5), None, None, None, None, None, True, left_out)
        self.assertEqual(self.dumped(b), {"date": "2026-10-05", "o": None, "h": None, "l": None,
                                          "c": None, "v": None, "complete": True,
                                          "status": "no_value",
                                          "excluded_sessions": ["2026-10-05", "2026-10-07",
                                                                "2026-10-09"]})

    def test_last_closed(self):
        self.assertEqual(self.dumped(LastClosed(date(2026, 7, 24), price(156), Quality.GOOD)),
                         {"date": "2026-07-24", "c": 156.0, "status": "good",
                          "excluded_sessions": []})

    def test_a_reading_left_without_sessions_is_uncertain_and_names_them(self):
        lc = LastClosed(date(2026, 10, 2), price(102),
                        Quality((date(2026, 10, 6), date(2026, 10, 5))))
        self.assertEqual(self.dumped(lc), {"date": "2026-10-02", "c": 102.0, "status": "uncertain",
                                           "excluded_sessions": ["2026-10-05", "2026-10-06"]})

    def test_atr_names_its_interval_only_when_it_has_one(self):
        a = AtrReading(n=AtrPeriod(2), method="wilder", value=3.5, bars_used=5,
                       as_of=date(2026, 1, 7), interval=None, quality=Quality.GOOD)
        self.assertEqual(self.dumped(a), {"n": 2, "method": "wilder", "value": 3.5, "bars_used": 5,
                                          "as_of": "2026-01-07", "short_history": True,
                                          "status": "good", "excluded_sessions": []})

    def test_readings_print_the_intervals_label_not_its_code(self):
        """An interval passed as Interval.WEEKLY once printed "w", the CLI flag, not "weekly"."""
        a = AtrReading(n=AtrPeriod(2), method="wilder", value=3.5, bars_used=5,
                       as_of=date(2026, 1, 7), interval=Interval.WEEKLY, quality=Quality.GOOD)
        self.assertEqual(self.dumped(a)["interval"], "weekly")
        s = SwingLows(each_side=SessionsEachSide(2),
                      window=DateRange(date(2026, 1, 5), date(2026, 3, 2)), window_sessions=9,
                      detectable_through=date(2026, 2, 16), detected=(),
                      interval=Interval.DAILY, quality=Quality.GOOD)
        self.assertEqual(list(self.dumped(s).items())[0], ("candle_interval", "daily"))

    def test_swing_lows_without_an_interval(self):
        s = SwingLows(each_side=SessionsEachSide(2),
                      window=DateRange(date(2026, 1, 1), date(2026, 1, 9)), window_sessions=9,
                      detectable_through=date(2026, 1, 7),
                      detected=(SwingLow(date(2026, 1, 3), price(8), None, 6, price(7)),),
                      interval=None, quality=Quality.GOOD)
        self.assertEqual(self.dumped(s), {
            "sessions_each_side_with_higher_lows": 2, "window_first_session": "2026-01-01",
            "window_last_session": "2026-01-09", "window_sessions": 9,
            "detectable_through": "2026-01-07",
            "detected": [{"date": "2026-01-03", "low_price": 8.0,
                          "higher_than_previous_row_low": None, "sessions_after_in_window": 6,
                          "lowest_low_in_those_sessions": 7.0,
                          "undercut_by_later_session": True}],
            "status": "good", "excluded_sessions": []})

    def test_swing_lows_too_short_to_confirm_have_no_edge(self):
        s = SwingLows(each_side=SessionsEachSide(2),
                      window=DateRange(date(2026, 1, 1), date(2026, 1, 2)), window_sessions=2,
                      detectable_through=None, detected=(), interval=None, quality=Quality.GOOD)
        self.assertIsNone(self.dumped(s)["detectable_through"])

    def test_anything_else_is_not_serializable(self):
        with self.assertRaises(TypeError):
            quotes.to_json(object())


class TestOutputPinnedAt040(unittest.TestCase):
    """Without a store the consumer still finds everything plugin 0.4.0 printed, unchanged and in the
    same order; the output may only add keys. fixtures/cli_0_4_0_PKN.json is the 0.4.0 output
    (commit 2589785) for these arguments, fed by the same Yahoo fixture, minus 'generated' (the wall
    clock). 'data_note' is prose for the reader and may grow. A key the output adds must be named in
    NEW_KEYS: a new key is a contract change, so it is let in on purpose, not by accident."""

    ARGV = ["PKN.PL", "--atr", "--swings"]
    NOT_COMPARED = {"generated", "data_note"}
    NEW_KEYS = {"trusted", "untrusted_reason", "status", "excluded_sessions"}

    def output(self, argv=ARGV):
        source = quotes.build_source(False, fetch=lambda sym, rng: (load_yahoo("PKN"), None),
                                     sleep=lambda s: None)
        return run(argv, source)

    def assertPinnedPlusNewKeys(self, pinned, got, path="$"):
        if isinstance(pinned, dict):
            self.assertIsInstance(got, dict, path)
            added = set(got) - set(pinned)
            self.assertLessEqual(added, self.NEW_KEYS, f"{path}: keys 0.4.0 did not print")
            self.assertEqual([k for k in got if k in pinned], list(pinned), f"{path}: key order")
            for k in pinned:
                self.assertPinnedPlusNewKeys(pinned[k], got[k], f"{path}.{k}")
        elif isinstance(pinned, list):
            self.assertIsInstance(got, list, path)
            self.assertEqual(len(got), len(pinned), f"{path}: length")
            for i, (p, g) in enumerate(zip(pinned, got)):
                self.assertPinnedPlusNewKeys(p, g, f"{path}[{i}]")
        else:                                       # 156.0 and 156 are not the same output
            self.assertEqual((type(got), got), (type(pinned), pinned), path)

    def test_records_are_0_4_0_plus_only_new_keys(self):
        doc = self.output()
        with open(os.path.join(FX, "cli_0_4_0_PKN.json"), encoding="utf-8") as f:
            pinned = json.load(f)
        for k in self.NOT_COMPARED:
            doc.pop(k, None)
            pinned.pop(k, None)
        self.assertPinnedPlusNewKeys(pinned, doc)

    def test_without_placeholders_every_daily_bar_is_trusted(self):
        bars = self.output()["quotes"]["PKN.PL"]["bars"]
        self.assertTrue(bars)
        self.assertEqual({(b["trusted"], "untrusted_reason" in b) for b in bars}, {(True, False)})

    def test_without_placeholders_every_derived_value_is_good(self):
        for interval in ("d", "w", "m"):
            rec = self.output([*self.ARGV, "--interval", interval])["quotes"]["PKN.PL"]
            derived = [rec["last_closed"], rec["swing_lows"]]
            derived += [rec["atr"]] if rec["atr"] else []          # MN: too short for ATR(14)
            derived += rec["bars"] if interval != "d" else []
            with self.subTest(interval=interval):
                self.assertEqual({(d["status"], tuple(d["excluded_sessions"])) for d in derived},
                                 {("good", ())})

    def test_the_comparison_catches_a_changed_value_and_an_unannounced_key(self):
        pinned = {"a": [{"c": 1.0}]}
        for got in ({"a": [{"c": 1}]}, {"a": [{"c": 1.0, "surprise": 0}]}, {"a": [{"c": 2.0}]}):
            with self.subTest(got=got), self.assertRaises(AssertionError):
                self.assertPinnedPlusNewKeys(pinned, got)


class TestOutputPinnedAt060(unittest.TestCase):
    """Without a store the consumer reads what plugin 0.6.0 printed: header and records byte for
    byte. fixtures/cli_0_6_0_PKN.json is the 0.6.0 output for these arguments, fed by the same Yahoo
    fixture, minus 'generated' (the wall clock). TestOutputPinnedAt040 keeps the older promise."""

    ARGV = ["PKN.PL", "--atr", "--swings"]

    def test_header_and_records_match_0_6_0(self):
        source = quotes.build_source(False, fetch=lambda sym, rng: (load_yahoo("PKN"), None),
                                     sleep=lambda s: None)
        doc = run(self.ARGV, source)
        del doc["generated"]
        with open(os.path.join(FX, "cli_0_6_0_PKN.json"), encoding="utf-8") as f:
            pinned = f.read()
        self.assertEqual(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", pinned)


class TestPlaceholderSessionsEndToEnd(unittest.TestCase):
    """The incident as the CLI met it: Yahoo served 10-05..10-09 as placeholders (one price, no
    volume), the own store holds the real sessions up to 10-02. Built by hand: the store fixture
    has 10-05..10-09 itself, so it would hide the gap."""

    REAL = [date(2026, 9, 1) + timedelta(days=i) for i in range(32)]
    REAL = [d for d in REAL if d.weekday() < 5]                       # 09-01 .. 10-02
    GAP = [date(2026, 10, d) for d in (5, 6, 7, 8, 9)]

    @staticmethod
    def ohlcv(i):
        c = 100 + (i * 7) % 11                                        # a close that moves
        return c - 1, c + 2, c - 3, c, 1000 + i

    def yahoo_response(self):
        rows = [self.ohlcv(i) for i in range(len(self.REAL))]
        last_close = rows[-1][3]
        rows += [(last_close, last_close, last_close, last_close, 0)] * len(self.GAP)
        o, h, l, c, v = (list(col) for col in zip(*rows))  # noqa: E741
        return {"meta": {"gmtoffset": 7200, "symbol": "PKN.WA"},
                "timestamp": [warsaw(d.year, d.month, d.day, 9 * 3600) for d in self.REAL + self.GAP],
                "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "store"
        self.store.mkdir()
        lines = ["date,open,high,low,close,volume,source"]
        lines += [f"{d.isoformat()},{o},{h},{l},{c},{v},stooq"
                  for i, d in enumerate(self.REAL) for o, h, l, c, v in [self.ohlcv(i)]]
        (self.store / "PLPKN0000018.csv").write_text("\n".join(lines) + "\n")

    def output(self, *argv):
        response = self.yahoo_response()

        def build(cache, *, store_dir=None):
            return quotes.build_source(cache, store_dir=store_dir, cache_dir=self.tmp / "cache",
                                       fetch=lambda sym, rng: (response, None),
                                       sleep=lambda s: None)

        doc = run(["--store", str(self.store), "PKN.PL", *argv], build=build,
                  today=date(2026, 10, 10))
        return doc["quotes"]["PKN.PL"]

    def test_store_sessions_are_trusted_and_placeholders_are_marked(self):
        rec = self.output("--bars", "7")
        self.assertEqual([(b["date"], b["source"], b["trusted"], b.get("untrusted_reason"))
                          for b in rec["bars"]],
                         [("2026-10-01", "store", True, None), ("2026-10-02", "store", True, None),
                          *((d.isoformat(), "yahoo", False, "placeholder") for d in self.GAP)])

    def test_atr_and_last_closed_are_as_of_the_last_real_session_and_name_the_gap(self):
        rec = self.output("--atr")
        gap = [d.isoformat() for d in self.GAP]
        self.assertEqual((rec["atr"]["as_of"], rec["atr"]["status"], rec["atr"]["excluded_sessions"]),
                         ("2026-10-02", "uncertain", gap))
        last_real_close = float(self.ohlcv(len(self.REAL) - 1)[3])
        self.assertEqual(rec["last_closed"], {"date": "2026-10-02", "c": last_real_close,
                                              "status": "uncertain", "excluded_sessions": gap})

    def test_the_week_of_placeholders_has_no_value(self):
        week = self.output("--interval", "w")["bars"][-1]
        self.assertEqual(week, {"date": "2026-10-05", "o": None, "h": None, "l": None, "c": None,
                                "v": None, "complete": True, "status": "no_value",
                                "excluded_sessions": [d.isoformat() for d in self.GAP]})


class TestCountFlags(unittest.TestCase):
    """--atr N and --swings N are counts of at least 1, checked where argv is read. Before, --atr -3
    printed a negative ATR as settled, --atr 0 quietly printed none, and --swings -1 crashed."""

    def output(self, *argv):
        source = quotes.build_source(False, fetch=lambda sym, rng: (load_yahoo("PKN"), None),
                                     sleep=lambda s: None)
        return run(["PKN.PL", *argv], source)["quotes"]["PKN.PL"]

    def test_a_count_below_one_is_rejected_before_anything_runs(self):
        for argv in (["--atr", "0"], ["--atr", "-3"], ["--swings", "0"], ["--swings", "-1"],
                     ["--atr", "x"]):
            src = FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))
            err = io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stderr(err), \
                    self.assertRaises(SystemExit) as exit_:
                run(["PKN.PL", *argv], src)
            self.assertEqual(exit_.exception.code, 2)
            self.assertEqual(src.asked, [])
            self.assertIn("at least 1", err.getvalue())

    def test_bare_flags_take_the_defaults(self):
        rec = self.output("--atr", "--swings")
        self.assertEqual((rec["atr"]["n"], rec["swing_lows"]["sessions_each_side_with_higher_lows"]),
                         (14, 2))

    def test_a_given_count_is_used(self):
        rec = self.output("--atr", "10", "--swings", "3")
        self.assertEqual((rec["atr"]["n"], rec["swing_lows"]["sessions_each_side_with_higher_lows"]),
                         (10, 3))

    def test_omitted_flags_print_neither_block(self):
        rec = self.output()
        self.assertNotIn("atr", rec)
        self.assertNotIn("swing_lows", rec)


class TestFlagsReachTheCompositionRoot(unittest.TestCase):
    """main() hands --cache and --store to build (the build_source seam) and nothing else does."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.built = []                     # (cache, store_dir) per build call

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, cache, *, store_dir=None):
        self.built.append((cache, store_dir))
        return FakeSource(QuoteSeries(BARS, (YAHOO_PKN,)))

    def test_store_dir_reaches_build(self):
        run(["--store", str(self.tmp), "PKN.PL"], build=self.build)
        self.assertEqual(self.built, [(False, self.tmp)])

    def test_cache_flag_reaches_build(self):
        run(["--cache", "PKN.PL"], build=self.build)
        self.assertEqual(self.built, [(True, None)])

    def test_unsubstituted_variable_in_store_is_rejected_before_anything_runs(self):
        """A skill whose ${CLAUDE_PROJECT_DIR} was not expanded must not read as 'no store'."""
        literal = self.tmp / "${CLAUDE_PROJECT_DIR}" / "data" / "market-data"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as exit_:
            run(["--store", str(literal), "PKN.PL"], build=self.build)
        self.assertEqual(exit_.exception.code, 2)
        self.assertEqual(self.built, [])
        self.assertIn("${", err.getvalue())
        self.assertIn("not substituted", err.getvalue())
        self.assertEqual(os.listdir(self.tmp), [])

    def test_store_whose_parent_is_missing_is_rejected_before_anything_runs(self):
        """An empty ${CLAUDE_PROJECT_DIR} expands to '', so --store reads /data/market-data: its
        parent is missing, and that must not read as 'no store'."""
        store = self.tmp / "data" / "market-data"            # tmp/data does not exist
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as exit_:
            run(["--store", str(store), "PKN.PL"], build=self.build)
        self.assertEqual(exit_.exception.code, 2)
        self.assertEqual(self.built, [])
        self.assertIn(f"parent directory '{self.tmp / 'data'}' does not exist", err.getvalue())
        self.assertIn("was ${CLAUDE_PROJECT_DIR} substituted?", err.getvalue())
        self.assertEqual(os.listdir(self.tmp), [])

    def test_missing_store_under_an_existing_parent_still_reaches_build(self):
        """The store directory itself missing is a project without a store yet, not a bad path."""
        run(["--store", str(self.tmp / "market-data"), "PKN.PL"], build=self.build)
        self.assertEqual(self.built, [(False, self.tmp / "market-data")])


if __name__ == "__main__":
    unittest.main()
