"""market_data.adapters.store — StoreQuotes: the own candle store behind the QuoteSource port.

Offline, no mocks: the store is the hand-written fixture directory (fixtures/store/) or a temp
directory on disk; the lower source in a chain is support.FakeSource.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from support import FX, FakeSource, flat_bar, num
from market_data.adapters.store import StoreQuotes
from market_data.indicators import atr_wilder, swing_lows
from market_data.model import (AtrPeriod, DailyBar, DateRange, Instrument, Isin, Price, Quality,
                               SessionsEachSide, Status, Trust, Volume)
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)
from market_data.quote_chain import QuoteChain

STORE = Path(FX) / "store"                     # holds PLPKN0000018.csv: 10-02 and 10-05..10-09
PKN = Instrument(isin=Isin.parse("PLPKN0000018"), symbols={"yahoo": "PKN.WA"})
PEO = Instrument(isin=Isin.parse("PLPEKAO00016"), symbols={"yahoo": "PEO.WA"})
PERIOD = DateRange(date(2026, 9, 28), date(2026, 10, 12))
NOW = 1791000000.0                             # unused by the store; the port requires it
PKN_RESOLVED = (Resolution("store", "PLPKN0000018", ResolvedBy.ISIN),)
INCONSISTENT_OHLC = Trust.untrusted("inconsistent_ohlc")


def dates(series):
    return [b.session.isoformat() for b in series.bars]


def store_with(test, *rows: str) -> Path:
    """A temp store directory holding PKN's file with these data rows under the header."""
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, tmp, True)
    (tmp / "PLPKN0000018.csv").write_text("date,open,high,low,close,volume,source\n"
                                          + "".join(f"{r}\n" for r in rows))
    return tmp


class TestStoreQuotes(unittest.TestCase):
    def test_is_named_store(self):
        self.assertEqual(StoreQuotes.name, "store")

    def test_answers_every_row_of_the_instruments_file(self):
        s = StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW)
        self.assertEqual(dates(s), ["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
                                    "2026-10-08", "2026-10-09"])
        self.assertEqual(s.bars[-1], DailyBar(date(2026, 10, 9), Price.parse("103"),
                                              Price.parse("108"), Price.parse("102"),
                                              Price.parse("107.50"), Volume(1500000),
                                              complete=True, source="store", trust=Trust.TRUSTED))
        self.assertEqual(s.unavailable, ())

    def test_source_is_the_adapter_not_the_provider(self):
        """The file's rows say stooq; the bar names who served it."""
        s = StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW)
        self.assertEqual({b.source for b in s.bars}, {"store"})

    def test_nothing_after_the_period_end(self):
        s = StoreQuotes(STORE).daily(PKN, DateRange(date(2026, 9, 28), date(2026, 10, 7)), now=NOW)
        self.assertEqual(dates(s)[-1], "2026-10-07")

    def test_rows_before_the_period_start_still_come(self):
        """The port allows more than asked; cutting at the start would mix sources on the old edge
        of the window (MN asks for 2130 days and needs 71 months)."""
        s = StoreQuotes(STORE).daily(PKN, DateRange(date(2026, 10, 6), date(2026, 10, 12)), now=NOW)
        self.assertEqual(dates(s)[0], "2026-10-02")

    def test_every_bar_is_the_stores_and_complete(self):
        s = StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW)
        self.assertEqual({(b.source, b.complete) for b in s.bars}, {(StoreQuotes.name, True)})

    def test_resolves_by_isin(self):
        self.assertEqual(StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW).resolved, PKN_RESOLVED)

    def test_isin_without_a_file_is_an_empty_answer_that_still_says_what_it_looked_for(self):
        s = StoreQuotes(STORE).daily(PEO, PERIOD, now=NOW)
        self.assertEqual(s, QuoteSeries((), (Resolution("store", "PLPEKAO00016", ResolvedBy.ISIN),)))

    def test_a_bar_shaped_like_a_vendor_placeholder_is_trusted(self):
        """Only closed sessions someone imported are stored (ADR 0000): the store vouches for each.
        A flat row with no volume is Yahoo's placeholder shape, and that rule is Yahoo's alone."""
        tmp = store_with(self, "2026-10-08,107,107,107,107,0,stooq",
                         "2026-10-09,103,108,102,107.50,1500000,stooq")
        s = StoreQuotes(tmp).daily(PKN, PERIOD, now=NOW)
        self.assertEqual([b.trust for b in s.bars], [Trust.TRUSTED, Trust.TRUSTED])

    def test_a_row_whose_low_or_high_does_not_bracket_open_and_close_is_served_untrusted(self):
        """Served as stored, neither dropped nor corrected, untrusted with a reason that names the
        rule; every other row stays trusted."""
        tmp = store_with(self, "2026-10-06,101,103,99,102,700000,stooq",
                         "2026-10-07,102,104,103,102.5,800000,stooq",     # low above the open
                         "2026-10-08,101,103.50,99,103,800000,stooq",
                         "2026-10-09,103,106,102,107.50,1500000,stooq")   # high below the close
        s = StoreQuotes(tmp).daily(PKN, PERIOD, now=NOW)
        self.assertEqual([(b.session.isoformat(), b.trust) for b in s.bars],
                         [("2026-10-06", Trust.TRUSTED), ("2026-10-07", INCONSISTENT_OHLC),
                          ("2026-10-08", Trust.TRUSTED), ("2026-10-09", INCONSISTENT_OHLC)])
        self.assertEqual(s.bars[1], DailyBar(date(2026, 10, 7), Price.parse("102"),
                                             Price.parse("104"), Price.parse("103"),
                                             Price.parse("102.5"), Volume(800000), complete=True,
                                             source="store", trust=INCONSISTENT_OHLC))

    def test_atr_and_swing_lows_over_such_a_row_are_uncertain_and_name_its_date(self):
        """The readings already leave untrusted sessions out; this proves the store's new reason
        reaches them like any other."""
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range(42)]
        days = [d for d in days if d.weekday() < 5]                      # 09-01 .. 10-12
        rows = []
        for i, d in enumerate(days):
            c = 100 + (i * 7) % 11                                       # a close that moves
            o, h, l = c - 1, c + 2, c - 3  # noqa: E741
            if d == date(2026, 10, 6):
                l = c + 0.5  # noqa: E741                              # low above open and close
            rows.append(f"{d.isoformat()},{o},{h},{l},{c},{1000 + i},stooq")
        bars = StoreQuotes(store_with(self, *rows)).daily(PKN, PERIOD, now=NOW).bars
        atr, swings = atr_wilder(bars, AtrPeriod(14)), swing_lows(bars, SessionsEachSide(2))
        self.assertEqual((atr.quality, atr.quality.status),
                         (Quality((date(2026, 10, 6),)), Status.UNCERTAIN))
        self.assertEqual((swings.quality, swings.quality.status),
                         (Quality((date(2026, 10, 6),)), Status.UNCERTAIN))

    def test_an_instrument_outside_the_symbol_map_is_answered_by_its_isin(self):
        """The file is named by the ISIN: the store needs no symbol from the map."""
        outside = Instrument.unmapped(Isin.parse("PLPKN0000018"))
        self.assertEqual(StoreQuotes(STORE).daily(outside, PERIOD, now=NOW),
                         StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW))


class TestStoreDidNotAnswer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_store_directory_is_no_store_even_for_a_known_isin(self):
        """No directory = the project has no store yet: a signal, not 'the store lacks PKN', and
        not Yahoo's not_found ('no such symbol') either."""
        with self.assertRaises(QuoteSourceUnavailableError) as caught:
            StoreQuotes(self.tmp / "missing").daily(PKN, PERIOD, now=NOW)
        self.assertEqual(caught.exception.failures, (SourceFailure("store", "no_store"),))
        self.assertEqual(caught.exception.resolved, ())
        self.assertFalse((self.tmp / "missing").exists())

    def test_broken_file_is_malformed_and_says_where_on_stderr(self):
        path = self.tmp / "PLPKN0000018.csv"
        path.write_bytes(b"date,open,high,low,close,volume,source\n"
                         b"2026-10-10,103,108,102,107.50,1500000,stooq\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                self.assertRaises(QuoteSourceUnavailableError) as caught:
            StoreQuotes(self.tmp).daily(PKN, PERIOD, now=NOW)
        self.assertEqual(caught.exception.failures, (SourceFailure("store", "malformed"),))
        self.assertEqual(caught.exception.resolved, PKN_RESOLVED)
        self.assertTrue(err.getvalue().startswith(f"{path}:2: "), err.getvalue())
        self.assertIn("Saturday", err.getvalue())


class TestStoreInAChain(unittest.TestCase):
    def test_store_wins_a_shared_date_and_the_lower_source_fills_the_rest(self):
        yahoo = FakeSource(QuoteSeries((flat_bar("2026-10-09", 99.0),
                                        flat_bar("2026-10-12", 110.0)), ()))
        s = QuoteChain([StoreQuotes(STORE), yahoo]).daily(PKN, PERIOD, now=NOW)
        self.assertEqual([(b.session.isoformat(), num(b.close), b.source) for b in s.bars[-2:]],
                         [("2026-10-09", 107.5, "store"), ("2026-10-12", 110.0, "yahoo")])


if __name__ == "__main__":
    unittest.main()
