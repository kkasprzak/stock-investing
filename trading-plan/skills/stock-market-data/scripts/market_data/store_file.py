"""The candle store's file: one CSV per ISIN, the contract between the importer and the adapter.

<ISIN>.csv, header HEADER, LF line endings, UTF-8 without a BOM; rows ascending by a unique date,
working days only, closed sessions only. date is ISO, prices are str(Price), volume is
str(Volume), source is the provider of the row (e.g. "stooq").
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from market_data.model import DailyQuote, Price, Volume

HEADER = ("date", "open", "high", "low", "close", "volume", "source")
LINE_TERMINATOR = "\n"
ENCODING = "utf-8"          # not utf-8-sig: the file carries no BOM


@dataclass(frozen=True)
class StoredQuote:
    """One row of the file. source is provenance of the stored row, not part of the quote; the
    set of providers is open, so it stays a str."""

    quote: DailyQuote
    source: str


class StoreFileError(Exception):
    """A store file that breaks the schema, or cannot be read at all (line is None then). The whole
    file is refused: a half-read file would pass off its missing rows as sessions it never had."""

    def __init__(self, path: Path, line: int | None, why: str) -> None:
        self.path = path
        self.line = line
        self.why = why
        super().__init__(f"{path}:{line}: {why}" if line else f"{path}: {why}")


_BOM = b"\xef\xbb\xbf"
_WEEKEND = {5: "Saturday", 6: "Sunday"}


def read(path: Path) -> list[StoredQuote]:
    """The file's rows, ascending by session. Any breach of the schema raises StoreFileError with
    the line; so do an unreadable file and one that is not UTF-8."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise StoreFileError(path, None, f"cannot read: {e.strerror or e}") from e
    if raw.startswith(_BOM):
        raise StoreFileError(path, 1, "starts with a BOM; the store is UTF-8 without one")
    try:
        text = raw.decode(ENCODING)
    except UnicodeDecodeError as e:
        raise StoreFileError(path, raw.count(b"\n", 0, e.start) + 1, f"not UTF-8 ({e.reason})") from e
    if "\r" in text:
        raise StoreFileError(path, text.count("\n", 0, text.index("\r")) + 1,
                             "CRLF line ending; the store uses LF")
    rows = csv.reader(io.StringIO(text, newline=""))
    header = next(rows, None)
    if header is None or tuple(header) != HEADER:
        raise StoreFileError(path, 1, f"header is {header!r}, expected {','.join(HEADER)}")
    out: list[StoredQuote] = []
    for row in rows:
        line = rows.line_num
        if len(row) != len(HEADER):
            raise StoreFileError(path, line, f"{len(row)} columns, expected {len(HEADER)}")
        day, o, h, l, c, v, source = row  # noqa: E741
        try:
            session = date.fromisoformat(day)
            if session.isoformat() != day:
                raise ValueError(f"date {day!r} is not YYYY-MM-DD")
            quote = DailyQuote(session, Price.parse(o), Price.parse(h), Price.parse(l),
                               Price.parse(c), Volume.parse(v))
        except ValueError as e:
            raise StoreFileError(path, line, str(e)) from e
        if session.weekday() in _WEEKEND:
            raise StoreFileError(path, line, f"{session} is a {_WEEKEND[session.weekday()]}; a "
                                             f"daily file has no weekend sessions")
        if out and session == out[-1].quote.session:
            raise StoreFileError(path, line, f"duplicate date {session}")
        if out and session < out[-1].quote.session:
            raise StoreFileError(path, line, f"date {session} after {out[-1].quote.session}; dates "
                                             f"must be ascending")
        out.append(StoredQuote(quote, source))
    return out


def to_bar(stored: StoredQuote) -> dict:
    """The row as a port bar, numbers as float/int like Yahoo's. The bar's source is the adapter
    that served it ("store"), not the provider the row came from."""
    q = stored.quote
    return {"date": q.session.isoformat(), "o": float(q.open.value), "h": float(q.high.value),
            "l": float(q.low.value), "c": float(q.close.value), "v": q.volume.value,
            "complete": True, "source": "store"}
