# Tests — stock-market-data

Deterministic, offline regression tests for `scripts/quotes.py` and the `scripts/market_data/`
package behind it. Stdlib `unittest`, no dependencies.

```
make test                                                                          # from the repo root, every skill's tests
python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests        # offline
RUN_LIVE_SMOKE=1 python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests   # + live Yahoo
```

## Files

One test file per module of `scripts/`, plus shared support:

```
support.py              frozen clock (FROZEN_TODAY, FROZEN_NOW, GPW_CLOSE, warsaw()), TOL, fixture
                        loaders (load_yahoo, load_stooq), DIVIDEND_WEEKS, pipeline(); puts ../scripts on sys.path
test_model.py           market_data/model.py — DateRange, Interval, Instrument, Isin, Price, Volume, DailyQuote
test_store_file.py      market_data/store_file.py — the store's file schema, StoredQuote, to_bar
test_indicators.py      market_data/indicators.py — _period, aggregate, last_closed, ATR, swing lows, Stooq oracle
test_quote_chain.py     market_data/quote_chain.py — QuoteChain: trust order, gap filling, sources that did not answer
test_yahoo.py           market_data/adapters/yahoo.py — resolve, range buckets, cache, session close, backfill, live smoke
test_symbol_index.py    market_data/adapters/symbol_index.py — lookup by ISIN / broker ticker, broker symbol
test_cli.py             scripts/quotes.py — build_source (the composition root) and main() over an injected source
fixtures/               captured Yahoo responses and the Stooq CSVs the golden values come from;
                        stooq_*_raw.csv are unedited Stooq exports, fixtures/store/ holds files in
                        the store's own schema
```

Every test file imports `support` (`import support` or `from support import ...`) before anything
from `scripts/`: that import puts `../scripts` on `sys.path`, so the file can then `import quotes`
and `import market_data...`. The module is named `support`, not
`fixtures`, because `fixtures/` is the directory of captured vendor responses.

No mocks. Whatever a test needs to replace is a seam the code already offers: a source is a fake
class implementing the `QuoteSource` port (`test_quote_chain.py`, `test_cli.py`), and the adapter
takes its `fetch` and `sleep` as constructor arguments, so `test_yahoo.py` hands it fixtures and a
no-op or recording sleep. `main(argv, source)` and `build_source(cache, cache_dir=..., fetch=...,
sleep=...)` take the same injections, so the CLI is tested without the network and without touching the real cache.

## How it stays deterministic

The pipeline depends on live Yahoo and the wall clock (the `complete` flag). Both are frozen:
- **Yahoo** → captured raw responses in `fixtures/yahoo_*.json` (trimmed ~7 months).
- **clock** → `FROZEN_TODAY = 2026-07-25` / `FROZEN_NOW` injected into `build_daily`/`aggregate`;
  session-boundary cases build their own epochs with `warsaw(...)`.

Expected OHLC is anchored to `fixtures/stooq_*.csv` — the independent source (Stooq) we cross-checked
by hand for PKN, KGH, LPP across D1/W1/MN. That manual verification is the provenance of the golden
values; the tests re-assert them on every run.

## Layers

- **Unit** — `resolve` (`test_yahoo.py`), `_period`, `aggregate`, `last_closed`
  (`test_indicators.py`), `build_daily` null-close backfill (`test_yahoo.py`), the value objects
  (`test_model.py`) and symbol lookup (`test_symbol_index.py`).
- **Stooq oracle** (`TestStooqOracle`) — pipeline vs Stooq, to the grosz, over the hand-verified
  recent window per interval. Low/Close always match; the two ex-dividend weeks (PKN 2026-06-15,
  KGH 2026-06-22) keep our unadjusted Open/High while Stooq back-adjusts — asserted explicitly, not
  skipped.
- **Completeness / last_closed** — flags relative to `FROZEN_TODAY` (July month still forming; the
  just-closed week complete on a Saturday).
- **Session close** (`TestSessionClose`) — the flag follows the venue's session, not the date: today's
  bar forming during the session, complete after the close and all evening, conservative when the
  vendor omits the trading period, market tz beating machine tz. On the cache side: an entry written
  before the close is refetched after it, one written after the close is reused, and a hit is
  re-stamped against the read clock (an evening entry whose bar was stored as forming comes back
  closed once the market's date has moved on). Weekly/monthly counterparts live in `TestAggregate`.
- **ATR** (`TestATR`) — the number two risk skills must agree on, pinned from three sides: arithmetic
  hand-computable at `n=2` (including the `|prevC - L|` branch), independence from `--bars` in both
  directions (a short slice cannot starve it, a wide fetch cannot shift it), and a regression golden at
  `n=14`. The `n=14` value is a **regression pin**, not an independently verified one — the Stooq CSVs
  are ~16 rows, too short for a 14-period run-up; correctness of the arithmetic rides on the `n=2` test.
- **Port contract** — `TestQuoteChain`: a higher source wins a shared date and a lower one fills the
  gaps, a source that raises lands in `unavailable`, all of them raising is an error, an empty answer
  is not; `TestDaily`: Yahoo labels every bar with its `source` and raises when it did not answer.
- **CLI** (`test_cli.py`) — `build_source` without a cache writes nothing, with one writes one
  file; the `ok:true` / `ok:false` records, and `--bars` edge values that must not crash. Not
  covered: `main()` turning the `--cache` flag into `build_source(cache=True)` (every `main()` test
  injects its source); that wiring was checked live only.
- **Live smoke** (opt-in, `RUN_LIVE_SMOKE=1`) — hits Yahoo to catch API/shape drift the fixtures
  can't see until re-captured.

Out of scope on purpose: deep history. The trimmed fixture starts mid-period (oldest week/month is
partial) and old bars reintroduce every past corporate action, which we did not verify by hand.

## Updating fixtures

When Yahoo's format or the mapping changes, re-capture: fetch `range=1y&interval=1d` for each ticker,
keep the last ~150 bars + `meta` (`gmtoffset`, `regularMarketPrice`, `regularMarketTime`,
`currentTradingPeriod`), and re-trim
the Stooq CSVs to their last ~16 rows. Then re-pin `FROZEN_TODAY` and refresh the expected values.
