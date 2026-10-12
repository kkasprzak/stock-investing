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
from market_data.importers import stooq
from market_data.importers.stooq import StooqFormatError
from market_data.indicators import atr_wilder
from market_data.model import DailyQuote, Price, Volume
from market_data.store_file import StoredQuote, to_bar

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
    """Stooq's dividend de-adjustment leaves float noise in the last places; snap takes it off."""

    def test_noise_snaps_to_the_shortest_value_within_the_radius(self):
        self.assertEqual(stooq.snap("237.0994785"), "237.1")

    def test_two_places_stay_as_they_are(self):
        self.assertEqual(stooq.snap("19.77"), "19.77")
        self.assertEqual(stooq.snap("1234.51"), "1234.51")

    def test_radius_is_capped_at_a_tenth_of_a_grosz(self):
        # 1e-5 x 1234 would be 0.0123 and let 1234.5 through; the 0.001 cap keeps the grosz.
        self.assertEqual(stooq.snap("1234.5100003"), "1234.51")

    def test_nothing_within_the_radius_falls_back_to_four_places(self):
        self.assertEqual(stooq.snap("0.123456"), "0.1235")
        self.assertIsNone(stooq.shortest_within_radius(Decimal("0.123456")))

    def test_four_places_are_never_touched(self):
        self.assertEqual(stooq.snap("12.3400"), "12.3400")

    def test_text_that_is_not_a_long_decimal_passes_through_for_price_to_judge(self):
        for text in ("19", "-1.123456", "1e2", "nan", " 1.5", ""):
            with self.subTest(text=text):
                self.assertEqual(stooq.snap(text), text)


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

    def test_fractional_volume_names_the_old_history(self):
        # Stooq's history before 2022 carries de-adjusted, fractional volume.
        self.assertRejected(Path(FX) / "stooq_kgh_m.csv", 2, "2022")

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


class TestRealExports(unittest.TestCase):
    """Karol's own exports ("skip splits + dividends"): the noise guard and the ATR pins."""

    PEO = Path(FX) / "stooq_peo_d_raw.csv"
    ALE = Path(FX) / "stooq_ale_d_raw.csv"

    def price_texts(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            return [p for row in list(csv.reader(f))[1:] for p in row[1:5]]

    def test_every_noisy_peo_price_is_within_the_snap_radius(self):
        # The full 1998-2026 history peaked at 0.000999 off: zero slack. If a re-export ever
        # carries a value the radius does not cover, this names it before the store takes it.
        long = [t for t in self.price_texts(self.PEO) if len(t.partition(".")[2]) > 4]
        self.assertGreater(len(long), 1000)
        outside = [t for t in long if stooq.shortest_within_radius(Decimal(t)) is None]
        self.assertEqual(outside, [])

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

    def atr(self, path):
        bars = [to_bar(r) for r in stooq.parse(path) if r.quote.session <= date(2026, 10, 9)]
        return atr_wilder(bars)

    def test_peo_atr_pin(self):
        # Computed 2026-10-10 on the series with Stooq's candles swapped in (ADR 0000: the 110
        # honest sessions agree with Yahoo to the grosz, so a Stooq-only series gives the same).
        # That value was taken to the grosz; the four places are a regression pin from this fixture.
        rec = self.atr(self.PEO)
        self.assertEqual((rec["as_of"], round(rec["value"], 2)), ("2026-10-09", 7.52))
        self.assertEqual(rec["value"], 7.5209)

    def test_ale_atr_pin(self):
        # Regression pin, computed when this test was written (2026-10-12) from this fixture.
        rec = self.atr(self.ALE)
        self.assertEqual((rec["as_of"], rec["value"]), ("2026-10-09", ALE_ATR))


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

    def run_import(self, export: Path, key="PKN.PL", today=TODAY):
        code, out, err = run(["--store", str(self.store), "stooq", str(export), "--for", key],
                             today=today)
        return code, (json.loads(out) if out else None), err

    def test_first_import_creates_the_store_and_the_file(self):
        code, report, err = self.run_import(Path(FX) / "stooq_ale_d_raw.csv", "ALE.PL",
                                            today=date(2026, 10, 12))
        self.assertEqual((code, err), (0, ""))
        path = self.store / "LU2237380790.csv"
        self.assertEqual(report, {"isin": "LU2237380790", "key": "ALE.PL", "file": str(path),
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

    def test_an_isin_works_as_the_key(self):
        code, report, _ = self.run_import(self.export(PKN_EXPORT), key="PLPKN0000018")
        self.assertEqual((code, report["isin"], report["key"]), (0, "PLPKN0000018", "PLPKN0000018"))

    def read_store(self):
        with open(self.store / PKN_FILE, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))[1:]


class TestImportUsage(TempDir):
    """Usage errors exit 2 and touch nothing."""

    def test_store_is_required(self):
        code, _, err = run(["stooq", os.path.join(FX, "stooq_pkn_d.csv"), "--for", "PKN.PL"])
        self.assertEqual(code, 2)
        self.assertIn("--store", err)

    def test_unknown_ticker(self):
        store = self.tmp / "store"
        code, out, err = run(["--store", str(store), "stooq", os.path.join(FX, "stooq_pkn_d.csv"),
                              "--for", "ZZZ.PL"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("ZZZ.PL", err)
        self.assertFalse(store.exists())

    def test_unsubstituted_project_dir_is_refused_not_created(self):
        # A skill whose ${CLAUDE_PROJECT_DIR} was not substituted would hand the literal over.
        store = self.tmp / "${CLAUDE_PROJECT_DIR}" / "data" / "market-data"
        code, out, err = run(["--store", str(store), "stooq", os.path.join(FX, "stooq_pkn_d.csv"),
                              "--for", "PKN.PL"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("${", err)
        self.assertFalse((self.tmp / "${CLAUDE_PROJECT_DIR}").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
