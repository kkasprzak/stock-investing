"""Shared test support for stock-market-data: frozen clock, fixture loaders, tolerances, a fake
QuoteSource.

Importing this module puts ../scripts on sys.path, so test files can `import quotes` and
`import market_data...` after `import support`. Named support, not fixtures: fixtures/ is the
directory of captured vendor responses.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "fixtures")
SCRIPTS = os.path.join(HERE, "..", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from market_data.adapters import yahoo              # noqa: E402  (needs SCRIPTS on sys.path)
from market_data.indicators import aggregate        # noqa: E402

FROZEN_TODAY = "2026-07-25"          # a Saturday; last session in fixtures is Fri 2026-07-24
FROZEN_NOW = 1784973600              # that Saturday 12:00 Warsaw — epoch for session-close checks
GPW_CLOSE = 17 * 3600 + 5 * 60       # WSE regular session ends 17:05 local (per Yahoo's own calendar)


def warsaw(y, m, d, secs):
    """Epoch for a Warsaw wall-clock moment (CEST, +2h) — session-boundary fixtures."""
    return (date(y, m, d) - date(1970, 1, 1)).days * 86400 + secs - 7200

TOL = lambda v: max(0.01, 0.0005 * abs(v))   # noqa: E731  price tolerance (rounding)

# Ex-dividend weeks: Stooq back-adjusts the pre-ex Open/High; we keep actual-traded (unadjusted).
# (ticker, interval, period_label) -> known unadjusted Open we must still report.
DIVIDEND_WEEKS = {
    ("PKN", "w", "2026-06-15"): 146.0,   # PKN ex-div 2026-06-17 (8.00)
    ("KGH", "w", "2026-06-22"): 375.0,   # KGH ex-div 2026-06-24 (1.50)
}


def load_yahoo(ticker):
    with open(os.path.join(FX, f"yahoo_{ticker}.json")) as f:
        return json.load(f)


class FakeSource:
    """A QuoteSource giving every instrument the same answer, or raising `error`."""

    name = "fake"
    description = "fake quotes"

    def __init__(self, series=None, error=None):
        self._series = series
        self._error = error
        self.asked = []                     # (instrument key, period)

    def daily(self, instrument, period, *, now):
        self.asked.append((instrument.key, period))
        if self._error is not None:
            raise self._error
        return self._series


def pipeline(ticker, interval):
    """Run the offline pipeline for a fixture at FROZEN_TODAY -> list of bars."""
    daily = yahoo.build_daily(load_yahoo(ticker), today=FROZEN_TODAY, now=FROZEN_NOW)
    if interval == "d":
        return daily
    return aggregate(daily, interval, FROZEN_TODAY)


def load_stooq(ticker, interval):
    """{our_date_label: {o,h,l,c}} from a Stooq CSV, aligned to our labels:
    daily = same date; weekly Sunday -> that week's Monday; monthly month-end -> 1st."""
    path = os.path.join(FX, f"stooq_{ticker.lower()}_{interval}.csv")
    out = {}
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        d = date.fromisoformat(row["Data"])
        if interval == "d":
            key = d.isoformat()
        elif interval == "w":
            key = (d - timedelta(days=6)).isoformat()
        else:
            key = f"{d.year}-{d.month:02d}-01"
        out[key] = {"o": float(row["Otwarcie"]), "h": float(row["Najwyzszy"]),
                    "l": float(row["Najnizszy"]), "c": float(row["Zamkniecie"])}
    return out
