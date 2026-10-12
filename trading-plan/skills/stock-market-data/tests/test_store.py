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
from datetime import date
from pathlib import Path

from support import FX, FakeSource
from market_data.adapters.store import StoreQuotes
from market_data.model import DateRange, Instrument, Isin
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)
from market_data.quote_chain import QuoteChain

STORE = Path(FX) / "store"                     # holds PLPKN0000018.csv: 10-02 and 10-05..10-09
PKN = Instrument(key="PKN.PL", isin=Isin.parse("PLPKN0000018"), symbols={"yahoo": "PKN.WA"})
PEO = Instrument(key="PEO.PL", isin=Isin.parse("PLPEKAO00016"), symbols={"yahoo": "PEO.WA"})
PERIOD = DateRange(date(2026, 9, 28), date(2026, 10, 12))
NOW = 1791000000.0                             # unused by the store; the port requires it
PKN_RESOLVED = (Resolution("store", "PLPKN0000018", ResolvedBy.ISIN),)


def dates(series):
    return [b["date"] for b in series.bars]


class TestStoreQuotes(unittest.TestCase):
    def test_is_named_store(self):
        self.assertEqual(StoreQuotes.name, "store")

    def test_answers_every_row_of_the_instruments_file(self):
        s = StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW)
        self.assertEqual(dates(s), ["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
                                    "2026-10-08", "2026-10-09"])
        self.assertEqual(s.bars[-1], {"date": "2026-10-09", "o": 103.0, "h": 108.0, "l": 102.0,
                                      "c": 107.5, "v": 1500000, "complete": True,
                                      "source": "store"})
        self.assertEqual(s.unavailable, ())

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
        self.assertEqual({(b["source"], b["complete"]) for b in s.bars}, {(StoreQuotes.name, True)})

    def test_resolves_by_isin(self):
        self.assertEqual(StoreQuotes(STORE).daily(PKN, PERIOD, now=NOW).resolved, PKN_RESOLVED)

    def test_isin_without_a_file_is_an_empty_answer_that_still_says_what_it_looked_for(self):
        s = StoreQuotes(STORE).daily(PEO, PERIOD, now=NOW)
        self.assertEqual(s, QuoteSeries((), (Resolution("store", "PLPEKAO00016", ResolvedBy.ISIN),)))

    def test_unmapped_instrument_is_an_empty_answer(self):
        s = StoreQuotes(STORE).daily(Instrument.unmapped("XXXX.PL"), PERIOD, now=NOW)
        self.assertEqual(s, QuoteSeries((), ()))


class TestStoreDidNotAnswer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_store_directory_is_not_found_even_for_a_known_isin(self):
        """No directory = the project has no store yet: a signal, not 'the store lacks PKN'."""
        with self.assertRaises(QuoteSourceUnavailableError) as caught:
            StoreQuotes(self.tmp / "missing").daily(PKN, PERIOD, now=NOW)
        self.assertEqual(caught.exception.failures, (SourceFailure("store", "not_found"),))
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
        def bar(day, close):
            return {"date": day, "o": close, "h": close, "l": close, "c": close, "v": 1,
                    "complete": True, "source": "yahoo"}

        yahoo = FakeSource(QuoteSeries((bar("2026-10-09", 99.0), bar("2026-10-12", 110.0)), ()))
        s = QuoteChain([StoreQuotes(STORE), yahoo]).daily(PKN, PERIOD, now=NOW)
        self.assertEqual([(b["date"], b["c"], b["source"]) for b in s.bars[-2:]],
                         [("2026-10-09", 107.5, "store"), ("2026-10-12", 110.0, "yahoo")])


if __name__ == "__main__":
    unittest.main()
