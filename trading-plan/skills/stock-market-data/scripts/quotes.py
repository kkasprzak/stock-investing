#!/usr/bin/env python3
"""stock-market-data: fresh delayed daily/weekly/monthly OHLC quotes for named stock tickers.

Agent-first tool. Output is self-describing JSON (default) — read the keys, no docs needed.
  python3 quotes.py PKN.PL ALE.PL PKO.PL          # broker tickers, daily (D1)
  python3 quotes.py PKN.PL --interval w           # weekly (W1); m = monthly (MN)
  python3 quotes.py PKN.PL --bars 10              # more history per symbol
  python3 quotes.py PKN.PL --atr                 # + Wilder ATR(14) on that interval (--atr 20 to override)
  python3 quotes.py PKN.PL --swings              # + confirmed swing lows (2 sessions each side; --swings 3 to override)
  python3 quotes.py PKN.PL --store DIR           # this project's own candle store first, Yahoo after
Reads recent completed candles for the given instruments, resolved via the shared symbols.json map
(broker -> ISIN and vendor symbol): from the own candle store (--store, one CSV per ISIN) when given,
and from Yahoo (~15 min delayed) for every session the store does not have. W1/MN are aggregated
from the daily series (Yahoo's native weekly/monthly bars split the current period unreliably). Evaluation/monitoring only —
execution prices come from the execution venue, not here. A price it can't read is "[NO DATA]".
Layout: this CLI talks to one QuoteSource port (market_data/ports.py), behind which a QuoteChain asks
its sources in trust order, each an adapter (market_data/adapters/store.py, then .../yahoo.py).
"""
from __future__ import annotations

import sys, os, json, time, argparse, tempfile
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data.adapters.store import StoreQuotes          # noqa: E402
from market_data.adapters.symbol_index import SymbolIndex   # noqa: E402
from market_data.adapters.yahoo import YahooQuotes, fetch_chart   # noqa: E402
from market_data.indicators import (ATR_DEFAULT_N, SWING_SESSIONS_DEFAULT,   # noqa: E402
                                    aggregate, atr_wilder, bars_needed, calendar_days,
                                    last_closed, swing_lows)
from market_data.model import DateRange, Interval           # noqa: E402
from market_data.ports import QuoteSource, QuoteSourceUnavailableError   # noqa: E402
from market_data.quote_chain import QuoteChain              # noqa: E402

SYMBOLS = Path(HERE) / "symbols.json"           # the shared symbol map (self-contained)
# Opt-in on-disk cache of daily series, OUTSIDE the skill (keeps the distributable artifact pure).
# Default: `.cache/stock-market-data` under the project that launched the skill (CLAUDE_PROJECT_DIR);
# override with STOCK_MARKET_DATA_CACHE; fall back to the system temp dir when run outside a project.
CACHE_DIR = Path(os.environ.get("STOCK_MARKET_DATA_CACHE")
                 or (os.path.join(os.environ["CLAUDE_PROJECT_DIR"], ".cache", "stock-market-data")
                     if os.environ.get("CLAUDE_PROJECT_DIR")
                     else os.path.join(tempfile.gettempdir(), "stock-market-data")))
DEFAULT_BARS = 6                                # bars returned per symbol
MAX_PERIOD_DAYS = 365 * 50                      # beyond Yahoo's widest bucket ("max"); keeps timedelta sane
MIN_PERIOD_DAYS = 9                             # the port's promise: an empty answer never means "weekend"
                                                # (below Yahoo's smallest bucket, 1mo, so no fetch changes)


def build_source(cache: bool, *, store_dir: Path | None = None, cache_dir: Path = CACHE_DIR,
                 fetch=fetch_chart, sleep=time.sleep) -> QuoteSource:
    """The composition root: which sources answer, in which order. `fetch` and `sleep` are injectable
    so tests run offline and unthrottled."""
    # no --cache = no cache: fail-safe (a forgotten flag means slower, never stale)
    yahoo_source = YahooQuotes(fetch=fetch, cache_dir=cache_dir if cache else None, sleep=sleep)
    # Order on this list = trust hierarchy (ADR 0000, docs/adr/0000-own-candle-store-is-the-most-
    # trusted-source-of-market-data.md): the own candle store first, Yahoo patches what it lacks.
    store = [StoreQuotes(store_dir)] if store_dir is not None else []
    return QuoteChain([*store, yahoo_source])


def quote_record(daily, interval, bars, today, atr_n=None, swings=None):
    """The per-symbol payload: the last `bars` candles of `interval`, their last closed one, and
    optionally ATR and the swing lows. Both derived blocks are computed over the **whole** fetched
    series, not the returned slice — see bars_needed()."""
    interval = Interval(interval)
    series = daily if interval is Interval.DAILY else aggregate(daily, interval, today)
    shown = series[-bars:]
    rec = {"last_closed": last_closed(shown), "bars": shown}
    if atr_n:
        rec["atr"] = atr_wilder(series, atr_n, interval.label)
    if swings:
        rec["swing_lows"] = swing_lows(series, swings, interval.label, atr_n)
    return rec


def _from_yahoo(entries):
    """The Yahoo entry among a source's Resolutions or SourceFailures, or None when Yahoo is not
    among them: the output contract's fields (yahoo_symbol, resolved_by, reason) are Yahoo's by name."""
    return next((e for e in entries if e.source == YahooQuotes.name), None)


def _yahoo_fields(resolved):
    res = _from_yahoo(resolved)
    return (res.symbol, res.by.value) if res else (None, None)


def _unavailable(failures):
    return [{"source": f.source, "reason": f.reason} for f in failures]


def _no_data(xtb, resolved, failures):
    """The one ok:false record, whether no source answered or the ones that did had no bars.
    `reason` is Yahoo's when Yahoo failed (the output contract names it), else the first failure's;
    `unavailable` always lists every failure."""
    symbol, by = _yahoo_fields(resolved)
    failure = _from_yahoo(failures) or next(iter(failures), None)
    return {"yahoo_symbol": symbol, "xtb": xtb, "resolved_by": by, "ok": False,
            "reason": failure.reason if failure else None, "value": "[NO DATA]",
            "unavailable": _unavailable(failures)}


def _store_dir(text: str) -> Path:
    """--store as given, never touched here. A literal `${` is a skill variable Claude Code did not
    substitute: reading it as a path would turn a broken setup into an innocent store not_found."""
    if "${" in text:
        raise argparse.ArgumentTypeError(
            f"{text!r} holds a variable that was not substituted (literal '${{'); pass the "
            f"project's real path, e.g. --store /path/to/project/data/market-data")
    return Path(text)


def main(argv=None, *, source: QuoteSource | None = None, build=build_source,
         today: date | None = None):
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
    ap.add_argument("--store", type=_store_dir, default=None, metavar="DIR",
                    help="this project's own candle store, one CSV per ISIN; asked before Yahoo")
    args = ap.parse_args(argv)

    index = SymbolIndex(SYMBOLS)
    interval = Interval(args.interval)
    end = today or date.today()
    today = end.isoformat()
    # --bars <= 0 never failed and must not now: DateRange would reject an inverted range.
    days = min(max(calendar_days(interval, bars_needed(max(args.bars, 1), args.atr, args.swings)),
                   MIN_PERIOD_DAYS),
               MAX_PERIOD_DAYS)
    period = DateRange(end - timedelta(days=days), end)
    if source is None:
        source = build(args.cache, store_dir=args.store)
    quotes = {}
    for tk in args.tickers:
        instrument = index.lookup(tk)
        xtb = instrument.symbols.get("xtb")
        try:
            series = source.daily(instrument, period, now=time.time())
        except QuoteSourceUnavailableError as e:
            quotes[tk] = _no_data(xtb, e.resolved, e.failures)
            continue
        if not series.bars and series.unavailable:  # no bars, and a source that might have had them failed
            quotes[tk] = _no_data(xtb, series.resolved, series.unavailable)
            continue
        symbol, by = _yahoo_fields(series.resolved)
        quotes[tk] = {"yahoo_symbol": symbol, "xtb": xtb, "resolved_by": by, "ok": True,
                      **quote_record(list(series.bars), interval, args.bars, today, args.atr,
                                     args.swings)}
        if series.unavailable:                      # only when some source did not answer
            quotes[tk]["unavailable"] = _unavailable(series.unavailable)

    result = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source.description,
        "interval": interval.label,
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
