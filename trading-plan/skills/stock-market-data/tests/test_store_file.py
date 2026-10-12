"""market_data.store_file — the candle store's file schema, the stored row, and its bar."""
from __future__ import annotations

import csv
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import support  # noqa: F401  (puts scripts/ on sys.path)
from support import FX
from market_data.model import DailyQuote, Price, Volume
from market_data.store_file import (ENCODING, HEADER, LINE_TERMINATOR, StoredQuote, StoreFileError,
                                    read, to_bar)

STORE_PKN = os.path.join(FX, "store", "PLPKN0000018.csv")


def stored(o="100.50", h="104", l="98.25", c="102", v="1500000", source="stooq"):  # noqa: E741
    q = DailyQuote(date(2026, 10, 9), Price.parse(o), Price.parse(h), Price.parse(l), Price.parse(c),
                   Volume.parse(v))
    return StoredQuote(q, source)


GOOD_HEADER = b"date,open,high,low,close,volume,source\n"
THU = b"2026-10-08,101,103.50,99,103,800000,stooq\n"
FRI = b"2026-10-09,103,108,102,107.50,1500000,stooq\n"


def write_tmp(test, raw: bytes) -> Path:
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, tmp, True)
    path = tmp / "PLPKN0000018.csv"
    path.write_bytes(raw)
    return path


class TestRead(unittest.TestCase):
    def test_reads_the_fixture_in_order(self):
        rows = read(Path(STORE_PKN))
        self.assertEqual([r.quote.session for r in rows],
                         [date(2026, 10, 2), date(2026, 10, 5), date(2026, 10, 6),
                          date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)])
        self.assertEqual({r.source for r in rows}, {"stooq"})

    def test_a_row_becomes_a_typed_quote_keeping_the_price_text(self):
        last = read(Path(STORE_PKN))[-1]
        self.assertEqual(last, StoredQuote(
            DailyQuote(date(2026, 10, 9), Price.parse("103"), Price.parse("108"),
                       Price.parse("102"), Price.parse("107.50"), Volume.parse("1500000")),
            "stooq"))
        self.assertEqual(str(last.quote.close), "107.50")

    def test_a_header_alone_is_an_empty_store(self):
        self.assertEqual(read(write_tmp(self, GOOD_HEADER)), [])


class TestReadRejects(unittest.TestCase):
    """Every rule of the file fails with the file, the line and why; nothing is half-read."""

    def rejects(self, raw: bytes, line, *why):
        path = write_tmp(self, raw)
        with self.assertRaises(StoreFileError) as caught:
            read(path)
        e = caught.exception
        self.assertEqual((e.path, e.line), (path, line))
        for fragment in why:
            self.assertIn(fragment, e.why)
        self.assertEqual(str(e), f"{path}:{line}: {e.why}" if line else f"{path}: {e.why}")
        return e

    def test_wrong_header(self):
        self.rejects(b"Data,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen\n" + FRI, 1, "header")

    def test_empty_file(self):
        self.rejects(b"", 1, "header")

    def test_wrong_number_of_columns(self):
        self.rejects(GOOD_HEADER + THU + b"2026-10-09,103,108,102,107.50,1500000\n", 3, "6 columns")

    def test_blank_line(self):
        self.rejects(GOOD_HEADER + THU + b"\n" + FRI, 3, "0 columns")

    def test_unparsable_price(self):
        self.rejects(GOOD_HEADER + b"2026-10-09,103,108,102,1e2,1500000,stooq\n", 2, "1e2")

    def test_fractional_volume(self):
        self.rejects(GOOD_HEADER + b"2026-10-09,103,108,102,107.50,560358.27,stooq\n", 2,
                     "560358.27")

    def test_ohlc_rule(self):
        self.rejects(GOOD_HEADER + b"2026-10-09,103,108,104,107.50,1500000,stooq\n", 2, "low")

    def test_date_not_iso(self):
        self.rejects(GOOD_HEADER + b"20261009,103,108,102,107.50,1500000,stooq\n", 2, "20261009")

    def test_saturday(self):
        self.rejects(GOOD_HEADER + b"2026-10-10,103,108,102,107.50,1500000,stooq\n", 2, "Saturday")

    def test_sunday(self):
        self.rejects(GOOD_HEADER + b"2026-10-11,103,108,102,107.50,1500000,stooq\n", 2, "Sunday")

    def test_duplicate_date(self):
        self.rejects(GOOD_HEADER + FRI + FRI, 3, "duplicate", "2026-10-09")

    def test_dates_out_of_order(self):
        self.rejects(GOOD_HEADER + FRI + THU, 3, "ascending", "2026-10-08")

    def test_crlf(self):
        self.rejects(GOOD_HEADER + THU + FRI.replace(b"\n", b"\r\n"), 3, "CRLF")

    def test_bom(self):
        self.rejects(b"\xef\xbb\xbf" + GOOD_HEADER + FRI, 1, "BOM")

    def test_not_utf8_is_wrapped(self):
        self.rejects(GOOD_HEADER + THU + b"2026-10-09,103,108,102,107.50,1500000,st\xf3oq\n", 3,
                     "UTF-8")

    def test_unreadable_file_is_wrapped(self):
        path = write_tmp(self, b"")
        path.unlink()
        path.mkdir()                        # a directory named <ISIN>.csv: open() raises OSError
        with self.assertRaises(StoreFileError) as caught:
            read(path)
        self.assertEqual((caught.exception.path, caught.exception.line), (path, None))


class TestSchema(unittest.TestCase):
    def test_header(self):
        self.assertEqual(HEADER, ("date", "open", "high", "low", "close", "volume", "source"))

    def test_lf_and_no_bom(self):
        self.assertEqual(LINE_TERMINATOR, "\n")
        self.assertEqual(ENCODING, "utf-8")      # not utf-8-sig: no BOM

    def test_the_store_fixture_follows_the_schema(self):
        with open(STORE_PKN, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        with open(STORE_PKN, encoding=ENCODING, newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(tuple(rows[0]), HEADER)
        self.assertEqual(len(rows) - 1, 6)
        for d, o, h, l, c, v, source in rows[1:]:  # noqa: E741
            DailyQuote(date.fromisoformat(d), Price.parse(o), Price.parse(h), Price.parse(l),
                       Price.parse(c), Volume.parse(v))
            self.assertEqual(source, "stooq")


class TestToBar(unittest.TestCase):
    def test_bar_shape(self):
        self.assertEqual(to_bar(stored()),
                         {"date": "2026-10-09", "o": 100.5, "h": 104.0, "l": 98.25, "c": 102.0,
                          "v": 1500000, "complete": True, "source": "store"})

    def test_numbers_are_float_and_int_like_yahoo(self):
        bar = to_bar(stored())
        self.assertEqual([type(bar[k]) for k in ("o", "h", "l", "c", "v")],
                         [float, float, float, float, int])

    def test_source_is_the_adapter_not_the_provider(self):
        self.assertEqual(to_bar(stored(source="stooq"))["source"], "store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
