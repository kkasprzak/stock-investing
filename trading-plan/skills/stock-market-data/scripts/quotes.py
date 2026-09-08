#!/usr/bin/env python3
"""stock-market-data: fresh delayed daily/weekly/monthly OHLC quotes for named stock tickers.

Agent-first tool. Output is self-describing JSON (default) — read the keys, no docs needed.
  python3 quotes.py PKN.PL ALE.PL PKO.PL          # broker tickers, daily (D1)
  python3 quotes.py PKN.PL --interval w           # weekly (W1); m = monthly (MN)
  python3 quotes.py PKN.PL --bars 10              # more history per symbol
  python3 quotes.py PKN.PL --atr                 # + Wilder ATR(14) on that interval (--atr 20 to override)
  python3 quotes.py PKN.PL --swings              # + confirmed swing lows (2 sessions each side; --swings 3 to override)
Fetches recent completed candles from Yahoo (~15 min delayed) for the given instruments, resolved via
the shared symbols.json map (broker -> vendor symbol). W1/MN are aggregated from the daily series
(Yahoo's native weekly/monthly bars split the current period unreliably). Evaluation/monitoring only —
execution prices come from the execution venue, not here. A price it can't read is "[NO DATA]".
"""
import sys, os, json, time, argparse, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone, date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = os.path.join(HERE, "symbols.json")   # the shared symbol map (self-contained)
# Opt-in on-disk cache of daily series, OUTSIDE the skill (keeps the distributable artifact pure).
# Default: `.cache/stock-market-data` under the project that launched the skill (CLAUDE_PROJECT_DIR);
# override with STOCK_MARKET_DATA_CACHE; fall back to the system temp dir when run outside a project.
CACHE_DIR = (os.environ.get("STOCK_MARKET_DATA_CACHE")
             or (os.path.join(os.environ["CLAUDE_PROJECT_DIR"], ".cache", "stock-market-data")
                 if os.environ.get("CLAUDE_PROJECT_DIR")
                 else os.path.join(tempfile.gettempdir(), "stock-market-data")))
THROTTLE = 1.5                                  # pause between Yahoo requests (s)
DEFAULT_BARS = 6                                # bars returned per symbol
INTERVAL_LABEL = {"d": "daily", "w": "weekly", "m": "monthly"}
ATR_DEFAULT_N = 14                              # Wilder's default lookback
ATR_WARMUP = 5                                  # x n candles of run-up before ATR is settled
SWING_SESSIONS_DEFAULT = 2                      # sessions each side that must have a higher low

# Yahoo fetch-range buckets (label, calendar-day span) and per-interval calendar headroom per bar.
# W1/MN are aggregated from the daily series, so every interval maps onto daily calendar days.
_RANGE_BUCKETS = [("1mo", 31), ("3mo", 92), ("6mo", 183), ("1y", 365),
                  ("2y", 730), ("5y", 1825), ("10y", 3650)]
_RANGE_FACTOR = {"d": 1.5, "w": 7, "m": 30}     # daily: ~1.5 calendar days per trading day


def range_for(interval, bars):
    """Smallest Yahoo range whose span covers `bars` candles of `interval`. Keeps small callers
    (e.g. a 6-bar morning check) cheap while letting triage pull ~252 daily bars."""
    needed = bars * _RANGE_FACTOR[interval]
    for label, span in _RANGE_BUCKETS:
        if span >= needed:
            return label
    return "max"


def _range_days(label):
    """Calendar-day span of a Yahoo range label (unknown / 'max' -> effectively unbounded)."""
    for lbl, span in _RANGE_BUCKETS:
        if lbl == label:
            return span
    return 10 ** 9


def load_index():
    """Return {lookup_key: entry}, keyed by both ISIN and xtb ticker. entry = {isin, name,
    symbols:{source: ticker}}. Callers keyed by broker ticker (state files) hit the xtb key;
    callers keyed by ISIN (e.g. index-membership sourcing) hit the ISIN key — no suffix guess."""
    with open(SYMBOLS) as f:
        data = json.load(f)
    idx = {}
    for isin, e in data["instruments"].items():
        entry = {"isin": isin, **e}
        idx[isin] = entry                          # resolve by ISIN (durable, rename-proof)
        xtb = e.get("symbols", {}).get("xtb")
        if xtb:
            idx[xtb] = entry                       # and by broker ticker (state-file anchor)
    return idx


def resolve(ticker, idx):
    """(yahoo_symbol, resolved_by). Map by xtb ticker; else suffix-swap .PL->.WA, flagged as a guess.
    Source name ('yahoo') is a parameter here so adding vendors stays data-only."""
    e = idx.get(ticker)
    if e and e.get("symbols", {}).get("yahoo"):
        return e["symbols"]["yahoo"], "symbols.json"
    if ticker.endswith(".PL"):                     # GPW: broker .PL -> Yahoo .WA
        return ticker[:-3] + ".WA", "suffix_guess"
    return ticker, "suffix_guess"                  # foreign (.DE/.US/...) already Yahoo-shaped


def broker_symbol(ticker, idx):
    """The execution-venue ticker for this instrument, or None when the map has none. Callers keyed
    by ISIN (index-membership sourcing) need it to name a state-file row. Never guessed: an
    instrument the broker does not list must be confirmed there, not inferred from the GPW root."""
    return (idx.get(ticker) or {}).get("symbols", {}).get("xtb")


def fetch_chart(yahoo, rng, tries=4):
    """Return (result, None) or (None, reason). Mirrors screen.py fetch idiom + 429 linear backoff."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?range={rng}&interval=1d"
    delay = 3
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            if d.get("chart", {}).get("error"):
                return None, d["chart"]["error"].get("code", "error")
            r = d["chart"]["result"]
            if not r:
                return None, "not_found"
            return r[0], None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(delay * (t + 1)); continue
            return None, "not_found" if e.code == 404 else f"http_{e.code}"
        except Exception:
            time.sleep(delay); continue
    return None, "rate_limited"


def _date(ts, off):
    """Local session date (YYYY-MM-DD) for an epoch, given the market's gmt offset."""
    return datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")


def market_today(off, now=None):
    """Today's date (YYYY-MM-DD) in the market's local tz."""
    return datetime.fromtimestamp((time.time() if now is None else now) + off,
                                  timezone.utc).strftime("%Y-%m-%d")


def session_end(meta):
    """Epoch at which the venue's current regular session ends, from the exchange's own calendar
    (meta.currentTradingPeriod.regular.end) — no hardcoded per-market close times, so half-days and
    DST come along for free. None when the vendor omits it."""
    e = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end")
    return e if isinstance(e, (int, float)) else None


def stamp_complete(bars, today, closed_today):
    """(Re)set each bar's `complete`, in place. An earlier market date is closed by definition;
    today's bar is closed only once the venue's regular session has ended — an evening run on a
    closed exchange must see today's candle as a fact, not as still forming."""
    for b in bars:
        b["complete"] = b["date"] < today or (b["date"] == today and closed_today)
    return bars


def build_daily(r, today=None, now=None):
    """All daily bars {date,o,h,l,c,v,complete}, newest last.
    Yahoo quirk: the latest session's bar trails close=None in the array until backfilled — the real
    close sits in meta.regularMarketPrice, dated by regularMarketTime; patch it in. Completeness is
    session-aware (see stamp_complete), keyed off the venue's own close time.
    `today` (YYYY-MM-DD, market tz) and `now` (epoch) are injectable so tests are deterministic;
    both default to the wall clock read in the market's tz."""
    m = r["meta"]; off = m.get("gmtoffset", 0)
    ts = r.get("timestamp") or []
    q = r["indicators"]["quote"][0]
    o, h, l, c, v = (q.get(k, []) for k in ("open", "high", "low", "close", "volume"))
    now = time.time() if now is None else now
    if today is None:
        today = market_today(off, now)
    closed_today = (session_end(m) or float("inf")) <= now
    rmp, rmt = m.get("regularMarketPrice"), m.get("regularMarketTime")
    rmt_date = _date(rmt, off) if rmt else None

    def at(a, i):
        return a[i] if i < len(a) else None

    bars, n = [], len(ts)
    for i in range(n):
        dt = _date(ts[i], off)
        oi, hi, li, ci, vi = at(o, i), at(h, i), at(l, i), at(c, i), at(v, i)
        if ci is None and i == n - 1 and rmp is not None:   # backfill trailing latest-session close
            ci = rmp
            if rmt_date:
                dt = rmt_date
        if oi is None and hi is None and li is None and ci is None:
            continue                                        # empty placeholder bar
        bars.append({
            "date": dt,
            "o": round(oi, 4) if oi is not None else None,
            "h": round(hi, 4) if hi is not None else None,
            "l": round(li, 4) if li is not None else None,
            "c": round(ci, 4) if ci is not None else None,
            "v": int(vi) if vi is not None else None,
        })
    return stamp_complete(bars, today, closed_today)


def get_daily(yahoo, rng, today, use_cache=False, fetch=None, now=None):
    """Daily bars for `yahoo` over range `rng`. Returns (bars, "live"|"cache") on success, or
    (None, reason) if the fetch failed. `today` is the cache key's day (the caller's date) — bar
    completeness is decided per market, from the venue's tz and session close, not from this. Default
    (use_cache False) always fetches live — the fail-safe: a forgotten flag means slower, never stale.
    With use_cache, a stored series is reused iff it was saved the same day, on the same side of that
    venue's session close, AND its range covers `rng`; otherwise refetch and rewrite. Closed candles
    are immutable, so there's no TTL — but the day's *forming* bar is not a closed candle, so the
    entry also carries the session state it was written in: crossing the close invalidates it, or a
    mid-session snapshot would later be served as the day's closed candle. `complete` is never trusted
    from disk; a hit re-stamps it against the current clock. `fetch` / `now` are injectable."""
    fetch = fetch or fetch_chart
    now = time.time() if now is None else now
    path = os.path.join(CACHE_DIR, yahoo.replace(os.sep, "_") + ".json")
    if use_cache and os.path.exists(path):
        try:
            with open(path) as f:
                c = json.load(f)
            off, end = c.get("gmtoffset", 0), c.get("session_end")
            closed_now = (end or float("inf")) <= now
            if (c.get("market_date") == today and c.get("session_over") == closed_now
                    and _range_days(c.get("range", "1mo")) >= _range_days(rng)):
                # Same market day AND same side of the close: the session can't have moved on, so the
                # stored series is still the series. Crossing the close makes it stale — the forming
                # bar's OHLC keeps changing until then, and serving it as closed would report a
                # mid-session snapshot as the day's candle.
                return stamp_complete(c["daily"], market_today(off, now), closed_now), "cache"
        except Exception:
            pass                                        # unreadable cache -> fall through to live
    r, reason = fetch(yahoo, rng)
    if r is None:
        return None, reason
    daily = build_daily(r, now=now)
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            end = session_end(r["meta"])
            json.dump({"market_date": today, "range": rng, "gmtoffset": r["meta"].get("gmtoffset", 0),
                       "session_end": end, "session_over": (end or float("inf")) <= now,
                       "daily": daily}, f)
        os.replace(tmp, path)                           # atomic write
    return daily, "live"


def _period(date_str, interval):
    """(label, period_end) for a daily date grouped weekly/monthly.
    label = period start (Monday / 1st); period_end = last business/calendar day (Friday / month-end)."""
    d = date.fromisoformat(date_str)
    if interval == "w":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat(), monday + timedelta(days=4)          # Mon .. Fri
    nxt = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return f"{d.year}-{d.month:02d}-01", nxt - timedelta(days=1)         # 1st .. month-end


def aggregate(daily, interval, today):
    """Roll daily bars up into weekly/monthly candles, newest last. o = first day's open, h/l = period
    extremes, c = last day's close, v = summed volume. A period is complete iff its last business/
    calendar day is before today, or that day has been reached and its own daily bar is already closed
    — so a week reads complete on Friday evening, not only on Saturday."""
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


def quote_record(daily, interval, bars, today, atr_n=None, swings=None):
    """The per-symbol payload: the last `bars` candles of `interval`, their last closed one, and
    optionally ATR and the swing lows. Both derived blocks are computed over the **whole** fetched
    series, not the returned slice — see bars_needed()."""
    series = daily if interval == "d" else aggregate(daily, interval, today)
    shown = series[-bars:]
    rec = {"last_closed": last_closed(shown), "bars": shown}
    if atr_n:
        rec["atr"] = atr_wilder(series, atr_n, INTERVAL_LABEL[interval])
    if swings:
        rec["swing_lows"] = swing_lows(series, swings, INTERVAL_LABEL[interval], atr_n)
    return rec


def last_closed(bars):
    """Most recent complete bar with a close — the number the checks want. None if none."""
    for b in reversed(bars):
        if b["complete"] and b["c"] is not None:
            return {"date": b["date"], "c": b["c"]}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+", metavar="TICKER", help="broker tickers, e.g. PKN.PL ALE.PL")
    ap.add_argument("--interval", choices=("d", "w", "m"), default="d",
                    help="candle interval: d=daily (default), w=weekly, m=monthly")
    ap.add_argument("--bars", type=int, default=DEFAULT_BARS, metavar="N",
                    help=f"bars returned per symbol (default {DEFAULT_BARS})")
    ap.add_argument("--atr", type=int, nargs="?", const=ATR_DEFAULT_N, default=None, metavar="N",
                    help=f"also report Wilder ATR(N) on the chosen interval (bare --atr = "
                         f"{ATR_DEFAULT_N}); widens the fetch to cover ATR's run-up, so the value "
                         f"never depends on --bars")
    ap.add_argument("--swings", type=int, nargs="?", const=SWING_SESSIONS_DEFAULT, default=None,
                    metavar="N",
                    help=f"also report confirmed swing lows on the chosen interval, N sessions each "
                         f"side (bare --swings = {SWING_SESSIONS_DEFAULT}); reads the same window as "
                         f"ATR, so both describe one stretch of history")
    ap.add_argument("--cache", action="store_true",
                    help="reuse the same market day's closed candles from an on-disk cache; omit when "
                         "the moment needs live data")
    args = ap.parse_args()

    idx = load_index()
    today = date.today().isoformat()
    rng = range_for(args.interval, bars_needed(args.bars, args.atr, args.swings))
    quotes = {}
    for tk in args.tickers:
        yahoo, how = resolve(tk, idx)
        xtb = broker_symbol(tk, idx)
        daily, src = get_daily(yahoo, rng, today, use_cache=args.cache)
        if daily is None:
            quotes[tk] = {"yahoo_symbol": yahoo, "xtb": xtb, "resolved_by": how, "ok": False,
                          "reason": src, "value": "[NO DATA]"}
            continue
        if src == "live":
            time.sleep(THROTTLE)                        # throttle real fetches only
        quotes[tk] = {"yahoo_symbol": yahoo, "xtb": xtb, "resolved_by": how, "ok": True,
                      **quote_record(daily, args.interval, args.bars, today, args.atr, args.swings)}

    result = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance v8 chart (~15 min delayed)",
        "interval": INTERVAL_LABEL[args.interval],
        "data_note": "Evaluation/monitoring only — NOT execution prices (those come from the execution "
                     "venue). Bars with complete:false are still forming; drop them for closed-candle "
                     "decisions. Today's bar flips to complete:true once that venue's regular session "
                     "has closed, so an evening run reads today's candle as a fact. W1/MN are "
                     "aggregated from daily.",
        "quotes": quotes,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
