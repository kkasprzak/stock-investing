"""Value objects shared by every quote source and the CLI."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import ClassVar, Mapping, Protocol

_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_PRICE = re.compile(r"[0-9]+(\.[0-9]+)?")
_VOLUME = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class Isin:
    """An ISIN that passed its format and check digit. Its strict shape is also what makes it safe
    to build a file name from."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _ISIN.fullmatch(self.value):
            raise ValueError(f"ISIN {self.value!r} is not 2 letters, 9 letters/digits and a digit")
        if not _luhn_ok("".join(str(int(ch, 36)) for ch in self.value)):   # A=10 .. Z=35
            raise ValueError(f"ISIN {self.value!r} has a wrong check digit")

    @classmethod
    def parse(cls, text: str) -> Isin:
        return cls(text)

    def __str__(self) -> str:
        return self.value


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass(frozen=True)
class Price:
    """A positive, finite price. Equal by value (133.5 == 133.50); str gives back the exact text it
    was parsed from."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal) or not self.value.is_finite() or self.value <= 0:
            raise ValueError(f"price {self.value!r} is not a positive finite Decimal")

    @classmethod
    def parse(cls, text: str) -> Price:
        """Digits with an optional fraction only: no sign, exponent, inf/nan or whitespace."""
        if not isinstance(text, str) or not _PRICE.fullmatch(text):
            raise ValueError(f"price {text!r} is not a plain decimal number")
        return cls(Decimal(text))

    def __str__(self) -> str:
        return format(self.value, "f")


@dataclass(frozen=True)
class Volume:
    """A whole, non-negative number of shares traded."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 0:
            raise ValueError(f"volume {self.value!r} is not a non-negative int")

    @classmethod
    def parse(cls, text: str) -> Volume:
        if not isinstance(text, str) or not _VOLUME.fullmatch(text):
            raise ValueError(f"volume {text!r} is not a whole number")
        return cls(int(text))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class DailyQuote:
    """The quote of one closed session. A quote that breaks the OHLC rules does not exist. Weekends
    are not its rule: that is exchange-calendar knowledge, checked where files are read and
    imported."""

    session: date
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Volume

    def __post_init__(self) -> None:
        o, h, l, c = self.open.value, self.high.value, self.low.value, self.close.value  # noqa: E741
        if l > min(o, c):
            raise ValueError(f"{self.session}: low {self.low} is above min(open {self.open}, "
                             f"close {self.close})")
        if h < max(o, c):
            raise ValueError(f"{self.session}: high {self.high} is below max(open {self.open}, "
                             f"close {self.close})")


@dataclass(frozen=True)
class Trust:
    """Whether the source vouches for a session it reported: a fact the source states, not one
    derived from the numbers. Untrusted always names its reason; the set of reasons is open."""

    reason: str | None

    TRUSTED: ClassVar[Trust]

    def __post_init__(self) -> None:
        if self.reason is None:
            return
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(f"untrusted reason {self.reason!r} is not a non-blank string")

    @classmethod
    def untrusted(cls, reason: str) -> Trust:
        if reason is None:
            raise ValueError("untrusted needs a reason")
        return cls(reason)

    @property
    def trusted(self) -> bool:
        return self.reason is None


Trust.TRUSTED = Trust(None)


class Status(str, Enum):
    """Status of a derived value. Quality only ever gives GOOD or UNCERTAIN; NO_VALUE is what a
    reading reports when it has no value at all."""

    GOOD = "good"
    UNCERTAIN = "uncertain"
    NO_VALUE = "no_value"


@dataclass(frozen=True)
class Quality:
    """Quality of a derived value: the sessions left out of it because they were not trusted.
    Sorted and unique, so two qualities naming the same sessions are equal."""

    excluded: tuple[date, ...]

    GOOD: ClassVar[Quality]

    def __post_init__(self) -> None:
        object.__setattr__(self, "excluded", tuple(sorted(set(self.excluded))))

    @property
    def status(self) -> Status:
        return Status.UNCERTAIN if self.excluded else Status.GOOD

    @classmethod
    def combine(cls, *qualities: Quality) -> Quality:
        """Quality of a value derived from values of these qualities: every session any left out."""
        return cls(tuple(d for q in qualities for d in q.excluded))


Quality.GOOD = Quality(())


class Candle(Protocol):
    """A candle as a reading over a series sees it, daily or rolled up: its day, its columns,
    whether it may be read, and what it leaves out of the quality of a value read over it."""

    @property
    def day(self) -> date: ...
    @property
    def open(self) -> Price | None: ...
    @property
    def high(self) -> Price | None: ...
    @property
    def low(self) -> Price | None: ...
    @property
    def close(self) -> Price | None: ...
    @property
    def volume(self) -> Volume | None: ...
    @property
    def complete(self) -> bool: ...
    @property
    def trusted(self) -> bool: ...
    @property
    def quality(self) -> Quality: ...


@dataclass(frozen=True)
class DailyBar:
    """What a source said about one session. Not a quote: it holds no OHLC rules, since a source
    may report gaps or numbers that do not add up. Whether to rely on it is trust."""

    session: date
    open: Price | None
    high: Price | None
    low: Price | None
    close: Price | None
    volume: Volume | None
    complete: bool
    source: str
    trust: Trust

    @property
    def day(self) -> date:
        return self.session

    @property
    def trusted(self) -> bool:
        return self.trust.trusted

    @property
    def quality(self) -> Quality:
        """What this bar leaves out of a value read over it, not a status of its own (a daily bar
        is reported by its trust): an untrusted session that ended names itself. A forming one is
        neither a value nor a left-out session, so it names nothing."""
        return Quality((self.session,)) if self.complete and not self.trusted else Quality.GOOD


@dataclass(frozen=True)
class PeriodBar:
    """A W1/MN candle rolled up from daily bars: a derived value, so it carries quality. While the
    period is forming, that quality names only the period's sessions that already ended."""

    period_start: date
    open: Price | None
    high: Price | None
    low: Price | None
    close: Price | None
    volume: Volume | None
    complete: bool
    quality: Quality

    @property
    def day(self) -> date:
        return self.period_start

    @property
    def trusted(self) -> bool:
        """Always: no source vouches for a period, it is judged by its quality instead."""
        return True

    @property
    def status(self) -> Status:
        return Status.NO_VALUE if self.close is None else self.quality.status


@dataclass(frozen=True)
class Instrument:
    """One tradable instrument, named by its ISIN (ADR 0003). Not hashable (holds a Mapping); nobody
    keys by it."""

    isin: Isin
    symbols: Mapping[str, str]  # {"xtb": "PKN.PL", "yahoo": "PKN.WA", ...}; empty when unmapped

    @classmethod
    def unmapped(cls, isin: Isin) -> Instrument:
        """An instrument the symbol map does not know: its ISIN, no per-source symbols."""
        return cls(isin=isin, symbols={})


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


@dataclass(frozen=True)
class PeriodInterval:
    """An interval daily bars roll up into: weekly or monthly. Daily is not one, so a rollup can
    never be asked for it."""

    interval: Interval

    WEEKLY: ClassVar[PeriodInterval]
    MONTHLY: ClassVar[PeriodInterval]

    def __post_init__(self) -> None:
        if not isinstance(self.interval, Interval) or self.interval is Interval.DAILY:
            raise ValueError(f"{self.interval!r} is not a weekly or monthly Interval")

    def period(self, session: date) -> DateRange:
        """The period a session falls in: Monday..Friday, or the 1st..month-end. Its start labels
        the period's bar; its end is the last session that can close it."""
        if self.interval is Interval.WEEKLY:
            monday = session - timedelta(days=session.weekday())
            return DateRange(monday, monday + timedelta(days=4))
        nxt = (date(session.year + 1, 1, 1) if session.month == 12
               else date(session.year, session.month + 1, 1))
        return DateRange(date(session.year, session.month, 1), nxt - timedelta(days=1))


PeriodInterval.WEEKLY = PeriodInterval(Interval.WEEKLY)
PeriodInterval.MONTHLY = PeriodInterval(Interval.MONTHLY)


def _at_least_one(value: object, what: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{what} {value!r} is not a whole number of at least 1")


@dataclass(frozen=True)
class AtrPeriod:
    """How many candles Wilder's ATR averages over (its n)."""

    value: int

    def __post_init__(self) -> None:
        _at_least_one(self.value, "ATR period")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class SessionsEachSide:
    """How many sessions on each side of a swing low must have traded higher to confirm it."""

    value: int

    def __post_init__(self) -> None:
        _at_least_one(self.value, "sessions each side")

    def __str__(self) -> str:
        return str(self.value)
