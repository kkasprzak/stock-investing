"""A saved page of the GPW quotation archive read into store rows, one per ISIN, for one session.

The page (https://www.gpw.pl/archiwum-notowan-full?type=10&instrument=&date=DD-MM-YYYY) is the
whole equity market for one session: a table whose header is HEADER and whose data rows are <tr>
with 11 <td> in the same order. Numbers use a space or NBSP between thousands and a comma before
the decimals ("4 248 811", "1 014,0000").

What is read and what is not:
- Only name, ISIN, currency, open, high, low, close and volume. "Zmiana kursu %" is measured from a
  dividend-adjusted reference price (PEO on its 2026-06-12 ex-date shows +5.70% on a fall from
  235.50 to 228.00), so it is never read; trades and turnover are not stored.
- A row with volume 0 is not a session: nothing traded, and its prices are no trades (O=H=L=0 with
  the last price as close). parse() leaves it out; table() still checks it is well formed.
- A row whose low or high does not fit its open and close is kept as written: GPW published it,
  and whether to trust it is the reader's call, not the parser's.
- A page with no data rows that says NO_DATA (a holiday, a session not yet published) is an empty
  answer. A page with neither is not one: whatever it is, it is not the archive saying "nothing".
- Anything else that does not fit (headers, cell count, ISIN, currency, a number, an ISIN twice)
  rejects the whole page with the row's line: GPW changed the page, and stopping beats storing
  rubbish. A currency other than PLN is rejected too: the store has no currency column, so such a
  row would pass for zlotys. None has been seen; one appearing is a decision to make, not to guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

from market_data.model import DailyQuote, Isin, Price, Volume
from market_data.store_file import StoredQuote

SOURCE = "gpw"
CURRENCY = "PLN"
NO_DATA = "Brak danych dla wybranych kryteriów."
HEADER = ("Nazwa", "Kod ISIN", "Waluta", "Kurs otwarcia", "Kurs maksymalny", "Kurs minimalny",
          "Kurs zamknięcia", "Zmiana kursu %", "Wolumen obrotu (w szt.)", "Liczba transakcji",
          "Wartość obrotu (w tys.)")
DATA_ROW_MIN_CELLS = 10     # a <tr> with fewer <td> belongs to the page layout, not the table

_NAME, _ISIN, _CURRENCY, _OPEN, _HIGH, _LOW, _CLOSE, _CHANGE, _VOLUME = range(9)
_DECIMAL = re.compile(r"\d{1,3}(?: \d{3})*(?:,\d+)?")
_WHOLE = re.compile(r"\d{1,3}(?: \d{3})*")


class GpwFormatError(Exception):
    """The page is not one this parser accepts. `line` is the page's line of the offending row
    (1-based), None when the problem is the page as a whole."""

    def __init__(self, line: int | None, why: str) -> None:
        super().__init__(f"line {line}: {why}" if line else why)
        self.line = line
        self.why = why


@dataclass(frozen=True)
class ArchiveRow:
    """One data row as GPW published it, its numbers parsed and nothing judged: prices are
    Decimals because a row without trades carries zeros, which no Price is."""

    line: int
    name: str
    isin: Isin
    currency: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class _Table(HTMLParser):
    """Every <tr> of the page as (line, tag of its cells, cell texts with whitespace collapsed).
    NBSP is whitespace to str.split, so "4\xa0248\xa0811" comes out as "4 248 811"."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[int, str, list[str]]] = []
        self.text: list[str] = []
        self._row: tuple[int, list[str], list[str]] | None = None   # line, tags, cells
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._end_row()
            self._row = (self.getpos()[0], [], [])
        elif tag in ("td", "th") and self._row is not None:
            self._end_cell()
            self._row[1].append(tag)
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()

    def handle_data(self, data):
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def close(self):
        super().close()
        self._end_row()

    def _end_cell(self):
        if self._cell is not None and self._row is not None:
            self._row[2].append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _end_row(self):
        self._end_cell()
        if self._row is not None:
            line, tags, cells = self._row
            kind = "td" if tags and all(t == "td" for t in tags) else "th" if tags else ""
            self.rows.append((line, kind, cells))
        self._row = None


def _decode(page: bytes | str) -> str:
    if isinstance(page, str):
        return page
    try:
        return page.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GpwFormatError(page[:e.start].count(b"\n") + 1, "not UTF-8 text") from None


def _decimal(text: str, column: str) -> Decimal:
    if not _DECIMAL.fullmatch(text):
        raise ValueError(f"{column} {text!r} is not a number like 1 014,0000")
    return Decimal(text.replace(" ", "").replace(",", "."))


def _whole(text: str, column: str) -> int:
    if not _WHOLE.fullmatch(text):
        raise ValueError(f"{column} {text!r} is not a whole number like 4 248 811")
    return int(text.replace(" ", ""))


def _row(line: int, cells: list[str]) -> ArchiveRow:
    who = f"row {cells[_NAME]!r}" if cells else "row"
    if len(cells) != len(HEADER):
        raise GpwFormatError(line, f"{who}: {len(cells)} cells, expected {len(HEADER)}")
    try:
        isin = Isin.parse(cells[_ISIN])
        if cells[_CURRENCY] != CURRENCY:
            raise ValueError(f"currency {cells[_CURRENCY]!r}, expected {CURRENCY}: the store has "
                             f"no currency column")
        o, h, l, c = (_decimal(cells[i], HEADER[i])                         # noqa: E741
                      for i in (_OPEN, _HIGH, _LOW, _CLOSE))
        volume = _whole(cells[_VOLUME], HEADER[_VOLUME])
    except ValueError as e:
        raise GpwFormatError(line, f"{who}: {e}") from None
    return ArchiveRow(line, cells[_NAME], isin, cells[_CURRENCY], o, h, l, c, volume)


def table(page: bytes | str) -> list[ArchiveRow]:
    """Every data row of the page, in page order, rows without trades included; [] for a page
    that says NO_DATA. The first problem rejects the whole page (GpwFormatError)."""
    parser = _Table()
    parser.feed(_decode(page))
    parser.close()
    data = [(line, cells) for line, kind, cells in parser.rows
            if kind == "td" and len(cells) >= DATA_ROW_MIN_CELLS]
    if not data:
        if NO_DATA in " ".join("".join(parser.text).split()):
            return []
        raise GpwFormatError(None, f"no data rows and no {NO_DATA!r}: not an archive page")
    headers = [cells for _, kind, cells in parser.rows if kind == "th" and len(cells) == len(HEADER)]
    if tuple(headers[0] if len(headers) == 1 else ()) != HEADER:
        found = headers[0] if len(headers) == 1 else f"{len(headers)} header rows of {len(HEADER)}"
        raise GpwFormatError(data[0][0], f"column headers are {found!r}, expected {HEADER!r}")
    out: list[ArchiveRow] = []
    seen: dict[Isin, int] = {}
    for line, cells in data:
        row = _row(line, cells)
        if row.isin in seen:
            raise GpwFormatError(line, f"row {row.name!r}: ISIN {row.isin} again (first on line "
                                       f"{seen[row.isin]})")
        seen[row.isin] = line
        out.append(row)
    return out


def parse(page: bytes | str, session: date) -> dict[Isin, StoredQuote]:
    """The page's sessions as store rows keyed by ISIN, in page order; rows with volume 0 left out.
    `session` is the date the caller fetched the page for: the page is not asked for its date.
    The first problem rejects the whole page, so nothing partial is ever returned."""
    out: dict[Isin, StoredQuote] = {}
    for row in table(page):
        if row.volume == 0:
            continue
        try:
            o, h, l, c = (Price(v) for v in (row.open, row.high, row.low, row.close))  # noqa: E741
            quote = DailyQuote(session, o, h, l, c, Volume(row.volume))
        except ValueError as e:
            raise GpwFormatError(row.line, f"row {row.name!r}: {e}") from None
        out[row.isin] = StoredQuote(quote, SOURCE)
    return out
