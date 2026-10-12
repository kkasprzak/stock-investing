"""Yahoo Finance v8 chart as a QuoteSource. The only module that knows Yahoo's response format, its
symbol suffixes, its range buckets and the on-disk cache of its daily series."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from market_data.model import DateRange, Instrument
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)

DESCRIPTION = "Yahoo Finance v8 chart (~15 min delayed)"
THROTTLE = 1.5                                  # pause after each live Yahoo request (s)

# Yahoo fetch-range buckets (label, calendar-day span).
_RANGE_BUCKETS = [("1mo", 31), ("3mo", 92), ("6mo", 183), ("1y", 365),
                  ("2y", 730), ("5y", 1825), ("10y", 3650)]


def range_for_days(days):
    """Smallest Yahoo range whose span covers `days` calendar days ("max" when none does). Keeps
    small callers (e.g. a 6-bar morning check) cheap while letting triage pull ~252 daily bars."""
    for label, span in _RANGE_BUCKETS:
        if span >= days:
            return label
    return "max"


def range_days(label):
    """Calendar-day span of a Yahoo range label (unknown / 'max' -> effectively unbounded)."""
    for lbl, span in _RANGE_BUCKETS:
        if lbl == label:
            return span
    return 10 ** 9


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


class YahooQuotes:
    """QuoteSource over Yahoo's v8 chart endpoint. `fetch`, `sleep` and `now` are injectable so tests
    run offline; cache_dir=None (the default) never touches the disk — the fail-safe: a forgotten
    --cache means slower, never stale."""

    name = "yahoo"

    def __init__(self, *, fetch=fetch_chart, cache_dir: Path | None = None,
                 throttle: float = THROTTLE, sleep=time.sleep) -> None:
        self._fetch = fetch
        self._cache_dir = cache_dir
        self._throttle = throttle
        self._sleep = sleep

    def resolve(self, instrument: Instrument) -> Resolution:
        """The map's yahoo symbol; else suffix-swap the caller's key .PL->.WA, flagged as a guess."""
        yahoo = instrument.symbols.get(self.name)
        if yahoo:
            return Resolution(self.name, yahoo, ResolvedBy.SYMBOLS_JSON)
        key = instrument.key
        if key.endswith(".PL"):                        # GPW: broker .PL -> Yahoo .WA
            return Resolution(self.name, key[:-3] + ".WA", ResolvedBy.SUFFIX_GUESS)
        return Resolution(self.name, key, ResolvedBy.SUFFIX_GUESS)   # foreign: already Yahoo-shaped

    def daily(self, instrument: Instrument, period: DateRange, *, now: float) -> QuoteSeries:
        """Every daily bar of the smallest Yahoo range covering `period` (often more than asked).
        Any failure to answer, Yahoo's not_found included, raises QuoteSourceUnavailableError.
        Yahoo's ranges always end today, so only `period.days` picks the range: a period ending in
        the past still gets the latest bars, not its own window. `period.end` is the cache key's day.
        The only caller (the CLI) passes a period ending today."""
        resolution = self.resolve(instrument)
        bars, how = self._daily(resolution.symbol, range_for_days(period.days),
                                period.end.isoformat(), now)
        if bars is None:
            raise QuoteSourceUnavailableError((SourceFailure(self.name, how),), (resolution,))
        if how == "live":
            self._sleep(self._throttle)                # throttle real fetches only
        for b in bars:
            b.setdefault("source", self.name)          # after the cache write: stored bars lack it
        return QuoteSeries(tuple(bars), (resolution,))

    def _daily(self, yahoo, rng, today, now):
        """Daily bars for `yahoo` over range `rng`. Returns (bars, "live"|"cache") on success, or
        (None, reason) if the fetch failed. `today` is the cache key's day (the caller's date) — bar
        completeness is decided per market, from the venue's tz and session close, not from this.
        Without a cache_dir it always fetches live. With one, a stored series is reused iff it was
        saved the same day, on the same side of that venue's session close, AND its range covers
        `rng`; otherwise refetch and rewrite. Closed candles are immutable, so there's no TTL — but
        the day's *forming* bar is not a closed candle, so the entry also carries the session state it
        was written in: crossing the close invalidates it, or a mid-session snapshot would later be
        served as the day's closed candle. `complete` is never trusted from disk; a hit re-stamps it
        against the current clock."""
        use_cache = self._cache_dir is not None
        path = (self._cache_dir / (yahoo.replace(os.sep, "_") + ".json")) if use_cache else None
        if use_cache and path.exists():
            try:
                with open(path) as f:
                    c = json.load(f)
                off, end = c.get("gmtoffset", 0), c.get("session_end")
                closed_now = (end or float("inf")) <= now
                if (c.get("market_date") == today and c.get("session_over") == closed_now
                        and range_days(c.get("range", "1mo")) >= range_days(rng)):
                    # Same market day AND same side of the close: the session can't have moved on, so
                    # the stored series is still the series. Crossing the close makes it stale — the
                    # forming bar's OHLC keeps changing until then, and serving it as closed would
                    # report a mid-session snapshot as the day's candle.
                    return stamp_complete(c["daily"], market_today(off, now), closed_now), "cache"
            except Exception:
                pass                                    # unreadable cache -> fall through to live
        r, reason = self._fetch(yahoo, rng)
        if r is None:
            return None, reason
        daily = build_daily(r, now=now)
        if use_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "w") as f:
                end = session_end(r["meta"])
                json.dump({"market_date": today, "range": rng, "gmtoffset": r["meta"].get("gmtoffset", 0),
                           "session_end": end, "session_over": (end or float("inf")) <= now,
                           "daily": daily}, f)
            os.replace(tmp, path)                       # atomic write
        return daily, "live"
