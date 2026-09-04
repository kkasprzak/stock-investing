---
name: stock-market-data
description: Fetch fresh delayed daily / weekly / monthly (D1 / W1 / MN) OHLC candles, last closing prices, and Wilder ATR (average true range) for named stock-market instruments (GPW / XETRA / US), keyed by broker ticker via a shared ISIN-backed symbol map. Use whenever a task needs current or recent market prices, closes, or candles for specific tickers — a morning runaway check, a daily-close D1 evaluation, a weekly D1/W1/MN portfolio or watchlist review, or any ad-hoc "what did X close at" lookup. Also the one place ATR is computed: reach for it for an instrument's ATR, its normal daily range, how volatile it is, or a stop distance expressed in ATR multiples — never derive ATR from candles yourself, or two callers will disagree on the same number. The market-data-acquisition layer; returns facts, not decisions.
user-invocable: false
---

# stock-market-data

The market-data-acquisition layer: fresh **delayed** D1 OHLC for named instruments. Reach for this
whenever a flow needs recent prices/candles for specific tickers. It returns facts (self-describing
JSON) — the caller judges. Backend is a market-data provider (currently Yahoo); callers depend on the
output contract, not the provider.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stock-market-data/scripts/quotes.py PKN.PL ALE.PL PKO.PL ETFBM40TR.PL  # broker tickers, daily
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stock-market-data/scripts/quotes.py PKN.PL --interval w                # weekly (W1); m = monthly
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stock-market-data/scripts/quotes.py PKN.PL --bars 10                   # more history per symbol
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stock-market-data/scripts/quotes.py PKN.PL --cache                     # reuse today's closed candles (skip the fetch)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/stock-market-data/scripts/quotes.py PKN.PL --atr                       # + Wilder ATR(14) on that interval (--atr 20 to override)
```

Input is **broker tickers** (`.PL` / `.DE` / `.US`) — the same symbols the state files use — or an
**ISIN** (resolved via the same map; handy for index-membership callers). You never pass
provider-specific symbols. `--interval` picks the candle: `d` daily (default), `w` weekly, `m` monthly
— W1/MN are aggregated from the daily series (open=period start, high/low=extremes, close=period end),
so they carry the same fields and `complete`/`last_closed` semantics as daily.

`--cache` reuses the same market day's closed candles from a local cache instead of fetching; reach
for it when a run re-reads closed candles, and omit it when the moment needs live data — your call
from the context, not a fixed rule. Default is always-live. An entry is scoped to the session state it
was written in: **crossing that venue's close invalidates it**, so a series cached mid-session is
never served afterwards as the day's closed candle. Within an open session a cached forming bar can
still be stale by construction — that bar is `complete:false`, so never decide on it.

## Output contract

Self-describing JSON to stdout: `quotes[<broker ticker>]` with `yahoo_symbol`, `resolved_by`, and
either `ok:true` + `last_closed {date,c}` + `bars[]`, or `ok:false` + `reason` + `value:"[NO DATA]"`.

- `last_closed` = the most recent **completed** D1 candle — the number to reason on.
- `atr` (only with `--atr`) = `{n, method, interval, value, bars_used, as_of, short_history}` — Wilder's
  ATR on the requested interval, the single definition every caller shares. Computed from **complete**
  candles over a fixed window (`5 x n + 1`), so the same instrument reads the same ATR for a 6-bar
  morning check and a 200-bar sizing run. `short_history:true` = fewer candles than that window: the
  value is still reported, but the recursion has not settled. Too few for `n+1` TRs → `atr: null`.
- Data is **delayed (~15 min)** — recent, not real-time.
- A price it can't read is `[NO DATA]`, never inferred. One bad ticker never fails the others.

## Gotchas

- **Trust the `complete` flag over the date.** It tracks the **venue's session**, not the calendar:
  today's bar is `complete:false` while that exchange is trading and flips to `true` once its regular
  session ends (close time read from the exchange's own calendar, so an evening GPW/XETRA run gets
  today's D1 as a fact while a US name is still forming). Same rule for W1/MN — a week closes on
  Friday evening. Use `last_closed`, or filter `complete:true`; never decide on a forming bar.
  If the provider omits the session calendar, the flag stays conservative (`false`) rather than guess.
- **An ex-date inside the ATR window inflates ATR.** Candles are unadjusted, so a dividend gap enters
  True Range as volatility that never happened. This layer has no event calendar — the caller holding
  ex-dates checks whether one falls in the last `5 x n + 1` sessions.
- **`resolved_by:"suffix_guess"` is unverified.** The ticker wasn't in the map and was resolved by a
  blind `.PL→.WA` swap. After a rename this can point at the wrong or a non-existent symbol (the
  provider ticker can move off the broker root) → wrong data or `[NO DATA]`. Add it to the map.
- **Prices are unadjusted (actual traded).** Around an ex-dividend, pre-ex-date bars will **not**
  match dividend-back-adjusted series — that is intended, don't try to reconcile it. A total-return
  (adjusted) series is available from the provider if ever needed.
- **The latest session's close trails `null`** in the provider's raw array until it backfills; the
  script patches it from the official close (so `last_closed` is right same-day). Relevant only if
  you ever read the provider directly instead of through this script.

## Symbol map (`scripts/symbols.json`)

The single shared symbol map for every quote script, self-contained. Keyed by **ISIN** (durable
across renames); each entry's `symbols` maps a source name (`xtb`, `yahoo`, …) to that source's
ticker. Runtime resolves an input `xtb` ticker → entry → `symbols.yahoo`.

Upkeep:
- **Add a watched instrument** — one entry: its ISIN → `{name, symbols:{xtb, yahoo}}`. Verify the
  provider symbol live before trusting it.
- **Add another data provider / broker later** — add its symbol under `symbols` (e.g.
  `"eodhd": "PKN.WAR"`). Data-only; no code change.
- **A ticker breaks after a rename** — the ISIN is stable; re-resolve that source's symbol via the
  source's own search (for Yahoo: `v1/finance/search?q=<ISIN>`) and update `symbols`. This is why
  blind suffix-swap is unsafe (a rename can move the provider symbol off the broker root).
