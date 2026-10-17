"""market_data/importers/gpw.py — a saved GPW quotation archive page into store rows.

Offline, no mocks: every page is a real one saved in fixtures/gpw/, and every broken page is one of
them with a single edit, so a test fails for the reason it names and not because the page is fake.
"""
from __future__ import annotations

import os
import re
import unittest
from datetime import date
from decimal import Decimal

from support import FX
from market_data.importers import gpw
from market_data.importers.gpw import GpwFormatError
from market_data.model import DailyQuote, Isin, Price, Volume
from market_data.store_file import StoredQuote

PEO = Isin("PLPEKAO00016")
ALE = Isin("LU2237380790")
ASB = Isin("CY1000031710")
CAR = Isin("PLINTCS00010")
EBP = Isin("PLBZ00000044")
AMPLI = Isin("PLAMPLI00019")

# The nine traded rows of 2026-10-13 whose low sat above min(open, close) on the page as fetched on
# 2026-10-15. GPW later lowered them (and six more lows that already fitted); the page fetched on
# 2026-10-17 has none left.
LOW_ABOVE_OPEN_CLOSE_13_10 = {"ALLEGRO", "DINOPL", "INTERCARS", "KRUK", "PEPCO", "PKNORLEN", "PZU",
                              "SCANWAY", "XTB"}
LOWS_CORRECTED_13_10 = LOW_ABOVE_OPEN_CLOSE_13_10 | {"BNPPPL", "EUROCASH", "LPP", "PEKAO",
                                                     "QUERCUS", "ZABKA"}


def page(day: str) -> bytes:
    with open(os.path.join(FX, "gpw", f"archiwum_{day}.html"), "rb") as f:
        return f.read()


def text(day: str) -> str:
    return page(day).decode("utf-8")


def quote(session: date, o: str, h: str, l: str, c: str, v: int) -> DailyQuote:  # noqa: E741
    return DailyQuote(session, Price.parse(o), Price.parse(h), Price.parse(l), Price.parse(c),
                      Volume(v))


def outside_open_close(row: gpw.ArchiveRow) -> bool:
    return row.low > min(row.open, row.close) or row.high < max(row.open, row.close)


def row_span(html: str, isin: str) -> tuple[int, int]:
    """Where the <tr> of this ISIN starts and ends in the page."""
    start = html.rindex("<tr>", 0, html.index(f">{isin}</td>"))
    return start, html.index("</tr>", start)


def line_of(html: str, isin: str) -> int:
    return html.count("\n", 0, row_span(html, isin)[0]) + 1


def with_cell(html: str, isin: str, index: int, new: str | None) -> str:
    """The page with cell `index` of that ISIN's row replaced by `new`, or dropped when None."""
    start, end = row_span(html, isin)
    cell = list(re.finditer(r"<td[^>]*>.*?</td>", html[start:end], re.S))[index]
    a, b = start + cell.start(), start + cell.end()
    return html[:a] + ("" if new is None else f'<td class="text-right">{new}</td>') + html[b:]


class TestRealPages(unittest.TestCase):

    def test_a_session_has_every_row_and_leaves_out_the_rows_without_trades(self):
        for day, session, rows, without_trades in (
                ("11-06-2026", date(2026, 6, 11), 400, 33),
                ("12-06-2026", date(2026, 6, 12), 400, 26),
                ("13-10-2026", date(2026, 10, 13), 402, 25),
                ("16-10-2026", date(2026, 10, 16), 402, 35)):
            with self.subTest(day=day):
                table = gpw.table(page(day))
                parsed = gpw.parse(page(day), session)
                self.assertEqual(len(table), rows)
                self.assertEqual(sum(r.volume == 0 for r in table), without_trades)
                self.assertEqual(list(parsed), [r.isin for r in table if r.volume > 0])

    def test_every_row_is_the_named_session_from_gpw(self):
        session = date(2026, 10, 16)
        rows = gpw.parse(page("16-10-2026"), session).values()
        self.assertEqual({r.quote.session for r in rows}, {session})
        self.assertEqual({r.source for r in rows}, {"gpw"})

    def test_a_row_without_trades_is_on_the_page_but_is_no_session(self):
        # 2026-06-11: nothing traded, O=H=L=0 and the last price as close; zeros are no Price.
        ampli = next(r for r in gpw.table(page("11-06-2026")) if r.isin == AMPLI)
        self.assertEqual((ampli.open, ampli.high, ampli.low, ampli.close, ampli.volume),
                         (0, 0, 0, Decimal("1.15"), 0))
        self.assertNotIn(AMPLI, gpw.parse(page("11-06-2026"), date(2026, 6, 11)))

    def test_peo_on_the_session_before_its_ex_date(self):
        got = gpw.parse(page("11-06-2026"), date(2026, 6, 11))[PEO]
        self.assertEqual(got, StoredQuote(
            quote(date(2026, 6, 11), "237.70", "239.10", "235.50", "235.50", 567211), "gpw"))

    def test_peo_on_its_ex_date_is_the_unadjusted_session(self):
        # Dividend 19.77 went ex on 2026-06-12; the prices match Stooq's unadjusted export.
        got = gpw.parse(page("12-06-2026"), date(2026, 6, 12))[PEO]
        self.assertEqual(got.quote, quote(date(2026, 6, 12), "220.6", "230.4", "220.6", "228",
                                          729914))

    def test_the_change_column_is_never_read(self):
        # On PEO's ex-date it says +5,70 on a fall from 235.50 to 228: measured from an adjusted
        # reference price. Garbage there changes nothing.
        html = text("12-06-2026")
        garbled = with_cell(html, "PLPEKAO00016", 7, "not a number")
        self.assertNotEqual(garbled, html)
        session = date(2026, 6, 12)
        self.assertEqual(gpw.parse(garbled, session), gpw.parse(html, session))

    def test_five_names_on_16_10_match_stooq_to_the_grosz(self):
        # Prices cross-checked with Stooq's unadjusted export taken on 2026-10-16 at 18:01; volume
        # is the archive's own, final figure (ALE, EBP and CAR are above Stooq's snapshot).
        session = date(2026, 10, 16)
        got = gpw.parse(page("16-10-2026"), session)
        expected = {
            PEO: ("263.8", "267.2", "262.4", "267.2", 380320),
            ALE: ("54.44", "55.85", "54.17", "55.66", 7446187),
            ASB: ("174", "176.8", "168.5", "173", 404588),
            EBP: ("775.6", "783.6", "773.2", "778", 109020),
            CAR: ("1000", "1018", "1000", "1012", 12413),
        }
        for isin, values in expected.items():
            with self.subTest(isin=str(isin)):
                self.assertEqual(got[isin].quote, quote(session, *values))

    def test_prices_keep_the_text_gpw_wrote(self):
        got = gpw.parse(page("16-10-2026"), date(2026, 10, 16))[CAR].quote
        self.assertEqual((str(got.open), str(got.high)), ("1000.0000", "1018.0000"))

    def test_a_holiday_is_an_empty_answer(self):
        self.assertEqual(gpw.table(page("25-12-2025")), [])
        self.assertEqual(gpw.parse(page("25-12-2025"), date(2025, 12, 25)), {})

    def test_text_and_bytes_read_the_same(self):
        session = date(2026, 6, 11)
        self.assertEqual(gpw.parse(text("11-06-2026"), session),
                         gpw.parse(page("11-06-2026"), session))


class TestSessionGpwCorrected(unittest.TestCase):
    """2026-10-13 as GPW published it (fetched 2026-10-15) and as it reads after GPW lowered fifteen
    lows (fetched 2026-10-17). The parser takes each page as written."""

    def test_the_first_copy_has_nine_traded_rows_with_a_low_above_open_and_close(self):
        rows = gpw.table(page("13-10-2026_fetched-2026-10-15"))
        odd = {r.name for r in rows if r.volume > 0 and outside_open_close(r)}
        self.assertEqual(odd, LOW_ABOVE_OPEN_CLOSE_13_10)
        allegro = next(r for r in rows if r.isin == ALE)
        self.assertEqual((allegro.open, allegro.high, allegro.low, allegro.close, allegro.volume),
                         (Decimal("52.15"), Decimal("53.3"), Decimal("52.65"), Decimal("53.3"),
                          4640402))

    def test_the_corrected_copy_has_no_traded_row_outside_open_and_close(self):
        rows = gpw.table(page("13-10-2026"))
        self.assertEqual([r.name for r in rows if r.volume > 0 and outside_open_close(r)], [])
        allegro = next(r for r in rows if r.isin == ALE)
        self.assertEqual(allegro.low, Decimal("51.94"))

    def test_the_two_copies_differ_in_fifteen_lows_and_nothing_else(self):
        first = {r.isin: r for r in gpw.table(page("13-10-2026_fetched-2026-10-15"))}
        corrected = {r.isin: r for r in gpw.table(page("13-10-2026"))}
        self.assertEqual(first.keys(), corrected.keys())
        lowered = {r.name for isin, r in first.items() if r.low != corrected[isin].low}
        self.assertEqual(lowered, LOWS_CORRECTED_13_10)
        for isin, r in first.items():
            with self.subTest(name=r.name):
                c = corrected[isin]
                self.assertEqual((r.name, r.currency, r.open, r.high, r.close, r.volume),
                                 (c.name, c.currency, c.open, c.high, c.close, c.volume))
                self.assertLessEqual(c.low, r.low)

    # TODO(sim-fg4): remove @expectedFailure once DailyQuote accepts a low above min(open, close).
    # Until then DailyQuote refuses ALLEGRO and parse() rejects the page; the rows are pinned as
    # written by the table() test above. When sim-fg4 lands this test passes, which unittest
    # reports as an unexpected success and a failed run: that is the reminder to delete the line.
    @unittest.expectedFailure
    def test_parse_keeps_the_rows_outside_open_and_close_as_written(self):
        session = date(2026, 10, 13)
        got = gpw.parse(page("13-10-2026_fetched-2026-10-15"), session)
        self.assertEqual(len(got), 377)
        self.assertEqual(got[ALE].quote, quote(session, "52.15", "53.3", "52.65", "53.3", 4640402))


class TestRejectedPages(unittest.TestCase):
    """A page that has data rows and does not fit is GPW changing the page: the whole page is
    rejected, naming the row's line, and nothing is returned."""

    SESSION = date(2026, 6, 11)

    def assertRejected(self, html: str, line: int | None, *needles: str) -> None:
        for read in (gpw.table, lambda p: gpw.parse(p, self.SESSION)):
            with self.subTest(read=read), self.assertRaises(GpwFormatError) as cm:
                read(html)
            self.assertEqual(cm.exception.line, line)
            for needle in needles:
                self.assertIn(needle, str(cm.exception))

    def setUp(self):
        self.html = text("11-06-2026")
        self.peo_line = line_of(self.html, "PLPEKAO00016")

    def test_a_dropped_cell(self):
        self.assertRejected(with_cell(self.html, "PLPEKAO00016", 10, None), self.peo_line,
                            "PEKAO", "10 cells, expected 11")

    def test_an_extra_cell(self):
        html = with_cell(self.html, "PLPEKAO00016", 10, "1</td><td>2")
        self.assertRejected(html, self.peo_line, "PEKAO", "12 cells")

    def test_an_isin_with_a_wrong_check_digit(self):
        self.assertRejected(with_cell(self.html, "PLPEKAO00016", 1, "PLPEKAO00017"),
                            self.peo_line, "PEKAO", "PLPEKAO00017", "check digit")

    def test_a_number_that_is_not_one(self):
        for index, bad in ((3, "1,2,3"), (6, "235.5000"), (5, "-235,5000"), (4, "2 39,1000"),
                           (8, "567 211,5"), (8, "")):
            with self.subTest(index=index, bad=bad):
                self.assertRejected(with_cell(self.html, "PLPEKAO00016", index, bad),
                                    self.peo_line, "PEKAO", repr(bad))

    def test_a_currency_other_than_pln(self):
        self.assertRejected(with_cell(self.html, "PLPEKAO00016", 2, "EUR"), self.peo_line,
                            "PEKAO", "'EUR'", "no currency column")

    def test_a_malformed_row_without_trades_rejects_the_page_too(self):
        line = line_of(self.html, "PLAMPLI00019")
        self.assertRejected(with_cell(self.html, "PLAMPLI00019", 3, "0,0,0"), line, "AMPLI")

    def test_a_traded_row_with_a_zero_price_is_no_session(self):
        # table() reads it (a row without trades carries zeros too); parse() refuses it.
        html = with_cell(self.html, "PLPEKAO00016", 5, "0,0000")
        self.assertEqual(len(gpw.table(html)), 400)
        with self.assertRaises(GpwFormatError) as cm:
            gpw.parse(html, self.SESSION)
        self.assertEqual(cm.exception.line, self.peo_line)
        self.assertIn("PEKAO", str(cm.exception))

    def test_an_isin_twice(self):
        html = with_cell(self.html, "PLAMPLI00019", 1, "PLPEKAO00016")
        self.assertRejected(html, self.peo_line, "PEKAO", "PLPEKAO00016 again",
                            f"first on line {line_of(self.html, 'PLAMPLI00019')}")

    def test_columns_in_another_order(self):
        # High and low swapped would still give numbers; the header is what tells them apart.
        html = (self.html.replace(">Kurs maksymalny<", ">TMP<")
                .replace(">Kurs minimalny<", ">Kurs maksymalny<").replace(">TMP<", ">Kurs minimalny<"))
        first = gpw.table(self.html)[0].line
        self.assertRejected(html, first, "column headers", "Kurs minimalny")

    def test_no_data_rows_and_no_notice_is_not_an_empty_answer(self):
        html = text("25-12-2025").replace(gpw.NO_DATA, "Przerwa techniczna.")
        self.assertRejected(html, None, "not an archive page")

    def test_not_utf8(self):
        raw = page("11-06-2026")
        broken = raw.replace("Kurs zamknięcia".encode(), "Kurs zamkni\xeacia".encode("latin-1"))
        with self.assertRaises(GpwFormatError) as cm:
            gpw.table(broken)
        self.assertIn("not UTF-8", str(cm.exception))
        self.assertEqual(cm.exception.line, raw[:raw.index("Kurs zamkni".encode())].count(b"\n") + 1)


if __name__ == "__main__":
    unittest.main()
