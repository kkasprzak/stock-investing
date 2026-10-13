"""Pure functions over bar series: weekly/monthly aggregation, Wilder ATR, swing lows, last close.

Bars are DailyBar (from the port) or PeriodBar (from aggregate), newest last; each function returns
its reading as a type, which the CLI turns into JSON. Arithmetic runs on floats, as it always has, so
the numbers do not move. Nothing here fetches or knows a vendor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence, Union

from market_data.model import DailyBar, Interval, PeriodBar, Price, Quality, Volume

ATR_DEFAULT_N = 14                              # Wilder's default lookback
ATR_WARMUP = 5                                  # x n candles of run-up before ATR is settled
SWING_SESSIONS_DEFAULT = 2                      # sessions each side that must have a higher low

Bar = Union[DailyBar, PeriodBar]


@dataclass(frozen=True)
class AtrReading:
    n: int
    method: str
    value: float
    bars_used: int
    as_of: date                 # the newest candle it read
    short_history: bool
    interval: str | None        # the interval label, when the caller named one
    quality: Quality


@dataclass(frozen=True)
class SwingLow:
    session: date               # on W1/MN, the period's first day
    low_price: float
    higher_than_previous_row_low: bool | None
    sessions_after_in_window: int
    lowest_low_in_those_sessions: float
    undercut_by_later_session: bool


@dataclass(frozen=True)
class SwingLows:
    each_side: int
    window_first_session: date
    window_last_session: date
    window_sessions: int
    detectable_through: date | None
    detected: tuple[SwingLow, ...]
    interval: str | None
    quality: Quality


@dataclass(frozen=True)
class LastClosed:
    session: date               # on W1/MN, the period's first day
    close: float
    quality: Quality


def _day(b: Bar) -> date:
    """The date a bar is keyed by: its session, or its period's first day."""
    return b.session if isinstance(b, DailyBar) else b.period_start


def _f(p: Price) -> float:
    return float(p.value)


def _trusted(b: Bar) -> bool:
    """A period bar is not vouched for by a source but judged by its quality, read separately."""
    return not isinstance(b, DailyBar) or b.trust.trusted


def _quality(b: Bar) -> Quality:
    """What a bar leaves out of a value read over it: an untrusted session itself, or whatever a
    period bar already left out."""
    if isinstance(b, PeriodBar):
        return b.quality
    return Quality.GOOD if b.trust.trusted else Quality((b.session,))


def _usable(bars: Sequence[Bar], *fields: str) -> list[int]:
    """Indices of the candles a reading may use: closed, trusted, and holding the fields that
    reading needs (each reading names its own, so a gap in one column costs only the readings that
    read it)."""
    return [i for i, b in enumerate(bars)
            if b.complete and _trusted(b) and all(getattr(b, f) is not None for f in fields)]


def _window_quality(bars: Sequence[Bar], first: int) -> Quality:
    """Quality of a reading whose window starts at bars[first]: every closed candle from there to the
    end of the series, so a gap inside the window and the sessions after the reading's own date are
    both named. A forming candle is left out of a reading anyway, not because it is untrusted."""
    return Quality.combine(*(_quality(b) for b in bars[first:] if b.complete))


def calendar_days(interval, bars):
    """Calendar days of daily history that `bars` candles of `interval` need (~1.5 per trading day;
    W1/MN are aggregated from daily)."""
    return math.ceil(bars * Interval(interval).calendar_factor)


def _period(d: date, interval) -> tuple[date, date]:
    """(label, period_end) for a daily session grouped weekly/monthly.
    label = period start (Monday / 1st); period_end = last business/calendar day (Friday / month-end)."""
    interval = Interval(interval)
    if interval is Interval.WEEKLY:
        monday = d - timedelta(days=d.weekday())
        return monday, monday + timedelta(days=4)                      # Mon .. Fri
    nxt = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return date(d.year, d.month, 1), nxt - timedelta(days=1)           # 1st .. month-end


def aggregate(daily: Sequence[DailyBar], interval, today: date) -> list[PeriodBar]:
    """Roll daily bars up into weekly/monthly candles, newest last. o = first day's open, h/l = period
    extremes, c = last day's close, v = summed volume, each column over the trusted days that have
    it. A period is complete iff its last business/calendar day is before today, or that day has been
    reached and its own daily bar is already closed — so a week reads complete on Friday evening, not
    only on Saturday.

    Grouping and completeness read every bar: a session that ended is a session that ended, trusted
    or not (ADR 0002), so a placeholder Friday still closes its week and a period with no trusted
    session stays in the series, with no values. Its quality names the closed sessions it left out;
    an untrusted forming bar is neither a value nor a left-out session of the period in progress."""
    interval = Interval(interval)
    newest = daily[-1].session if daily else None
    order, groups = [], {}
    for b in daily:
        label, end = _period(b.session, interval)
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
            quality=Quality.combine(*(_quality(b) for b in bars if b.complete)),
        ))
    return out


def series_window(atr_n=None):
    """The fixed lookback every derived block reads, in candles. One definition on purpose: ATR and
    the swing lows must describe the same stretch of history, or a stop distance in ATR multiples
    would be measured against structure the ATR never saw."""
    return (atr_n or ATR_DEFAULT_N) * ATR_WARMUP + 1


def bars_needed(bars, atr_n=None, swings=None):
    """Candles the fetch must cover: what the caller wants to see, or the derived blocks' window if
    that is longer. ATR is recursive, so its value depends on how much history it was fed — deriving
    it from the returned slice would make the same instrument read differently for a 6-bar morning
    check and a 70-bar sizing run. The window is therefore fixed here, independent of `bars`;
    atr_wilder() and swing_lows() then trim to that same window from the other side, so a wider fetch
    cannot shift either result."""
    return max(bars, series_window(atr_n)) if (atr_n or swings) else bars


def atr_wilder(bars: Sequence[Bar], n=ATR_DEFAULT_N, interval=None) -> AtrReading | None:
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
    if len(idx) < n + 1:                                              # must not shift the value
        return None
    usable = [bars[i] for i in idx]
    h = [_f(b.high) for b in usable]
    lo = [_f(b.low) for b in usable]
    c = [_f(b.close) for b in usable]
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(c[i - 1] - lo[i]))
           for i in range(1, len(usable))]
    atr = sum(trs[:n]) / n                                  # Wilder's seed
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return AtrReading(n=n, method="wilder", value=round(atr, 4), bars_used=len(usable),
                      as_of=_day(usable[-1]), short_history=len(trs) < ATR_WARMUP * n,
                      interval=interval, quality=_window_quality(bars, idx[0]))


def swing_lows(bars: Sequence[Bar], each_side=SWING_SESSIONS_DEFAULT, interval=None,
               atr_n=None) -> SwingLows | None:
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
    idx = _usable(bars, "low")[-series_window(atr_n):]   # the same window ATR reads — see series_window()
    if not idx:
        return None
    usable = [bars[i] for i in idx]
    lows = [_f(b.low) for b in usable]
    detected = []
    for i in range(each_side, len(usable) - each_side):
        low = lows[i]
        if not all(lows[j] > low for j in range(i - each_side, i + each_side + 1) if j != i):
            continue
        after = lows[i + 1:]
        lowest_after = min(after)
        detected.append(SwingLow(
            session=_day(usable[i]),
            low_price=low,
            higher_than_previous_row_low=None if not detected else low > detected[-1].low_price,
            sessions_after_in_window=len(after),
            lowest_low_in_those_sessions=lowest_after,
            undercut_by_later_session=lowest_after < low,
        ))
    return SwingLows(
        each_side=each_side,
        window_first_session=_day(usable[0]), window_last_session=_day(usable[-1]),
        window_sessions=len(usable),
        detectable_through=_day(usable[-(each_side + 1)]) if len(usable) > each_side else None,
        detected=tuple(detected), interval=interval, quality=_window_quality(bars, idx[0]))


def last_closed(bars: Sequence[Bar]) -> LastClosed | None:
    """Most recent complete, trusted bar with a close — the number the checks want. None if none.
    Its quality names the closed sessions after it that were left out (and, for a W1/MN candle, its
    own). Read over the whole series the caller has, not the slice it shows: a short slice would
    hide the close."""
    idx = _usable(bars, "close")
    if not idx:
        return None
    b = bars[idx[-1]]
    return LastClosed(session=_day(b), close=_f(b.close), quality=_window_quality(bars, idx[-1]))
