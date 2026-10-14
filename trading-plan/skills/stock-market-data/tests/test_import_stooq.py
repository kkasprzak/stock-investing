"""market_data/importers/stooq.py and scripts/import_quotes.py — a Stooq export into the store.

Offline, no mocks: exports are fixtures or files written to a temp directory, the store is a temp
directory, and main() takes `today` so the "no session after today" rule does not follow the clock.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from support import FX
import import_quotes
from market_data import store_file
from market_data.adapters.store import StoreQuotes
from market_data.importers import stooq
from market_data.importers.stooq import StooqFormatError
from market_data.indicators import atr_wilder
from market_data.model import DailyQuote, DateRange, Instrument, Isin, Price, Volume
from market_data.store_file import StoredQuote

ALE_ATR = 1.2752            # regression pin: Wilder ATR(14) of stooq_ale_d_raw.csv as of 2026-10-09
PL_HEADER = "Data,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen\n"
EN_HEADER = "Date,Open,High,Low,Close,Volume\n"


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self, text: str, name: str = "export.csv") -> Path:
        path = self.tmp / name
        path.write_bytes(text.encode("utf-8"))
        return path


class TestSnap(unittest.TestCase):
    """Stooq's dividend de-adjustment leaves float noise in the last places; snap takes it off.
    The noise is relative (about 1e-5 of the value), so the radius is too."""

    def test_noise_snaps_to_the_shortest_value_within_the_radius(self):
        self.assertEqual(stooq.snap("237.0994785"), "237.1")

    def test_two_places_stay_as_they_are(self):
        self.assertEqual(stooq.snap("19.77"), "19.77")
        self.assertEqual(stooq.snap("1234.51"), "1234.51")

    def test_radius_grows_with_the_value(self):
        # LPP 2022-01-03 open, 0.136 off: noise on a five-digit price, inside 1e-5 x 17250 = 0.17.
        self.assertEqual(stooq.snap("17250.135879362"), "17250")
        # No cap: 1e-5 x 1234 = 0.0123 covers the grosz, so the shorter 1234.5 wins.
        self.assertEqual(stooq.snap("1234.5100003"), "1234.5")

    def test_nothing_within_the_radius_is_rejected_not_cut(self):
        self.assertIsNone(stooq.shortest_within_radius(Decimal("0.123456")))
        with self.assertRaises(ValueError) as cm:
            stooq.snap("0.123456")
        self.assertIn("0.123456", str(cm.exception))
        self.assertIn('"pomijaj splity + dywidendy"', str(cm.exception))
        self.assertIn("shorter range", str(cm.exception))

    def test_four_places_are_never_touched(self):
        self.assertEqual(stooq.snap("12.3400"), "12.3400")

    def test_text_that_is_not_a_long_decimal_passes_through_for_price_to_judge(self):
        for text in ("19", "-1.123456", "1e2", "nan", " 1.5", ""):
            with self.subTest(text=text):
                self.assertEqual(stooq.snap(text), text)


class TestSnapVolume(unittest.TestCase):
    """De-adjustment puts the same relative noise on volume: a fraction within 1e-5 of a whole
    number is that number; further off, the file is rejected."""

    def test_a_whole_number_stays_as_it_is(self):
        self.assertEqual(stooq.snap_volume("2559"), "2559")
        self.assertEqual(stooq.snap_volume("0"), "0")

    def test_noise_snaps_to_the_nearest_whole_number(self):
        # LPP 2022-01-03: 0.0073 off, inside 1e-5 x 2559 = 0.026.
        self.assertEqual(stooq.snap_volume("2558.9926927366"), "2559")

    def test_a_fraction_outside_the_radius_is_rejected_with_the_value(self):
        for text in ("469.68936359651",       # PEO 2004-12-24: 6.6e-4 off
                     "1.6740976690835"):      # LPP 2002-07-12: 0.19 off
            with self.subTest(text=text), self.assertRaises(ValueError) as cm:
                stooq.snap_volume(text)
            self.assertIn(text, str(cm.exception))
            self.assertIn('"pomijaj splity + dywidendy"', str(cm.exception))
            self.assertIn("shorter range", str(cm.exception))

    def test_what_is_not_a_plain_number_is_rejected(self):
        for text in ("-1", "1e2", "", " 5"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                stooq.snap_volume(text)


class TestParseRejects(TempDir):
    """Whatever parse rejects, it names the line; the first error rejects the whole file."""

    def assertRejected(self, path, line, why_part):
        with self.assertRaises(StooqFormatError) as cm:
            stooq.parse(path)
        self.assertEqual(cm.exception.line, line)
        self.assertIn(why_part, cm.exception.why)
        self.assertEqual(str(cm.exception), f"line {line}: {cm.exception.why}")

    def test_unknown_header(self):
        self.assertRejected(self.export("Date,Open,High,Low,Close\n2026-07-03,1,1,1,1\n"), 1,
                            "header")

    def test_header_with_bom(self):
        self.assertRejected(self.export("﻿" + PL_HEADER + "2026-07-03,1,1,1,1,1\n"), 1, "header")

    def test_empty_file(self):
        self.assertRejected(self.export(""), 1, "header")

    def test_wrong_number_of_columns(self):
        self.assertRejected(self.export(PL_HEADER + "2026-07-03,1,1,1,1,1\n2026-07-06,1,1,1,1\n"),
                            3, "6 columns")

    def test_blank_line(self):
        self.assertRejected(self.export(PL_HEADER + "2026-07-03,1,1,1,1,1\n\n2026-07-06,1,1,1,1,1\n"),
                            3, "6 columns")

    def test_date_not_iso(self):
        self.assertRejected(self.export(PL_HEADER + "20260703,1,1,1,1,1\n"), 2, "date")

    def assertNoiseRejected(self, row, value):
        path = self.export(PL_HEADER + row + "\n")
        self.assertRejected(path, 2, value)
        with self.assertRaises(StooqFormatError) as cm:
            stooq.parse(path)
        hint, history = (cm.exception.why.find('"pomijaj splity + dywidendy"'),
                         cm.exception.why.find("before ~2022"))
        self.assertTrue(0 <= hint < history, cm.exception.why)    # the export option comes first

    # Real rows from Karol's full-history exports (~/Downloads/{peo,lpp}_d.csv, not committed).

    def test_full_history_peo_volume_is_rejected(self):
        self.assertNoiseRejected("2004-12-24,133.99790082288,136.00011867238,133.99790082288,"
                                 "136.00011867238,469.68936359651", "469.68936359651")

    def test_full_history_lpp_volume_is_rejected(self):
        self.assertNoiseRejected("2002-07-12,107.99940756323,107.99940756323,107.99940756323,"
                                 "107.99940756323,1.6740976690835", "1.6740976690835")

    def test_a_price_outside_the_radius_is_rejected(self):
        # Made up: no real export has one yet. Cut to four places, it would be stored as a price.
        self.assertNoiseRejected("2026-07-06,0.123456,1,0.1,1,1", "0.123456")

    def test_negative_volume(self):
        self.assertRejected(self.export(PL_HEADER + "2026-07-03,1,1,1,1,-1\n"), 2, "volume")

    def test_monthly_export_has_a_weekend_session(self):
        self.assertRejected(Path(FX) / "stooq_lpp_m.csv", 3, "weekend")   # 2025-05-31, a Saturday

    def test_duplicate_date(self):
        self.assertRejected(self.export(PL_HEADER + "2026-07-03,1,1,1,1,1\n2026-07-03,1,1,1,1,1\n"),
                            3, "2026-07-03")

    def test_unsorted_dates(self):
        self.assertRejected(self.export(PL_HEADER + "2026-07-06,1,1,1,1,1\n2026-07-03,1,1,1,1,1\n"),
                            3, "2026-07-03")

    def test_not_utf8(self):
        path = self.tmp / "latin.csv"
        path.write_bytes(PL_HEADER.encode() + b"2026-07-03,1,1,1,1,1\n2026-07-06,\xff,1,1,1,1\n")
        self.assertRejected(path, 3, "UTF-8")


class TestParse(TempDir):
    def test_polish_header_with_crlf(self):
        rows = stooq.parse(Path(FX) / "stooq_pkn_d.csv")
        self.assertEqual(len(rows), 16)
        first = rows[0]
        self.assertEqual(first, StoredQuote(
            DailyQuote(date(2026, 7, 3), Price.parse("133.52"), Price.parse("133.62"),
                       Price.parse("131.28"), Price.parse("132.92"), Volume.parse("742988")),
            "stooq"))
        self.assertEqual(str(rows[1].quote.close), "133.5")       # the text as exported

    def test_english_header(self):
        rows = stooq.parse(self.export(EN_HEADER + "2026-07-03,10,12,9,11,500\r\n"
                                                   "2026-07-06,11,11.5,10.5,11.25,600\r\n"))
        self.assertEqual([(r.quote.session, str(r.quote.close), r.quote.volume.value, r.source)
                          for r in rows],
                         [(date(2026, 7, 3), "11", 500, "stooq"),
                          (date(2026, 7, 6), "11.25", 600, "stooq")])

    def test_header_only_is_no_rows(self):
        self.assertEqual(stooq.parse(self.export(PL_HEADER)), [])

    def test_prices_are_snapped_before_they_are_validated(self):
        # Unsnapped, low 100.0000004 is above close 100; snapped, both are 100 and the candle holds.
        rows = stooq.parse(self.export(PL_HEADER + "2026-07-03,100.5,101,100.0000004,100,10\n"))
        self.assertEqual((str(rows[0].quote.low), str(rows[0].quote.close)), ("100", "100"))

    def test_weekly_export_is_rejected_on_its_first_sunday(self):
        with self.assertRaises(StooqFormatError) as cm:
            stooq.parse(Path(FX) / "stooq_peo_w_raw.csv")             # 2026-01-04, a Sunday
        self.assertEqual(cm.exception.line, 2)
        self.assertIn("weekend", cm.exception.why)

    def test_price_rule_names_the_line(self):
        with self.assertRaises(StooqFormatError) as cm:
            stooq.parse(self.export(PL_HEADER + "2026-07-03,1,1,1,1,1\n2026-07-06,0,1,1,1,1\n"))
        self.assertEqual(cm.exception.line, 3)
        self.assertIn("price", cm.exception.why)

    def test_ohlc_rule_names_the_line(self):
        with self.assertRaises(StooqFormatError) as cm:
            stooq.parse(self.export(PL_HEADER + "2026-07-03,10,12,11,10,1\n"))   # low above close
        self.assertEqual(cm.exception.line, 2)
        self.assertIn("low", cm.exception.why)


class TestRealExports(TempDir):
    """Karol's own exports ("skip splits + dividends"): the noise guards and the ATR pins."""

    PEO = Path(FX) / "stooq_peo_d_raw.csv"
    ALE = Path(FX) / "stooq_ale_d_raw.csv"
    LPP = Path(FX) / "stooq_lpp_d_raw.csv"

    def columns(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))[1:]
        return [p for row in rows for p in row[1:5]], [row[5] for row in rows]

    def test_every_noisy_peo_price_is_within_the_snap_radius(self):
        # Peaks at 0.97e-5 off (the full 1998-2026 history at 0.99993e-5): little slack. If a
        # re-export ever carries a value the radius does not cover, this names it.
        prices, _ = self.columns(self.PEO)
        long = [t for t in prices if len(t.partition(".")[2]) > 4]
        self.assertGreater(len(long), 1000)
        outside = [t for t in long if stooq.shortest_within_radius(Decimal(t)) is None]
        self.assertEqual(outside, [])

    def test_every_noisy_lpp_value_is_within_the_snap_radius(self):
        # Five-digit prices: 0.136 off on 17250 is noise. Prices peak at 0.998e-5 off, volume at
        # 0.95e-5. Under the old 0.001 cap the prices kept three places of noise.
        prices, volumes = self.columns(self.LPP)
        long = [t for t in prices if len(t.partition(".")[2]) > 4]
        self.assertGreater(len(long), 4000)
        self.assertEqual([t for t in long if stooq.shortest_within_radius(Decimal(t)) is None], [])
        fractional = [t for t in volumes if "." in t]
        self.assertGreater(len(fractional), 1000)
        rejected = []
        for t in fractional:
            try:
                stooq.snap_volume(t)
            except ValueError:
                rejected.append(t)
        self.assertEqual(rejected, [])

    def test_lpp_parses_whole_to_the_price_grid(self):
        rows = stooq.parse(self.LPP)
        self.assertEqual((len(rows), rows[0].quote.session, rows[-1].quote.session),
                         (1196, date(2022, 1, 3), date(2026, 10, 12)))
        q = rows[0].quote   # 17250.135879362,17430.100107203,16360.045783182,16789.893585063,2558.99...
        self.assertEqual([str(p) for p in (q.open, q.high, q.low, q.close, q.volume)],
                         ["17250", "17430", "16360", "16790", "2559"])
        places = {len(str(p).partition(".")[2])
                  for r in rows for p in (r.quote.open, r.quote.high, r.quote.low, r.quote.close)}
        self.assertEqual(places, {0, 1})

    def test_peo_parses_whole(self):
        rows = stooq.parse(self.PEO)
        self.assertEqual((len(rows), rows[0].quote.session, rows[-1].quote.session),
                         (1195, date(2022, 1, 3), date(2026, 10, 9)))

    def test_peo_snapped_values(self):
        by_session = {r.quote.session: r.quote for r in stooq.parse(self.PEO)}
        q = by_session[date(2022, 1, 3)]       # 122.40046597261,126.95026207158,121.99973156924,124.6496720781
        self.assertEqual([str(p) for p in (q.open, q.high, q.low, q.close)],
                         ["122.4", "126.95", "122", "124.65"])
        q = by_session[date(2026, 10, 9)]      # exported clean: taken as written
        self.assertEqual([str(p) for p in (q.open, q.high, q.low, q.close)],
                         ["265", "265.5", "258.6", "261.1"])

    def atr(self, path, isin):
        """The way the CLI gets there: the import writes the store file, StoreQuotes reads it."""
        store_file.write(self.tmp / f"{isin}.csv", stooq.parse(path))
        instrument = Instrument(isin=Isin.parse(isin), symbols={})
        series = StoreQuotes(self.tmp).daily(
            instrument, DateRange(date(2026, 1, 1), date(2026, 10, 9)), now=0.0)
        return atr_wilder(list(series.bars))

    def test_peo_atr_pin(self):
        # Computed 2026-10-10 on the series with Stooq's candles swapped in (ADR 0000: the 110
        # honest sessions agree with Yahoo to the grosz, so a Stooq-only series gives the same).
        # That value was taken to the grosz; the four places are a regression pin from this fixture.
        rec = self.atr(self.PEO, "PLPEKAO00016")
        self.assertEqual((rec.as_of, round(rec.value, 2)), (date(2026, 10, 9), 7.52))
        self.assertAlmostEqual(rec.value, 7.5209, places=4)

    def test_ale_atr_pin(self):
        # Regression pin, computed when this test was written (2026-10-12) from this fixture.
        rec = self.atr(self.ALE, "LU2237380790")
        self.assertEqual(rec.as_of, date(2026, 10, 9))
        self.assertAlmostEqual(rec.value, ALE_ATR, places=4)


def run(argv, today=None):
    """main() -> (exit code, stdout, stderr); argparse's SystemExit counts as an exit code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = import_quotes.main(argv, today=today)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


TODAY = date(2026, 7, 8)        # a Wednesday; the inline exports below close on Tue 07-07
PKN_FILE = "PLPKN0000018.csv"
PKN_EXPORT = (PL_HEADER + "2026-07-03,133.52,133.62,131.28,132.92,742988\n"
                          "2026-07-06,133.24,133.58,131.88,133.5,868792\n"
                          "2026-07-07,133.5,134,132,133,500000\n")


class TestImport(TempDir):
    """main() end to end on a temp store: parse, merge, write, report."""

    def setUp(self):
        super().setUp()
        self.store = self.tmp / "data" / "market-data"           # does not exist yet
        self.store.parent.mkdir()                                # its parent does, as in a project

    def run_import(self, export: Path, isin="PLPKN0000018", today=TODAY):
        code, out, err = run(["--store", str(self.store), "stooq", str(export), "--for", isin],
                             today=today)
        return code, (json.loads(out) if out else None), err

    def test_first_import_creates_the_store_and_the_file(self):
        code, report, err = self.run_import(Path(FX) / "stooq_ale_d_raw.csv", "LU2237380790",
                                            today=date(2026, 10, 12))
        self.assertEqual((code, err), (0, ""))
        path = self.store / "LU2237380790.csv"
        self.assertEqual(report, {"isin": "LU2237380790", "file": str(path),
                                  "added": 114, "unchanged": 0, "changed": 0, "changed_dates": [],
                                  "imported": {"first": "2026-05-04", "last": "2026-10-09"}})
        self.assertTrue(path.read_bytes().startswith(b"date,open,high,low,close,volume,source\n"
                                                     b"2026-05-04,30,30.35,29.685,29.82,2488061,"
                                                     b"stooq\n"))

    def test_the_same_export_twice_changes_nothing(self):
        export = self.export(PKN_EXPORT)
        self.run_import(export)
        first = (self.store / PKN_FILE).read_bytes()
        code, report, _ = self.run_import(export)
        self.assertEqual(code, 0)
        self.assertEqual((report["added"], report["unchanged"], report["changed"]), (0, 3, 0))
        self.assertEqual((self.store / PKN_FILE).read_bytes(), first)

    def test_a_new_session_is_added_to_what_is_stored(self):
        self.run_import(self.export(PKN_EXPORT))
        code, report, _ = self.run_import(self.export(
            PL_HEADER + "2026-07-07,133.5,134,132,133,500000\n2026-07-08,133,135,132.5,134.1,1\n"),
            today=date(2026, 7, 9))
        self.assertEqual((code, report["added"], report["unchanged"]), (0, 1, 1))
        self.assertEqual(len(self.read_store()), 4)

    def test_a_changed_close_is_reported_with_its_date(self):
        self.run_import(self.export(PKN_EXPORT))
        code, report, _ = self.run_import(self.export(PKN_EXPORT.replace(",133,500000",
                                                                         ",133.2,500000")))
        self.assertEqual((code, report["changed"], report["changed_dates"], report["unchanged"]),
                         (0, 1, ["2026-07-07"], 2))
        self.assertEqual(self.read_store()[-1][4], "133.2")

    def test_todays_session_is_imported(self):
        # A row in Stooq's daily export is a closed session, today's included.
        code, report, _ = self.run_import(self.export(PKN_EXPORT), today=date(2026, 7, 7))
        self.assertEqual((code, report["added"]), (0, 3))
        self.assertEqual(report["imported"], {"first": "2026-07-03", "last": "2026-07-07"})
        self.assertEqual([r[0] for r in self.read_store()],
                         ["2026-07-03", "2026-07-06", "2026-07-07"])

    def test_a_header_only_export_writes_nothing(self):
        code, report, _ = self.run_import(self.export(PL_HEADER))
        self.assertEqual((code, report["added"], report["imported"]),
                         (0, 0, {"first": None, "last": None}))
        self.assertFalse(self.store.exists())

    def test_a_session_after_today_rejects_the_file(self):
        code, report, err = self.run_import(self.export(PKN_EXPORT), today=date(2026, 7, 6))
        self.assertEqual((code, report), (1, None))
        self.assertIn("line 4:", err)
        self.assertIn("2026-07-07", err)
        self.assertFalse(self.store.exists())

    def test_a_bad_row_rejects_the_file_and_leaves_the_store_byte_for_byte(self):
        self.run_import(self.export(PKN_EXPORT))
        before = (self.store / PKN_FILE).read_bytes()
        code, report, err = self.run_import(self.export(
            PKN_EXPORT + "2026-07-08,133,135,136,134.1,1\n"), today=date(2026, 7, 9))  # low > high
        self.assertEqual((code, report), (1, None))
        self.assertIn("line 5:", err)
        self.assertEqual((self.store / PKN_FILE).read_bytes(), before)

    def test_a_broken_store_file_is_not_overwritten(self):
        self.store.mkdir(parents=True)
        (self.store / PKN_FILE).write_bytes(b"not,a,store,file\n")
        code, report, err = self.run_import(self.export(PKN_EXPORT))
        self.assertEqual((code, report), (1, None))
        self.assertIn(PKN_FILE, err)
        self.assertEqual((self.store / PKN_FILE).read_bytes(), b"not,a,store,file\n")

    def test_a_missing_export_is_rejected(self):
        code, report, err = self.run_import(self.tmp / "nope.csv")
        self.assertEqual((code, report), (1, None))
        self.assertIn("nope.csv", err)
        self.assertFalse(self.store.exists())

    def test_an_isin_outside_the_symbol_map_is_imported(self):
        """The store file is named by the ISIN alone; the map is not consulted."""
        code, report, err = self.run_import(self.export(PKN_EXPORT), "US0378331005")
        self.assertEqual((code, err, report["isin"], report["added"]), (0, "", "US0378331005", 3))
        self.assertTrue((self.store / "US0378331005.csv").exists())

    def read_store(self):
        with open(self.store / PKN_FILE, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))[1:]


class TestImportUsage(TempDir):
    """Usage errors exit 2 and touch nothing."""

    def test_store_is_required(self):
        code, _, err = run(["stooq", os.path.join(FX, "stooq_pkn_d.csv"), "--for", "PLPKN0000018"])
        self.assertEqual(code, 2)
        self.assertIn("--store", err)

    def test_for_takes_an_isin_only(self):
        """Checked strictly: a broker ticker, a wrong check digit, lower case and padding are
        refused before anything is read or written."""
        store = self.tmp / "store"
        for key in ("PKN.PL", "PLPKN0000019", "plpkn0000018", " PLPKN0000018"):
            with self.subTest(key=key):
                code, out, err = run(["--store", str(store), "stooq",
                                      os.path.join(FX, "stooq_pkn_d.csv"), "--for", key])
                self.assertEqual((code, out), (2, ""))
                self.assertIn(repr(key), err)
                self.assertFalse(store.exists())

    def test_unsubstituted_project_dir_is_refused_not_created(self):
        # A skill whose ${CLAUDE_PROJECT_DIR} was not substituted would hand the literal over.
        store = self.tmp / "${CLAUDE_PROJECT_DIR}" / "data" / "market-data"
        code, out, err = run(["--store", str(store), "stooq", os.path.join(FX, "stooq_pkn_d.csv"),
                              "--for", "PLPKN0000018"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("${", err)
        self.assertFalse((self.tmp / "${CLAUDE_PROJECT_DIR}").exists())


class TestImportStorePath(TempDir):
    """Where --store points: a missing parent is a usage error, a store that cannot be written is a
    rejection, and neither ends in a traceback."""

    def setUp(self):
        super().setUp()
        self.read_only = []                 # given write back before tearDown removes the temp dir

    def tearDown(self):
        for path in self.read_only:
            path.chmod(0o755)
        super().tearDown()

    def make_read_only(self, path: Path):
        path.chmod(0o555)
        self.read_only.append(path)

    def run_import(self, store: Path):
        return run(["--store", str(store), "stooq", str(self.export(PKN_EXPORT)),
                    "--for", "PLPKN0000018"],
                   today=TODAY)

    def assertRejectedCleanly(self, code, out, err):
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("import rejected, nothing written: "), err)
        self.assertNotIn("Traceback", err)

    def test_store_whose_parent_is_missing_is_a_usage_error_and_creates_nothing(self):
        # An empty ${CLAUDE_PROJECT_DIR} expands to '', and --store reads /data/market-data.
        store = self.tmp / "data" / "market-data"
        code, out, err = self.run_import(store)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"parent directory '{self.tmp / 'data'}' does not exist", err)
        self.assertIn("was ${CLAUDE_PROJECT_DIR} substituted?", err)
        self.assertFalse((self.tmp / "data").exists())

    def test_store_that_is_a_file_is_rejected_and_the_file_left_alone(self):
        store = self.tmp / "market-data"
        store.write_bytes(b"not a directory\n")
        code, out, err = self.run_import(store)
        self.assertRejectedCleanly(code, out, err)
        self.assertIn(str(store), err)
        self.assertEqual(store.read_bytes(), b"not a directory\n")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_store_without_write_permission_is_rejected(self):
        store = self.tmp / "market-data"
        store.mkdir()
        self.make_read_only(store)
        code, out, err = self.run_import(store)
        self.assertRejectedCleanly(code, out, err)
        self.assertEqual(os.listdir(store), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_store_that_cannot_be_created_is_rejected(self):
        parent = self.tmp / "data"
        parent.mkdir()
        self.make_read_only(parent)
        code, out, err = self.run_import(parent / "market-data")
        self.assertRejectedCleanly(code, out, err)
        self.assertEqual(os.listdir(parent), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
