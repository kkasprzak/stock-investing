# Tests — stock-market-data

Deterministic, offline regression tests for `scripts/quotes.py`. Stdlib `unittest`, no dependencies.

```
python3 -m unittest discover -s .claude/skills/stock-market-data/tests        # offline (~0.02s)
RUN_LIVE_SMOKE=1 python3 -m unittest discover -s .claude/skills/stock-market-data/tests   # + live Yahoo
```

## How it stays deterministic

The pipeline depends on live Yahoo and the wall clock (the `complete` flag). Both are frozen:
- **Yahoo** → captured raw responses in `fixtures/yahoo_*.json` (trimmed ~7 months).
- **clock** → `FROZEN_TODAY = 2026-07-25` / `FROZEN_NOW` injected into `build_daily`/`aggregate`;
  session-boundary cases build their own epochs with `warsaw(...)`.

Expected OHLC is anchored to `fixtures/stooq_*.csv` — the independent source (Stooq) we cross-checked
by hand for PKN, KGH, LPP across D1/W1/MN. That manual verification is the provenance of the golden
values; the tests re-assert them on every run.

## Layers

- **Unit** — `resolve`, `_period`, `aggregate`, `last_closed`, `build_daily` (null-close backfill).
- **Stooq oracle** — pipeline vs Stooq, to the grosz, over the hand-verified recent window per
  interval. Low/Close always match; the two ex-dividend weeks (PKN 2026-06-15, KGH 2026-06-22) keep
  our unadjusted Open/High while Stooq back-adjusts — asserted explicitly, not skipped.
- **Completeness / last_closed** — flags relative to `FROZEN_TODAY` (July month still forming; the
  just-closed week complete on a Saturday).
- **Session close** (`TestSessionClose`) — the flag follows the venue's session, not the date: today's
  bar forming during the session, complete after the close and all evening, conservative when the
  vendor omits the trading period, market tz beating machine tz, and a same-day cache hit re-stamped
  after the close. Weekly/monthly counterparts live in `TestAggregate`.
- **ATR** (`TestATR`) — the number two risk skills must agree on, pinned from three sides: arithmetic
  hand-computable at `n=2` (including the `|prevC - L|` branch), independence from `--bars` in both
  directions (a short slice cannot starve it, a wide fetch cannot shift it), and a regression golden at
  `n=14`. The `n=14` value is a **regression pin**, not an independently verified one — the Stooq CSVs
  are ~16 rows, too short for a 14-period run-up; correctness of the arithmetic rides on the `n=2` test.
- **Live smoke** (opt-in, `RUN_LIVE_SMOKE=1`) — hits Yahoo to catch API/shape drift the fixtures
  can't see until re-captured.

Out of scope on purpose: deep history. The trimmed fixture starts mid-period (oldest week/month is
partial) and old bars reintroduce every past corporate action, which we did not verify by hand.

## Updating fixtures

When Yahoo's format or the mapping changes, re-capture: fetch `range=1y&interval=1d` for each ticker,
keep the last ~150 bars + `meta` (`gmtoffset`, `regularMarketPrice`, `regularMarketTime`,
`currentTradingPeriod`), and re-trim
the Stooq CSVs to their last ~16 rows. Then re-pin `FROZEN_TODAY` and refresh the expected values.
