"""Value objects shared by every quote source and the CLI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Mapping


@dataclass(frozen=True)
class Instrument:
    """One tradable instrument as the caller named it. Not hashable (holds a Mapping); nobody keys
    by it."""

    key: str                    # what the caller passed: broker ticker or ISIN
    isin: str | None            # None when the key is not in symbols.json
    symbols: Mapping[str, str]  # {"xtb": "PKN.PL", "yahoo": "PKN.WA", ...}; empty when unmapped

    @classmethod
    def unmapped(cls, key: str) -> Instrument:
        """An instrument the symbol map does not know: no ISIN, no per-source symbols."""
        return cls(key=key, isin=None, symbols={})


@dataclass(frozen=True)
class DateRange:
    """Calendar dates, both ends inclusive."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"DateRange start {self.start} is after end {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days


class Interval(str, Enum):
    """Candle interval. A str Enum, so Interval.WEEKLY == "w"; callers holding a bare string coerce
    with Interval(value) before reading .label or .calendar_factor."""

    DAILY = "d"
    WEEKLY = "w"
    MONTHLY = "m"

    @property
    def label(self) -> str:
        return _LABEL[self]

    @property
    def calendar_factor(self) -> float:
        """Calendar days of daily history one candle needs (daily: ~1.5 per trading day). W1/MN are
        aggregated from the daily series, so every interval maps onto daily calendar days."""
        return _CALENDAR_FACTOR[self]


_LABEL = {Interval.DAILY: "daily", Interval.WEEKLY: "weekly", Interval.MONTHLY: "monthly"}
_CALENDAR_FACTOR = {Interval.DAILY: 1.5, Interval.WEEKLY: 7, Interval.MONTHLY: 30}
