"""Pure functions over bar series: weekly/monthly aggregation, Wilder ATR, swing lows, last close.

Bars are DailyBar (from the port) or PeriodBar (from aggregate), newest last, read through the
Candle they both are; each function returns its reading as a type, which the CLI turns into JSON.
Arithmetic runs on floats, as it always has, so the numbers do not move. Nothing here fetches or
knows a vendor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from market_data.model import (AtrPeriod, Candle, DailyBar, DateRange, Interval, PeriodBar,
                               PeriodInterval, Price, Quality, SessionsEachSide, Volume)

ATR_DEFAULT_N = AtrPeriod(14)                   # Wilder's default lookback
ATR_WARMUP = 5                                  # x n candles of run-up before ATR is settled
SWING_SESSIONS_DEFAULT = SessionsEachSide(2)    # sessions each side that must have a higher low


@dataclass(frozen=True)
class AtrReading:
    n: AtrPeriod
    method: str
    value: float                # a distance, not a price: zero is a legal ATR
    bars_used: int
    as_of: date                 # the newest candle it read
    interval: Interval | None   # when the caller named one
    quality: Quality

    @property
    def short_history(self) -> bool:
        """Fewer true ranges (one per candle after the first) than the run-up ATR needs to settle."""
        return self.bars_used - 1 < ATR_WARMUP * self.n.value


@dataclass(frozen=True)
class SwingLow:
    session: date               # on W1/MN, the period's first day
    low_price: Price
    higher_than_previous_row_low: bool | None
    sessions_after_in_window: int
    lowest_low_in_those_sessions: Price

    @property
    def undercut_by_later_session(self) -> bool:
        """Price has since traded below the low; strict, so an exact retest is not an undercut."""
        return self.lowest_low_in_those_sessions.value < self.low_price.value


@dataclass(frozen=True)
class SwingLows:
    """`detectable_through` is the session `each_side` sessions before the window's last one: kept,
    not derived, because which calendar date that is depends on the sessions in the window, not on
    its two ends. What can be checked here is that it fits the window and the confirmation."""

    each_side: SessionsEachSide
    window: DateRange           # first and last session read
    window_sessions: int
    detectable_through: date | None
    detected: tuple[SwingLow, ...]
    interval: Interval | None
    quality: Quality

    def __post_init__(self) -> None:
        confirmable = self.window_sessions > self.each_side.value
        through = self.detectable_through
        if not confirmable and through is not None:
            raise ValueError(f"{self.window_sessions} sessions cannot confirm a low with "
                             f"{self.each_side} each side, yet detectable_through is {through}")
        if confirmable and (through is None or not self.window.start <= through < self.window.end):
            raise ValueError(f"detectable_through {through} is not a session inside "
                             f"{self.window.start}..{self.window.end} before its last")


@dataclass(frozen=True)
class LastClosed:
    session: date               # on W1/MN, the period's first day
    close: Price
    quality: Quality


def _f(p: Price) -> float:
    return float(p.value)


def _usable(bars: Sequence[Candle], *fields: str) -> list[int]:
    """Indices of the candles a reading may use: closed, trusted, and holding the fields that
    reading needs (each reading names its own, so a gap in one column costs only the readings that
    read it)."""
    return [i for i, b in enumerate(bars)
            if b.complete and b.trusted and all(getattr(b, f) is not None for f in fields)]


def _window_quality(bars: Sequence[Candle], first: int) -> Quality:
    """Quality of a reading whose window starts at bars[first]: what every candle from there to the
    end of the series leaves out, so a gap inside the window and the sessions after the reading's
    own date are both named. A forming W1/MN candle is not a reading's value, but the closed
    sessions of its period ended after the reading's date, so they are named too (aggregate already
    leaves the forming day out)."""
    return Quality.combine(*(b.quality for b in bars[first:]))


def calendar_days(interval, bars):
    """Calendar days of daily history that `bars` candles of `interval` need (~1.5 per trading day;
    W1/MN are aggregated from daily)."""
    return math.ceil(bars * Interval(interval).calendar_factor)


def _require(value: object, cls: type, what: str) -> None:
    """Refuses an argument of the wrong type where nothing else would notice: a plain int or the
    other count for a count (the two counts have two types so they cannot be swapped), a bare
    Interval for a rollup."""
    if not isinstance(value, cls):
        raise TypeError(f"{what} must be {cls.__name__}, not {type(value).__name__}")


def aggregate(daily: Sequence[DailyBar], interval: PeriodInterval,
              today: date) -> list[PeriodBar]:
    """Roll daily bars up into weekly/monthly candles, newest last. o = first day's open, h/l = period
    extremes, c = last day's close, v = summed volume, each column over the trusted days that have
    it. A period is complete iff its last business/calendar day is before today, or that day has been
    reached and its own daily bar is already closed — so a week reads complete on Friday evening, not
    only on Saturday.

    Grouping and completeness read every bar: a session that ended is a session that ended, trusted
    or not (ADR 0002), so a placeholder Friday still closes its week and a period with no trusted
    session stays in the series, with no values. Its quality names the closed sessions it left out;
    an untrusted forming bar is neither a value nor a left-out session of the period in progress."""
    _require(interval, PeriodInterval, "aggregate's interval")
    newest = daily[-1].session if daily else None
    order, groups = [], {}
    for b in daily:
        period = interval.period(b.session)
        label, end = period.start, period.end
        g = groups.get(label)
        if g is None:
            g = groups[label] = (end, [])
            order.append(label)
        g[1].append(b)

    out = []
    for label in order:
        end, bars = groups[label]
        trusted = [b for b in bars if b.trust.trusted]
        opens = [b.open for b in trusted if b.open is not None]
        highs = [b.high for b in trusted if b.high is not None]
        lows = [b.low for b in trusted if b.low is not None]
        closes = [b.close for b in trusted if b.close is not None]
        vols = [b.volume.value for b in trusted if b.volume is not None]
        out.append(PeriodBar(
            period_start=label,
            open=opens[0] if opens else None,
            high=max(highs, key=lambda p: p.value) if highs else None,
            low=min(lows, key=lambda p: p.value) if lows else None,
            close=closes[-1] if closes else None,
            volume=Volume(sum(vols)) if vols else None,
            complete=end < today or (newest is not None and end <= newest and bars[-1].complete),
            quality=Quality.combine(*(b.quality for b in bars)),
        ))
    return out


def series_window(atr_n: AtrPeriod | None = None) -> int:
    """The fixed lookback every derived block reads, in candles. One definition on purpose: ATR and
    the swing lows must describe the same stretch of history, or a stop distance in ATR multiples
    would be measured against structure the ATR never saw."""
    if atr_n is None:
        atr_n = ATR_DEFAULT_N
    _require(atr_n, AtrPeriod, "the ATR period")
    return atr_n.value * ATR_WARMUP + 1


def bars_needed(bars: int, atr_n: AtrPeriod | None = None,
                swings: SessionsEachSide | None = None) -> int:
    """Candles the fetch must cover: what the caller wants to see, or the derived blocks' window if
    that is longer. ATR is recursive, so its value depends on how much history it was fed — deriving
    it from the returned slice would make the same instrument read differently for a 6-bar morning
    check and a 70-bar sizing run. The window is therefore fixed here, independent of `bars`;
    atr_wilder() and swing_lows() then trim to that same window from the other side, so a wider fetch
    cannot shift either result."""
    if swings is not None:
        _require(swings, SessionsEachSide, "the sessions each side")
    if atr_n is None and swings is None:
        return bars
    return max(bars, series_window(atr_n))


def atr_wilder(bars: Sequence[Candle], n: AtrPeriod = ATR_DEFAULT_N,
               interval: Interval | None = None) -> AtrReading | None:
    """Wilder's ATR(n) over a series (newest last) — or None when there are fewer than n+1 usable
    candles. Method is J. Welles Wilder Jr., New Concepts in Technical Trading Systems (1978):
    TR = max(H-L, |H-prevC|, |prevC-L|), seed = mean of the first n TRs, then
    ATR = (prevATR x (n-1) + TR) / n.

    Only **complete**, trusted candles with high, low and close count: a forming bar's H/L keep
    moving, so it distorts both the TR and everything measured against it, and an untrusted session's
    numbers are not a range anyone traded. The window is the last usable candles, so an untrusted
    tail gives the ATR as of the last trusted candle (`as_of`), and its quality names what was left
    out. `short_history` marks a value computed on less than the ATR_WARMUP run-up — still reported
    (never a silent [NO DATA]), but flagged as not yet settled."""
    idx = _usable(bars, "high", "low", "close")[-series_window(n):]   # fixed window: a longer fetch
    k = n.value                                                       # must not shift the value
    if len(idx) < k + 1:
        return None
    usable = [bars[i] for i in idx]
    h = [_f(b.high) for b in usable]
    lo = [_f(b.low) for b in usable]
    c = [_f(b.close) for b in usable]
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(c[i - 1] - lo[i]))
           for i in range(1, len(usable))]
    atr = sum(trs[:k]) / k                                  # Wilder's seed
    for tr in trs[k:]:
        atr = (atr * (k - 1) + tr) / k
    return AtrReading(n=n, method="wilder", value=round(atr, 4), bars_used=len(usable),
                      as_of=usable[-1].day, interval=interval,
                      quality=_window_quality(bars, idx[0]))


def swing_lows(bars: Sequence[Candle], each_side: SessionsEachSide = SWING_SESSIONS_DEFAULT,
               interval: Interval | None = None,
               atr_n: AtrPeriod | None = None) -> SwingLows | None:
    """Confirmed swing lows over a series (newest last) — or None when the series carries no usable
    candle. A swing low is a session whose low the `each_side` sessions before **and** after it did
    not reach, so it cannot be read until that many sessions have closed after it
    (`detectable_through` marks that edge).

    Every confirmed low is reported, including ones lower than the previous — this layer describes the
    series, it does not pick the one a trailing stop may use. The two derived fields carry what that
    choice needs: `higher_than_previous_row_low` compares with the preceding row, and
    `undercut_by_later_session` says whether price has since traded below the low (strict `<`, so an
    exact retest is not an undercut). Only **complete**, trusted candles with a low count: a forming
    bar's low keeps moving, so it can neither be a swing low nor undercut one, and an untrusted
    session never traded, so it is neither a candidate nor a neighbour that confirms one."""
    _require(each_side, SessionsEachSide, "the sessions each side")
    idx = _usable(bars, "low")[-series_window(atr_n):]   # the same window ATR reads — see series_window()
    if not idx:
        return None
    usable = [bars[i] for i in idx]
    lows = [_f(b.low) for b in usable]
    k = each_side.value
    detected, previous_low = [], None
    for i in range(k, len(usable) - k):
        low = lows[i]
        if not all(lows[j] > low for j in range(i - k, i + k + 1) if j != i):
            continue
        lowest_after = min(range(i + 1, len(usable)), key=lows.__getitem__)
        detected.append(SwingLow(
            session=usable[i].day,
            low_price=usable[i].low,
            higher_than_previous_row_low=None if previous_low is None else low > previous_low,
            sessions_after_in_window=len(usable) - i - 1,
            lowest_low_in_those_sessions=usable[lowest_after].low,
        ))
        previous_low = low
    return SwingLows(
        each_side=each_side,
        window=DateRange(usable[0].day, usable[-1].day),
        window_sessions=len(usable),
        detectable_through=usable[-(k + 1)].day if len(usable) > k else None,
        detected=tuple(detected), interval=interval, quality=_window_quality(bars, idx[0]))


def last_closed(bars: Sequence[Candle]) -> LastClosed | None:
    """Most recent complete, trusted bar with a close — the number the checks want. None if none.
    Its quality names the closed sessions after it that were left out (and, for a W1/MN candle, its
    own). Read over the whole series the caller has, not the slice it shows: a short slice would
    hide the close."""
    idx = _usable(bars, "close")
    if not idx:
        return None
    b = bars[idx[-1]]
    return LastClosed(session=b.day, close=b.close, quality=_window_quality(bars, idx[-1]))
