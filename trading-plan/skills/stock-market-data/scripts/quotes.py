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

import sys, os, json, time, argparse
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data.adapters.store import StoreQuotes          # noqa: E402
from market_data.adapters.symbol_index import SymbolIndex   # noqa: E402
from market_data.adapters.yahoo import YahooQuotes, fetch_chart   # noqa: E402
from market_data.indicators import (ATR_DEFAULT_N, SWING_SESSIONS_DEFAULT,   # noqa: E402
                                    AtrReading, LastClosed, SwingLow, SwingLows, aggregate,
                                    atr_wilder, bars_needed, calendar_days, last_closed,
                                    swing_lows)
from market_data.model import (AtrPeriod, DailyBar, DateRange, Interval, PeriodBar,   # noqa: E402
                               PeriodInterval, SessionsEachSide)
from market_data.ports import QuoteSource, QuoteSourceUnavailableError   # noqa: E402
from market_data.quote_chain import QuoteChain              # noqa: E402

SYMBOLS = Path(HERE) / "symbols.json"           # the shared symbol map (self-contained)
DEFAULT_BARS = 6                                # bars returned per symbol
MAX_PERIOD_DAYS = 365 * 50                      # beyond Yahoo's widest bucket ("max"); keeps timedelta sane
MIN_PERIOD_DAYS = 9                             # the port's promise: an empty answer never means "weekend"
                                                # (below Yahoo's smallest bucket, 1mo, so no fetch changes)


def build_source(*, store_dir: Path | None = None, fetch=fetch_chart,
                 sleep=time.sleep) -> QuoteSource:
    """The composition root: which sources answer, in which order. `fetch` and `sleep` are injectable
    so tests run offline and unthrottled. Nothing here writes to disk: there is no cache (ADR 0004)."""
    yahoo_source = YahooQuotes(fetch=fetch, sleep=sleep)
    # Order on this list = trust hierarchy (ADR 0000, docs/adr/0000-own-candle-store-is-the-most-
    # trusted-source-of-market-data.md): the own candle store first, Yahoo patches what it lacks.
    store = [StoreQuotes(store_dir)] if store_dir is not None else []
    return QuoteChain([*store, yahoo_source])


def quote_record(daily, interval, bars, today: date, atr_n: AtrPeriod | None = None,
                 swings: SessionsEachSide | None = None):
    """The per-symbol payload: the last `bars` candles of `interval`, the last closed one, and
    optionally ATR and the swing lows. The last closed candle and both derived blocks are read over
    the **whole** fetched series, not the returned slice — see bars_needed(). Values are types;
    to_json prints them."""
    interval = Interval(interval)
    series = (daily if interval is Interval.DAILY
              else aggregate(daily, PeriodInterval(interval), today))
    rec = {"last_closed": last_closed(series), "bars": series[-bars:]}
    if atr_n is not None:
        rec["atr"] = atr_wilder(series, atr_n, interval)
    if swings is not None:
        rec["swing_lows"] = swing_lows(series, swings, interval, atr_n)
    return rec


def _num(p):
    return None if p is None else float(p.value)


def _ohlcv(b):
    return {"o": _num(b.open), "h": _num(b.high), "l": _num(b.low), "c": _num(b.close),
            "v": None if b.volume is None else b.volume.value, "complete": b.complete}


def _quality(status, quality):
    """A derived value's status and the sessions it left out, always both (an empty list when good)."""
    return {"status": status.value, "excluded_sessions": [d.isoformat() for d in quality.excluded]}


def to_json(obj):
    """The output contract's shape of a bar or a reading: keys and their order as consumers read
    them, prices as floats, dates as ISO text. A daily bar says whether its source vouches for it,
    and why not only when it does not. A derived value (a W1/MN bar, last_closed, atr, swing_lows)
    says its status and the sessions it left out (ADR 0002). Anything else raises TypeError, as
    json.dump's `default` must."""
    if isinstance(obj, DailyBar):
        rec = {"date": obj.session.isoformat(), **_ohlcv(obj), "source": obj.source,
               "trusted": obj.trust.trusted}
        if not obj.trust.trusted:
            rec["untrusted_reason"] = obj.trust.reason
        return rec
    if isinstance(obj, PeriodBar):                  # rolled up from several sources: none named
        return {"date": obj.period_start.isoformat(), **_ohlcv(obj),
                **_quality(obj.status, obj.quality)}
    if isinstance(obj, LastClosed):
        return {"date": obj.session.isoformat(), "c": _num(obj.close),
                **_quality(obj.quality.status, obj.quality)}
    if isinstance(obj, AtrReading):
        rec = {"n": obj.n.value, "method": obj.method, "value": obj.value,
               "bars_used": obj.bars_used, "as_of": obj.as_of.isoformat(),
               "short_history": obj.short_history}
        if obj.interval is not None:
            rec["interval"] = obj.interval.label
        return {**rec, **_quality(obj.quality.status, obj.quality)}
    if isinstance(obj, SwingLow):
        return {"date": obj.session.isoformat(), "low_price": _num(obj.low_price),
                "higher_than_previous_row_low": obj.higher_than_previous_row_low,
                "sessions_after_in_window": obj.sessions_after_in_window,
                "lowest_low_in_those_sessions": _num(obj.lowest_low_in_those_sessions),
                "undercut_by_later_session": obj.undercut_by_later_session}
    if isinstance(obj, SwingLows):
        through = obj.detectable_through
        rec = {"sessions_each_side_with_higher_lows": obj.each_side.value,
               "window_first_session": obj.window.start.isoformat(),
               "window_last_session": obj.window.end.isoformat(),
               "window_sessions": obj.window_sessions,
               "detectable_through": through.isoformat() if through else None,
               "detected": [to_json(r) for r in obj.detected],
               **_quality(obj.quality.status, obj.quality)}
        if obj.interval is None:
            return rec
        return {"candle_interval": obj.interval.label, **rec}
    raise TypeError(f"{type(obj).__name__} is not part of the output contract")


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
    """--store as given, never created here. A literal `${` is a skill variable Claude Code did not
    substitute, and a missing parent is most likely an empty one (bash turns ${CLAUDE_PROJECT_DIR}/
    data/market-data into /data/market-data): reading either as a path would turn a broken setup
    into an innocent store no_store. The store directory itself missing is a project without one."""
    if "${" in text:
        raise argparse.ArgumentTypeError(
            f"{text!r} holds a variable that was not substituted (literal '${{'); pass the "
            f"project's real path, e.g. --store /path/to/project/data/market-data")
    path = Path(text)
    if not path.parent.exists():
        raise argparse.ArgumentTypeError(
            f"parent directory '{path.parent}' does not exist; was ${{CLAUDE_PROJECT_DIR}} "
            f"substituted?")
    return path


def _count(cls, unit):
    """An argparse type for --atr / --swings: a whole number of at least 1, as `cls`, so a count
    that would print a negative ATR or crash the swing scan never gets past argv."""
    def parse(text: str):
        try:
            return cls(int(text))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{text!r} is not a whole number of {unit} of at least 1") from None
    return parse


def main(argv=None, *, source: QuoteSource | None = None, build=build_source,
         today: date | None = None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+", metavar="TICKER", help="broker tickers, e.g. PKN.PL ALE.PL")
    ap.add_argument("--interval", choices=("d", "w", "m"), default="d",
                    help="candle interval: d=daily (default), w=weekly, m=monthly")
    ap.add_argument("--bars", type=int, default=DEFAULT_BARS, metavar="N",
                    help=f"bars returned per symbol (default {DEFAULT_BARS})")
    ap.add_argument("--atr", type=_count(AtrPeriod, "candles"), nargs="?", const=ATR_DEFAULT_N,
                    default=None, metavar="N",
                    help=f"also report Wilder ATR(N) on the chosen interval (bare --atr = "
                         f"{ATR_DEFAULT_N}); widens the fetch to cover ATR's run-up, so the value "
                         f"never depends on --bars")
    ap.add_argument("--swings", type=_count(SessionsEachSide, "sessions each side"), nargs="?",
                    const=SWING_SESSIONS_DEFAULT, default=None, metavar="N",
                    help=f"also report confirmed swing lows on the chosen interval, N sessions each "
                         f"side (bare --swings = {SWING_SESSIONS_DEFAULT}); reads the same window as "
                         f"ATR, so both describe one stretch of history")
    ap.add_argument("--store", type=_store_dir, default=None, metavar="DIR",
                    help="this project's own candle store, one CSV per ISIN; asked before Yahoo")
    args = ap.parse_args(argv)

    index = SymbolIndex(SYMBOLS)
    interval = Interval(args.interval)
    end = today or date.today()
    # --bars <= 0 never failed and must not now: DateRange would reject an inverted range.
    days = min(max(calendar_days(interval, bars_needed(max(args.bars, 1), args.atr, args.swings)),
                   MIN_PERIOD_DAYS),
               MAX_PERIOD_DAYS)
    period = DateRange(end - timedelta(days=days), end)
    if source is None:
        source = build(store_dir=args.store)
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
                      **quote_record(list(series.bars), interval, args.bars, end, args.atr,
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
                     "aggregated from daily. A daily bar with trusted:false is one its source does "
                     "not vouch for (untrusted_reason says why); it is shown, not repaired. W1/MN "
                     "bars, last_closed, atr and swing_lows are read from trusted sessions only: "
                     "status good, uncertain (excluded_sessions names what was left out) or "
                     "no_value.",
        "quotes": quotes,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=to_json)
    print()


if __name__ == "__main__":
    main()
