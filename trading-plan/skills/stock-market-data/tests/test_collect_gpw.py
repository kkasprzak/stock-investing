"""scripts/collect_gpw.py — one session of the GPW quotation archive into the gpw store.

Offline, no mocks: the archive is a fake opener serving the real pages saved in fixtures/gpw/ (or a
scripted failure), the pause is a list the sleep appends to, the store is a temp directory, and
main() takes `today` so neither the default session nor "no session after today" follows the clock.
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
import urllib.error
from datetime import date, datetime
from pathlib import Path

from support import FX
import collect_gpw

GPW_FX = Path(FX) / "gpw"
PEO_FILE = "PLPEKAO00016.csv"
FRI_16_10 = date(2026, 10, 16)
TUE_13_10 = date(2026, 10, 13)
RESET = ConnectionResetError(54, "Connection reset by peer")


def page(name: str) -> bytes:
    return (GPW_FX / name).read_bytes()


PAGE_16_10 = page("archiwum_16-10-2026.html")       # 402 rows, 35 with volume 0
PAGE_13_10 = page("archiwum_13-10-2026.html")       # as fetched on 2026-10-17, after GPW's fix
PAGE_13_10_FIRST = page("archiwum_13-10-2026_fetched-2026-10-15.html")   # before it: 15 lows higher
PAGE_HOLIDAY = page("archiwum_25-12-2025.html")     # no rows, "Brak danych dla wybranych kryteriów."


class Opener:
    """Stands in for urllib.request.urlopen: answers each request with the next scripted outcome (a
    page in bytes, or an exception to raise) and records the requests it was given."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(outcome)


class Collect(unittest.TestCase):
    """main() over a temp gpw store whose parent exists, as in a project."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.gpw = self.tmp / "data" / "gpw"                     # does not exist yet
        self.gpw.parent.mkdir()
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def collect(self, *outcomes, session: date | None = FRI_16_10, today: date = FRI_16_10,
                gpw: Path | None = None):
        """main() -> (exit code, the report or None, stderr, the opener)."""
        opener = Opener(*outcomes)
        argv = ["--gpw", str(gpw or self.gpw)]
        if session is not None:
            argv += ["--date", session.isoformat()]
        code, out, err = run(argv, today=today, opener=opener, sleep=self.sleeps.append)
        return code, (json.loads(out) if out else None), err, opener

    def files(self):
        return sorted(os.listdir(self.gpw)) if self.gpw.exists() else []

    def rows(self, name=PEO_FILE):
        with open(self.gpw / name, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))


def run(argv, **kwargs):
    """main() -> (exit code, stdout, stderr); argparse's SystemExit counts as an exit code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = collect_gpw.main(argv, **kwargs)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TestCollect(Collect):
    def test_a_published_session_writes_one_file_per_traded_isin(self):
        code, report, err, _ = self.collect(PAGE_16_10)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(self.files()), 367)                 # 402 rows minus 35 with volume 0
        self.assertEqual(self.rows(), [["date", "open", "high", "low", "close", "volume", "source"],
                                       ["2026-10-16", "263.8000", "267.2000", "262.4000",
                                        "267.2000", "380320", "gpw"]])     # prices as GPW wrote them
        fetched_at = report.pop("fetched_at")
        self.assertIsNotNone(datetime.fromisoformat(fetched_at).tzinfo)
        self.assertEqual(report, {"session": "2026-10-16", "dir": str(self.gpw), "empty": False,
                                  "rows": 367, "skipped_volume_0": 35,
                                  "added": 367, "unchanged": 0, "changed": 0, "changed_isins": []})

    def test_the_request_names_the_session_and_looks_like_a_browser(self):
        _, _, _, opener = self.collect(PAGE_16_10)
        (request,) = opener.requests
        self.assertEqual(request.full_url, "https://www.gpw.pl/archiwum-notowan-full"
                                           "?type=10&instrument=&date=16-10-2026")
        self.assertTrue(request.get_header("User-agent").startswith("Mozilla/5.0 ("))
        self.assertEqual(request.get_header("Accept-language"), "pl-PL,pl;q=0.9")
        # Live, 2026-10-17: without Accept the server reset urllib's request three times in a row;
        # with it, the page came at once (curl always sends one, so curl never showed the need).
        self.assertTrue(request.get_header("Accept").startswith("text/html,"))

    def test_without_a_date_today_is_collected(self):
        code, report, _, opener = self.collect(PAGE_16_10, session=None, today=FRI_16_10)
        self.assertEqual((code, report["session"], report["added"]), (0, "2026-10-16", 367))
        self.assertTrue(opener.requests[0].full_url.endswith("&date=16-10-2026"))

    def test_a_past_session_is_written_under_its_own_date(self):
        code, report, _, _ = self.collect(PAGE_13_10, session=TUE_13_10, today=FRI_16_10)
        self.assertEqual((code, report["session"], report["rows"]), (0, "2026-10-13", 377))
        self.assertEqual(self.rows()[1][0], "2026-10-13")

    def test_an_empty_page_writes_nothing_and_says_so(self):
        # A holiday and a session not yet published look the same: no rows, "Brak danych".
        code, report, err, _ = self.collect(PAGE_HOLIDAY)
        self.assertEqual((code, err), (0, ""))
        report.pop("fetched_at")
        self.assertEqual(report, {"session": "2026-10-16", "dir": str(self.gpw), "empty": True,
                                  "rows": 0, "skipped_volume_0": 0,
                                  "added": 0, "unchanged": 0, "changed": 0, "changed_isins": []})
        self.assertFalse(self.gpw.exists())

    def test_the_same_page_twice_rewrites_no_file(self):
        self.collect(PAGE_16_10)
        past = 1_700_000_000
        for name in self.files():
            os.utime(self.gpw / name, (past, past))
        code, report, _, _ = self.collect(PAGE_16_10)
        self.assertEqual((code, report["added"], report["unchanged"], report["changed"]),
                         (0, 0, 367, 0))
        self.assertEqual({(self.gpw / n).stat().st_mtime for n in self.files()}, {past})

    def test_a_corrected_page_replaces_the_session_and_names_the_isins(self):
        # GPW lowered fifteen lows of 13.10 between the 15.10 and the 17.10 fetch (sim-xa6).
        self.collect(PAGE_13_10_FIRST, session=TUE_13_10)
        self.assertEqual(self.rows()[1][3], "264.3000")
        code, report, _, _ = self.collect(PAGE_13_10, session=TUE_13_10)
        self.assertEqual((code, report["changed"], report["unchanged"], report["added"]),
                         (0, 15, 362, 0))
        self.assertIn("PLPEKAO00016", report["changed_isins"])
        self.assertEqual(report["changed_isins"], sorted(report["changed_isins"]))
        self.assertEqual(self.rows()[1][3], "261.9000")

    def test_other_sessions_in_a_file_are_kept(self):
        self.collect(PAGE_13_10, session=TUE_13_10)
        code, report, _, _ = self.collect(PAGE_16_10)
        self.assertEqual((code, report["added"]), (0, 367))
        self.assertEqual([r[0] for r in self.rows()[1:]], ["2026-10-13", "2026-10-16"])


class TestCollectRetries(Collect):
    """The server often resets the connection: tried again after a pause, never after the last try;
    once the tries run out, exit 3 and nothing written."""

    def test_a_reset_then_the_page_pauses_once_and_writes(self):
        code, report, _, opener = self.collect(RESET, PAGE_16_10)
        self.assertEqual((code, report["added"]), (0, 367))
        self.assertEqual((len(opener.requests), self.sleeps), (2, [collect_gpw.PAUSE]))
        self.assertGreaterEqual(collect_gpw.PAUSE, 30)              # Karol's rule: human pace

    def test_three_failed_tries_exit_3_and_write_nothing(self):
        refused = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        code, report, err, opener = self.collect(RESET, TimeoutError("timed out"), refused)
        self.assertEqual((code, report), (3, None))
        self.assertEqual((len(opener.requests), self.sleeps), (3, [collect_gpw.PAUSE] * 2))
        self.assertIn("3 tries", err)
        self.assertIn("Connection refused", err)                 # the last try's reason
        self.assertNotIn("Traceback", err)
        self.assertFalse(self.gpw.exists())

    def test_an_http_error_is_an_answer_and_not_tried_again(self):
        forbidden = urllib.error.HTTPError("https://www.gpw.pl/", 403, "Forbidden", {}, None)
        code, report, err, opener = self.collect(forbidden)
        self.assertEqual((code, report), (3, None))
        self.assertEqual((len(opener.requests), self.sleeps), (1, []))
        self.assertIn("HTTP 403", err)
        self.assertFalse(self.gpw.exists())


class TestCollectRejected(Collect):
    """Exit 1 and nothing written: a page the parser no longer accepts (ADR 0005: the source stops
    until the parser is fixed), and a store file that is not one."""

    def test_a_changed_page_exits_1_and_writes_nothing(self):
        changed = PAGE_16_10.replace("Kurs otwarcia".encode(), b"Otwarcie")
        code, report, err, _ = self.collect(changed)
        self.assertEqual((code, report), (1, None))
        self.assertTrue(err.startswith("collect rejected, nothing written: "), err)
        self.assertIn("line ", err)
        self.assertFalse(self.gpw.exists())

    def test_a_broken_store_file_stops_the_run_before_any_file_is_written(self):
        self.gpw.mkdir()
        (self.gpw / PEO_FILE).write_bytes(b"not,a,store,file\n")
        code, report, err, _ = self.collect(PAGE_16_10)
        self.assertEqual((code, report), (1, None))
        self.assertIn(PEO_FILE, err)
        self.assertEqual(self.files(), [PEO_FILE])
        self.assertEqual((self.gpw / PEO_FILE).read_bytes(), b"not,a,store,file\n")

    def test_a_gpw_dir_that_is_a_file_is_rejected_and_left_alone(self):
        self.gpw.write_bytes(b"not a directory\n")
        code, report, err, _ = self.collect(PAGE_16_10)
        self.assertEqual((code, report), (1, None))
        self.assertIn(str(self.gpw), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.gpw.read_bytes(), b"not a directory\n")


class TestCollectUsage(Collect):
    """Usage errors exit 2, before any request, and touch nothing."""

    def assertUsage(self, code, report, opener):
        self.assertEqual((code, report, opener.requests), (2, None, []))
        self.assertFalse(self.gpw.exists())

    def test_gpw_is_required(self):
        code, _, err = run(["--date", "2026-10-16"], today=FRI_16_10, opener=Opener(),
                           sleep=self.sleeps.append)
        self.assertEqual(code, 2)
        self.assertIn("--gpw", err)

    def test_a_weekend_date_is_no_session(self):
        code, report, err, opener = self.collect(session=date(2026, 10, 17), today=date(2026, 10, 19))
        self.assertUsage(code, report, opener)
        self.assertIn("Saturday", err)

    def test_today_on_a_weekend_is_no_session(self):
        code, report, err, opener = self.collect(session=None, today=date(2026, 10, 18))
        self.assertUsage(code, report, opener)
        self.assertIn("Sunday", err)
        self.assertIn("--date", err)

    def test_a_date_after_today_is_refused(self):
        code, report, err, opener = self.collect(session=date(2026, 10, 19), today=FRI_16_10)
        self.assertUsage(code, report, opener)
        self.assertIn("after today 2026-10-16", err)

    def test_a_date_that_is_not_yyyy_mm_dd_is_refused(self):
        for text in ("16-10-2026", "20261016", "2026-10-32"):
            with self.subTest(text=text):
                code, _, err = run(["--gpw", str(self.gpw), "--date", text], today=FRI_16_10,
                                   opener=Opener(), sleep=self.sleeps.append)
                self.assertEqual(code, 2)
                self.assertIn(repr(text), err)
                self.assertFalse(self.gpw.exists())

    def test_unsubstituted_project_dir_is_refused_not_created(self):
        gpw = self.tmp / "${CLAUDE_PROJECT_DIR}" / "data" / "gpw"
        code, report, err, opener = self.collect(gpw=gpw)
        self.assertUsage(code, report, opener)
        self.assertIn("${", err)
        self.assertFalse((self.tmp / "${CLAUDE_PROJECT_DIR}").exists())

    def test_gpw_dir_whose_parent_is_missing_is_refused_not_created(self):
        # An empty ${CLAUDE_PROJECT_DIR} expands to '', and --gpw reads /data/gpw.
        gpw = self.tmp / "nowhere" / "gpw"
        code, report, err, opener = self.collect(gpw=gpw)
        self.assertUsage(code, report, opener)
        self.assertIn(f"parent directory '{self.tmp / 'nowhere'}' does not exist", err)
        self.assertFalse((self.tmp / "nowhere").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
