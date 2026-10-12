"""Pure functions over bar series: weekly/monthly aggregation, Wilder ATR, swing lows, last close.

Bars are dicts {date, o, h, l, c, v, complete} (daily bars also carry `source`), newest last. Nothing here fetches or knows a vendor.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from market_data.model import Interval

ATR_DEFAULT_N = 14                              # Wilder's default lookback
ATR_WARMUP = 5                                  # x n candles of run-up before ATR is settled
SWING_SESSIONS_DEFAULT = 2                      # sessions each side that must have a higher low


def calendar_days(interval, bars):
    """Calendar days of daily history that `bars` candles of `interval` need (~1.5 per trading day;
    W1/MN are aggregated from daily)."""
    return math.ceil(bars * Interval(interval).calendar_factor)


def _period(date_str, interval):
    """(label, period_end) for a daily date grouped weekly/monthly.
    label = period start (Monday / 1st); period_end = last business/calendar day (Friday / month-end)."""
    interval = Interval(interval)
    d = date.fromisoformat(date_str)
    if interval is Interval.WEEKLY:
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat(), monday + timedelta(days=4)          # Mon .. Fri
    nxt = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return f"{d.year}-{d.month:02d}-01", nxt - timedelta(days=1)         # 1st .. month-end


def aggregate(daily, interval, today):
    """Roll daily bars up into weekly/monthly candles, newest last. o = first day's open, h/l = period
    extremes, c = last day's close, v = summed volume. A period is complete iff its last business/
    calendar day is before today, or that day has been reached and its own daily bar is already closed
    — so a week reads complete on Friday evening, not only on Saturday."""
    interval = Interval(interval)
    today_d = date.fromisoformat(today)
    newest = date.fromisoformat(daily[-1]["date"]) if daily else None
    order, groups = [], {}
    for b in daily:
        label, end = _period(b["date"], interval)
        g = groups.get(label)
        if g is None:
            g = groups[label] = {"end": end, "bars": []}
            order.append(label)
        g["bars"].append(b)

    out = []
    for label in order:
        g = groups[label]
        def col(k):
            return [x[k] for x in g["bars"] if x.get(k) is not None]
        opens, highs, lows, closes, vols = col("o"), col("h"), col("l"), col("c"), col("v")
        out.append({
            "date": label,
            "o": opens[0] if opens else None,
            "h": max(highs) if highs else None,
            "l": min(lows) if lows else None,
            "c": closes[-1] if closes else None,
            "v": sum(vols) if vols else None,
            "complete": g["end"] < today_d or (newest is not None and g["end"] <= newest
                                               and g["bars"][-1]["complete"]),
        })
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


def atr_wilder(bars, n=ATR_DEFAULT_N, interval=None):
    """Wilder's ATR(n) over a series (newest last), as a self-describing record — or None when there
    are fewer than n+1 usable candles. Method is J. Welles Wilder Jr., New Concepts in Technical
    Trading Systems (1978): TR = max(H-L, |H-prevC|, |prevC-L|), seed = mean of the first n TRs, then
    ATR = (prevATR x (n-1) + TR) / n.

    Only **complete** candles count: a forming bar's H/L keep moving, so it distorts both the TR and
    everything measured against it. `short_history` marks a value computed on less than the ATR_WARMUP
    run-up — still reported (never a silent [NO DATA]), but flagged as not yet settled."""
    usable = [b for b in bars if b.get("complete") and b.get("h") is not None
              and b.get("l") is not None and b.get("c") is not None]
    usable = usable[-series_window(n):]          # fixed window: a longer fetch must not shift the value
    if len(usable) < n + 1:
        return None
    trs = [max(usable[i]["h"] - usable[i]["l"],
               abs(usable[i]["h"] - usable[i - 1]["c"]),
               abs(usable[i - 1]["c"] - usable[i]["l"])) for i in range(1, len(usable))]
    atr = sum(trs[:n]) / n                                  # Wilder's seed
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    rec = {"n": n, "method": "wilder", "value": round(atr, 4), "bars_used": len(usable),
           "as_of": usable[-1]["date"], "short_history": len(trs) < ATR_WARMUP * n}
    if interval:
        rec["interval"] = interval
    return rec


def swing_lows(bars, each_side=SWING_SESSIONS_DEFAULT, interval=None, atr_n=None):
    """Confirmed swing lows over a series (newest last), as a self-describing record — or None when
    the series carries no usable candle. A swing low is a session whose low the `each_side` sessions
    before **and** after it did not reach, so it cannot be read until that many sessions have closed
    after it (`detectable_through` marks that edge).

    Every confirmed low is reported, including ones lower than the previous — this layer describes the
    series, it does not pick the one a trailing stop may use. The two derived fields carry what that
    choice needs: `higher_than_previous_row_low` compares with the preceding row, and
    `undercut_by_later_session` says whether price has since traded below the low (strict `<`, so an
    exact retest is not an undercut). Only **complete** candles count: a forming bar's low keeps
    moving, so it can neither be a swing low nor undercut one."""
    usable = [b for b in bars if b.get("complete") and b.get("l") is not None]
    usable = usable[-series_window(atr_n):]      # the same window ATR reads — see series_window()
    if not usable:
        return None
    lows = [b["l"] for b in usable]
    detected = []
    for i in range(each_side, len(usable) - each_side):
        low = lows[i]
        if not all(lows[j] > low for j in range(i - each_side, i + each_side + 1) if j != i):
            continue
        after = lows[i + 1:]
        lowest_after = min(after)
        detected.append({
            "date": usable[i]["date"],
            "low_price": low,
            "higher_than_previous_row_low": None if not detected else low > detected[-1]["low_price"],
            "sessions_after_in_window": len(after),
            "lowest_low_in_those_sessions": lowest_after,
            "undercut_by_later_session": lowest_after < low,
        })
    rec = {"sessions_each_side_with_higher_lows": each_side,
           "window_first_session": usable[0]["date"], "window_last_session": usable[-1]["date"],
           "window_sessions": len(usable),
           "detectable_through": usable[-(each_side + 1)]["date"] if len(usable) > each_side else None,
           "detected": detected}
    if interval:
        rec = {"candle_interval": interval, **rec}
    return rec


def last_closed(bars):
    """Most recent complete bar with a close — the number the checks want. None if none."""
    for b in reversed(bars):
        if b["complete"] and b["c"] is not None:
            return {"date": b["date"], "c": b["c"]}
    return None
