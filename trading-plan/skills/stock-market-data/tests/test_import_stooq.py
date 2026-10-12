"""market_data/importers/stooq.py and scripts/import_quotes.py — a Stooq export into the store.

Offline, no mocks: exports are fixtures or files written to a temp directory, the store is a temp
directory, and main() takes `today` so the "closed sessions only" rule does not follow the clock.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from support import FX
import import_quotes
from market_data.importers import stooq
from market_data.importers.stooq import StooqFormatError

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


def run(argv, today=None):
    """main() -> (exit code, stdout, stderr); argparse's SystemExit counts as an exit code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = import_quotes.main(argv, today=today)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


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
