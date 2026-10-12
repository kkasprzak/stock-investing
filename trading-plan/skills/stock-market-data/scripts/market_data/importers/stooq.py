"""A Stooq daily CSV export read into store rows.

Stooq exports come with a Polish or an English header, CRLF or LF line endings. Exported with
"skip splits + dividends", prices and volume from the dividend de-adjustment carry float noise of
about 1e-5 of the value (237.0994785 for 237.1, 17250.135879362 for 17250, volume 2558.99269 for
2559); snap() and snap_volume() take it off before the row is validated. A value further off than
that is not noise around a short one, and rejects the file rather than being cut.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from market_data.model import DailyQuote, Price, Volume
from market_data.store_file import StoredQuote

SOURCE = "stooq"
HEADERS = (
    ("Data", "Otwarcie", "Najwyzszy", "Najnizszy", "Zamkniecie", "Wolumen"),
    ("Date", "Open", "High", "Low", "Close", "Volume"),
)
SNAP_MAX_PLACES = 4                     # a price with this many places or fewer is taken as written
SNAP_RADIUS_REL = Decimal("1e-5")       # noise never moves a value by more than this fraction of it
NOISE_HINT = ('export with "pomijaj splity + dywidendy" (skip splits and dividends); Stooq history '
              'before ~2022 carries larger de-adjustment noise: export a shorter range')

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


def shortest_within_radius(x: Decimal, max_places: int = SNAP_MAX_PLACES) -> Decimal | None:
    """The value with the fewest places (0..max_places) within 1e-5 * x of `x`, or None when there
    is none. The radius is what de-adjustment noise is allowed to be; outside it a long value is
    not noise around a short one."""
    radius = SNAP_RADIUS_REL * x
    for places in range(max_places + 1):
        y = x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if abs(x - y) <= radius:
            return y
    return None


def snap(text: str) -> str:
    """A price as Stooq wrote it, without the de-adjustment noise. Only plain decimals longer than
    four places are touched; anything else passes through for Price.parse to judge. ValueError
    when no value of four places or fewer is within the radius."""
    if not _LONG_DECIMAL.fullmatch(text):
        return text
    y = shortest_within_radius(Decimal(text))
    if y is None:
        raise ValueError(f"price {text} is off every number of {SNAP_MAX_PLACES} places or fewer "
                         f"by more than 1e-5 of it: {NOISE_HINT}")
    return format(y, "f")


def snap_volume(text: str) -> str:
    """A volume as Stooq wrote it, without the de-adjustment noise: a whole number as written, a
    fraction within the radius as the nearest whole number. ValueError otherwise."""
    if _INTEGER.fullmatch(text):
        return text
    if not _FRACTION.fullmatch(text):
        raise ValueError(f"volume {text!r} is not a whole number of shares")
    y = shortest_within_radius(Decimal(text), max_places=0)
    if y is None:
        raise ValueError(f"volume {text} is off the nearest whole number by more than 1e-5 of it: "
                         f"{NOISE_HINT}")
    return format(y, "f")


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise StooqFormatError(raw[:e.start].count(b"\n") + 1, "not UTF-8 text") from None


def _records(path: Path):
    """(line, session, [open, high, low, close] snapped, volume snapped) per data row, after every
    check that needs no price type: header, columns, ISO date, weekend, order, noise radius."""
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
            snapped = [snap(p) for p in prices], snap_volume(volume)
        except ValueError as e:
            raise StooqFormatError(line, str(e)) from None
        previous = session
        yield line, session, *snapped


def parse(path: Path) -> list[StoredQuote]:
    """Every row of a Stooq daily export as a store row; the first problem rejects the whole file.
    Prices are snapped first and validated after (Price, then the OHLC rules of DailyQuote): the
    noise can put a low a hair above the close, and the snapped value is the one that is stored."""
    out = []
    for line, session, prices, volume in _records(path):
        try:
            o, h, l, c = (Price.parse(p) for p in prices)  # noqa: E741
            quote = DailyQuote(session, o, h, l, c, Volume.parse(volume))
        except ValueError as e:
            raise StooqFormatError(line, str(e)) from None
        out.append(StoredQuote(quote, SOURCE))
    return out
