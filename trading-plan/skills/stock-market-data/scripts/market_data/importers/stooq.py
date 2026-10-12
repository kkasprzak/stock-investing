"""A Stooq daily CSV export read into store rows.

Stooq exports come with a Polish or an English header, CRLF or LF line endings. Exported with
"skip splits + dividends", prices from the dividend de-adjustment carry float noise in the last
places (237.0994785 for 237.1); snap() takes it off before the prices are validated.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SOURCE = "stooq"
HEADERS = (
    ("Data", "Otwarcie", "Najwyzszy", "Najnizszy", "Zamkniecie", "Wolumen"),
    ("Date", "Open", "High", "Low", "Close", "Volume"),
)
SNAP_MAX_PLACES = 4                     # a value with this many places or fewer is taken as written
SNAP_RADIUS_CAP = Decimal("0.001")      # a tenth of a grosz: noise never moves a price by more
SNAP_RADIUS_REL = Decimal("1e-5")       # ...nor by more than this fraction of it

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LONG_DECIMAL = re.compile(r"\d+\.\d{%d,}" % (SNAP_MAX_PLACES + 1))
_INTEGER = re.compile(r"\d+")
_FRACTION = re.compile(r"\d+\.\d+")


class StooqFormatError(Exception):
    """The export is not one this importer accepts. `line` is 1-based and counts the header."""

    def __init__(self, line: int, why: str) -> None:
        super().__init__(f"line {line}: {why}")
        self.line = line
        self.why = why


def shortest_within_radius(x: Decimal) -> Decimal | None:
    """The value with the fewest places (0..4) within min(0.001, 1e-5 * x) of `x`, or None when
    there is none. The radius is what de-adjustment noise is allowed to be; outside it a long value
    is not noise around a short one."""
    radius = min(SNAP_RADIUS_CAP, SNAP_RADIUS_REL * x)
    for places in range(SNAP_MAX_PLACES + 1):
        y = x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if abs(x - y) <= radius:
            return y
    return None


def snap(text: str) -> str:
    """A price as Stooq wrote it, without the de-adjustment noise. Only plain decimals longer than
    four places are touched; anything else passes through for Price.parse to judge."""
    if not _LONG_DECIMAL.fullmatch(text):
        return text
    x = Decimal(text)
    y = shortest_within_radius(x)
    if y is None:
        y = x.quantize(Decimal(1).scaleb(-SNAP_MAX_PLACES), rounding=ROUND_HALF_UP)
    return format(y, "f")


def _check_volume(text: str) -> None:
    if _INTEGER.fullmatch(text):
        return
    if _FRACTION.fullmatch(text):
        raise ValueError(f"fractional volume {text}: Stooq's history before 2022 carries "
                         f"de-adjusted volume; export from 2022 on")
    raise ValueError(f"volume {text!r} is not a whole number of shares")


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise StooqFormatError(raw[:e.start].count(b"\n") + 1, "not UTF-8 text") from None


def _records(path: Path):
    """(line, session, [open, high, low, close] snapped, volume text) per data row, after every
    check that needs no price type: header, columns, ISO date, weekend, order, whole volume."""
    rows = csv.reader(io.StringIO(_decode(Path(path).read_bytes()), newline=""))
    header = next(rows, None)
    if header is None or tuple(header) not in HEADERS:
        raise StooqFormatError(1, f"unknown header {header!r}; expected {','.join(HEADERS[0])} "
                                  f"or {','.join(HEADERS[1])}")
    previous = None
    for line, row in enumerate(rows, start=2):
        if len(row) != 6:
            raise StooqFormatError(line, f"expected 6 columns, got {len(row)}")
        text, *prices, volume = row
        if not _ISO_DATE.fullmatch(text):
            raise StooqFormatError(line, f"date {text!r} is not YYYY-MM-DD")
        try:
            session = date.fromisoformat(text)
        except ValueError as e:
            raise StooqFormatError(line, f"date {text!r}: {e}") from None
        if session.weekday() >= 5:
            raise StooqFormatError(line, f"session {session} falls on a weekend; a daily export "
                                         f"has none (weekly or monthly export?)")
        if previous is not None and session <= previous:
            raise StooqFormatError(line, f"session {session} "
                                         f"{'repeats' if session == previous else 'comes after'} "
                                         f"{previous}; dates must rise")
        try:
            _check_volume(volume)
        except ValueError as e:
            raise StooqFormatError(line, str(e)) from None
        previous = session
        yield line, session, [snap(p) for p in prices], volume


def parse(path: Path) -> list:
    """Every row of a Stooq daily export; the first problem rejects the whole file."""
    return list(_records(path))
