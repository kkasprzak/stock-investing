"""The candle store's file: one CSV per ISIN, the contract between the importer and the adapter.

<ISIN>.csv, header HEADER, LF line endings, UTF-8 without a BOM; rows ascending by a unique date,
working days only, closed sessions only. date is ISO, prices are str(Price), volume is
str(Volume), source is the provider of the row (e.g. "stooq").
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import stat
import tempfile
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


NEW_FILE_MODE = 0o644       # rw-r--r--, for a file write() creates; an existing file keeps its mode


@dataclass(frozen=True)
class MergeResult:
    """What an import does to the file. changed = a session already stored whose quote differs by
    value (the source of the row is provenance, not part of the comparison)."""

    rows: tuple[StoredQuote, ...]
    added: int
    unchanged: int
    changed: int
    changed_dates: tuple[date, ...]


def _by_session(rows, side: str) -> dict[date, StoredQuote]:
    out = {}
    for r in rows:
        if r.quote.session in out:
            raise ValueError(f"{side} holds session {r.quote.session} twice")
        out[r.quote.session] = r
    return out


def merge(existing, incoming) -> MergeResult:
    """The stored rows with the incoming ones laid over them, by session; incoming wins a
    difference. An equal quote keeps the stored row, so a re-import does not churn the file's text
    ("133.50" stays even when the export says "133.5")."""
    rows = _by_session(existing, "existing")
    added = unchanged = 0
    changed_dates = []
    for session, new in _by_session(incoming, "incoming").items():
        old = rows.get(session)
        if old is None:
            added += 1
        elif old.quote == new.quote:
            unchanged += 1
            continue
        else:
            changed_dates.append(session)
        rows[session] = new
    return MergeResult(tuple(rows[s] for s in sorted(rows)), added, unchanged, len(changed_dates),
                       tuple(sorted(changed_dates)))


def write(path: Path, rows) -> None:
    """The whole file, sorted by session, replaced atomically (a temp file beside it, then
    os.replace): a reader never sees half a file and a failed write leaves the old one. A duplicate
    session or one on a weekend is the caller's bug: the row types already guarantee the rest."""
    path = Path(path)
    ordered = sorted(rows, key=lambda r: r.quote.session)
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.quote.session == prev.quote.session:
            raise ValueError(f"session {cur.quote.session} appears twice")
    for r in ordered:
        if r.quote.session.weekday() >= 5:
            raise ValueError(f"session {r.quote.session} falls on a weekend")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=ENCODING, newline="") as f:
            out = csv.writer(f, lineterminator=LINE_TERMINATOR)
            out.writerow(HEADER)
            for r in ordered:
                q = r.quote
                out.writerow((q.session.isoformat(), q.open, q.high, q.low, q.close, q.volume,
                              r.source))
        # mkstemp makes the temp file 0600; the store file is an ordinary file in the repo.
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode) if path.exists() else NEW_FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
