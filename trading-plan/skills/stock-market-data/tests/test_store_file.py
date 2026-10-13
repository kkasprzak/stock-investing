"""market_data.store_file — the candle store's file schema and the stored row."""
from __future__ import annotations

import csv
import os
import shutil
import stat
import tempfile
import unittest
from datetime import date
from pathlib import Path

import support  # noqa: F401  (puts scripts/ on sys.path)
from support import FX
from market_data.model import DailyQuote, Price, Volume
from market_data.store_file import (ENCODING, HEADER, LINE_TERMINATOR, StoredQuote, StoreFileError,
                                    merge, read, write)

STORE_PKN = os.path.join(FX, "store", "PLPKN0000018.csv")


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


def row(day, c="102", source="stooq", o="100.50", h="104", l="98.25", v="1500000"):  # noqa: E741
    """A StoredQuote on 2026-10-<day>; close defaults inside the fixed high/low."""
    q = DailyQuote(date(2026, 10, day), Price.parse(o), Price.parse(h), Price.parse(l),
                   Price.parse(c), Volume.parse(v))
    return StoredQuote(q, source)


def fixture_rows(path):
    """The store fixture's rows, built straight from its text (independent of any reader)."""
    with open(path, encoding=ENCODING, newline="") as f:
        rows = list(csv.reader(f))[1:]
    return [StoredQuote(DailyQuote(date.fromisoformat(d), Price.parse(o), Price.parse(h),
                                   Price.parse(l), Price.parse(c), Volume.parse(v)), source)
            for d, o, h, l, c, v, source in rows]  # noqa: E741


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "PLPKN0000018.csv"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip_is_byte_for_byte(self):
        # LF, no BOM, header, ISO dates, prices exactly as parsed ("103.50", "107.50" stay).
        write(self.path, fixture_rows(STORE_PKN))
        self.assertEqual(self.path.read_bytes(), Path(STORE_PKN).read_bytes())

    def test_round_trip_through_read(self):
        write(self.path, read(Path(STORE_PKN)))
        self.assertEqual(self.path.read_bytes(), Path(STORE_PKN).read_bytes())
        rows = [row(8, c="101.10"), row(9, source="other")]
        write(self.path, rows)
        self.assertEqual(read(self.path), rows)

    def test_sorts_by_session(self):
        write(self.path, list(reversed(fixture_rows(STORE_PKN))))
        self.assertEqual(self.path.read_bytes(), Path(STORE_PKN).read_bytes())

    def test_replaces_an_existing_file_and_leaves_nothing_beside_it(self):
        self.path.write_bytes(b"old\n")
        write(self.path, [row(9)])
        self.assertEqual(self.path.read_text(encoding=ENCODING),
                         "date,open,high,low,close,volume,source\n"
                         "2026-10-09,100.50,104,98.25,102,1500000,stooq\n")
        self.assertEqual(os.listdir(self.tmp), [self.path.name])

    def test_file_mode_is_an_ordinary_files_not_the_temp_files(self):
        write(self.path, [row(9)])                              # new file: rw-r--r--
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        self.path.chmod(0o664)
        write(self.path, [row(8), row(9)])                      # existing file keeps its mode
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o664)

    def test_duplicate_session_is_the_callers_bug(self):
        with self.assertRaisesRegex(ValueError, "2026-10-09"):
            write(self.path, [row(9), row(9, c="101")])

    def test_weekend_session_is_the_callers_bug(self):
        with self.assertRaisesRegex(ValueError, "2026-10-10"):
            write(self.path, [row(9), row(10)])                 # 2026-10-10 is a Saturday

    def test_a_rejected_write_leaves_the_file_as_it_was(self):
        self.path.write_bytes(b"old\n")
        with self.assertRaises(ValueError):
            write(self.path, [row(9), row(9)])
        self.assertEqual(self.path.read_bytes(), b"old\n")
        self.assertEqual(os.listdir(self.tmp), [self.path.name])


class TestMerge(unittest.TestCase):
    def test_new_sessions_are_added_in_order(self):
        result = merge([row(7), row(9)], [row(8), row(12)])
        self.assertEqual([r.quote.session.day for r in result.rows], [7, 8, 9, 12])
        self.assertEqual((result.added, result.unchanged, result.changed, result.changed_dates),
                         (2, 0, 0, ()))

    def test_into_an_empty_store(self):
        result = merge([], [row(8), row(9)])
        self.assertEqual((len(result.rows), result.added), (2, 2))

    def test_same_quote_is_unchanged(self):
        result = merge([row(8), row(9)], [row(8), row(9)])
        self.assertEqual((result.added, result.unchanged, result.changed), (0, 2, 0))

    def test_equal_by_value_is_unchanged_and_keeps_the_stored_text(self):
        # 133.5 == 133.50: not a change, and a re-import must not churn the file's text either.
        result = merge([row(9, c="102.50")], [row(9, c="102.5")])
        self.assertEqual((result.unchanged, result.changed), (1, 0))
        self.assertEqual(str(result.rows[0].quote.close), "102.50")

    def test_source_is_not_part_of_the_comparison(self):
        result = merge([row(9, source="other")], [row(9, source="stooq")])
        self.assertEqual((result.unchanged, result.changed), (1, 0))

    def test_a_different_quote_is_changed_and_incoming_wins(self):
        result = merge([row(7), row(8), row(9)], [row(8, c="101"), row(9), row(12)])
        self.assertEqual((result.added, result.unchanged, result.changed, result.changed_dates),
                         (1, 1, 1, (date(2026, 10, 8),)))
        self.assertEqual([str(r.quote.close) for r in result.rows], ["102", "101", "102", "102"])

    def test_volume_alone_is_a_change(self):
        result = merge([row(9)], [row(9, v="1500001")])
        self.assertEqual(result.changed_dates, (date(2026, 10, 9),))

    def test_duplicate_session_on_either_side_is_the_callers_bug(self):
        with self.assertRaisesRegex(ValueError, "2026-10-09"):
            merge([row(9), row(9)], [])
        with self.assertRaisesRegex(ValueError, "2026-10-09"):
            merge([], [row(9), row(9, c="101")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
