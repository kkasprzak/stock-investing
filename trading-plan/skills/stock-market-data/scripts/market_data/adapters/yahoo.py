"""Yahoo Finance v8 chart as a QuoteSource. The only module that knows Yahoo's response format, its
symbol suffixes and its range buckets. It keeps nothing on disk: there is no cache (ADR 0004)."""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal

from market_data.model import DailyBar, DateRange, Instrument, Price, Trust, Volume
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)

SOURCE = "yahoo"                                # the adapter's name, on every bar it serves
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


def _price(x) -> Price | None:
    """Yahoo's number as a Price, rounded as build_daily rounds so float(price.value) gives back the
    same float. No price at all when it cannot be one: Yahoo sometimes sends 0 (and a tiny value
    rounds to 0.0), and an exception out of the adapter would be a bug, not an answer."""
    if x is None or not math.isfinite(x):
        return None
    x = round(x, 4)
    return Price(Decimal(repr(x))) if x > 0 else None


PLACEHOLDER = Trust.untrusted("placeholder")
UNUSABLE_PRICE = Trust.untrusted("unusable_price")


def _trust(o: Price | None, h: Price | None, l: Price | None, c: Price | None,  # noqa: E741
           volume: Volume | None, unusable: bool) -> Trust:
    """Yahoo fills a session it has no trades for with one price in all four fields and no volume.
    Such a bar is marked, not repaired or dropped. The bar alone decides: no look at the session
    before it, so the first bar of an answer and a forming one are judged the same way.

    A price Yahoo sent that is no price (0, negative, not finite) marks the session too, so the gap
    it leaves is named rather than silent; a price Yahoo did not send is a plain gap. That reason
    comes first: a session flat at 0 has no price it could have been filled with."""
    if unusable:
        return UNUSABLE_PRICE
    flat = None not in (o, h, l, c) and o == h == l == c
    return PLACEHOLDER if flat and (volume is None or volume.value == 0) else Trust.TRUSTED


def to_bar(row: dict) -> DailyBar:
    """A row of build_daily as the port's DailyBar, with Yahoo's judgement of it."""
    v = row.get("v")
    sent = [row.get(k) for k in ("o", "h", "l", "c")]
    o, h, l, c = prices = [_price(x) for x in sent]  # noqa: E741
    unusable = any(x is not None and p is None for x, p in zip(sent, prices))
    volume = Volume(int(v)) if v is not None and math.isfinite(v) and v >= 0 else None
    return DailyBar(session=date.fromisoformat(row["date"]), open=o, high=h, low=l, close=c,
                    volume=volume, complete=row["complete"], source=SOURCE,
                    trust=_trust(o, h, l, c, volume, unusable))


class YahooQuotes:
    """QuoteSource over Yahoo's v8 chart endpoint. `fetch`, `sleep` and `now` are injectable so tests
    run offline. Every call fetches live; nothing is written to disk. Every bar it serves is judged
    by to_bar: Yahoo's placeholder sessions come out untrusted."""

    name = SOURCE
    description = "Yahoo Finance v8 chart (~15 min delayed)"

    def __init__(self, *, fetch=fetch_chart, throttle: float = THROTTLE,
                 sleep=time.sleep) -> None:
        self._fetch = fetch
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
        the past still gets the latest bars, not its own window. Bar completeness is decided per
        market, from the venue's tz and session close (build_daily), not from `period.end`.
        The only caller (the CLI) passes a period ending today."""
        resolution = self.resolve(instrument)
        r, reason = self._fetch(resolution.symbol, range_for_days(period.days))
        if r is None:
            raise QuoteSourceUnavailableError((SourceFailure(self.name, reason),), (resolution,))
        self._sleep(self._throttle)                    # pause after each answered fetch
        return QuoteSeries(tuple(to_bar(b) for b in build_daily(r, now=now)), (resolution,))
