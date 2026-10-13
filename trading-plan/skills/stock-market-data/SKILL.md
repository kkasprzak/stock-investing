---
name: stock-market-data
description: Fetch fresh delayed daily / weekly / monthly (D1 / W1 / MN) OHLC candles, last closing prices, and Wilder ATR (average true range) for named stock-market instruments (GPW / XETRA / US), keyed by broker ticker via a shared ISIN-backed symbol map. Use whenever a task needs current or recent market prices, closes, or candles for specific tickers — a morning runaway check, a daily-close D1 evaluation, a weekly D1/W1/MN portfolio or watchlist review, or any ad-hoc "what did X close at" lookup. Also the one place ATR and confirmed swing lows are computed: reach for it for an instrument's ATR, its normal daily range, how volatile it is, a stop distance expressed in ATR multiples, or the swing lows a trailing stop is anchored to — never derive either from candles yourself, or two callers will disagree on the same number. The market-data-acquisition layer; returns facts, not decisions.
user-invocable: false
---

# stock-market-data

The market-data-acquisition layer: fresh **delayed** D1 OHLC for named instruments. Reach for this
whenever a flow needs recent prices/candles for specific tickers. It returns facts (self-describing
JSON) — the caller judges. Backend is a chain of market-data sources asked in trust order; callers
depend on the output contract, not on which source answered.

## Run

```
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL ALE.PL PKO.PL ETFBM40TR.PL   # broker tickers, daily
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL --interval w                 # weekly (W1); m = monthly
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL --bars 10                    # more history per symbol
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL --cache                      # reuse today's closed candles (skip the fetch)
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL --atr                        # + Wilder ATR(14) on that interval (--atr 20 to override)
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PKN.PL --swings                     # + confirmed swing lows (2 sessions each side; --swings 3 to override)
```

Always pass `--store` exactly as above: it points at this project's own candle store (next section).

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

## Own candle store (required per project)

The store is this project's own record of closed daily candles, one CSV file per ISIN, filled only
by import and asked before Yahoo, which only fills what the store lacks
([ADR 0000](https://github.com/kkasprzak/stock-investing/blob/main/docs/adr/0000-own-candle-store-is-the-most-trusted-source-of-market-data.md),
[ADR 0001](https://github.com/kkasprzak/stock-investing/blob/main/docs/adr/0001-candle-store-is-one-csv-file-per-isin-versioned-in-the-consumers-repository.md)).

- **Every project that uses this skill has its own store**, under `data/market-data/` in that
  project's repository. There is no global store. The `Run` lines point at it.
- `unavailable: [{source: "store", reason: "no_store"}]` on every record means this project has no
  store yet: do the first import (below). Until then the bars come from Yahoo alone. `quotes.py`
  exiting 2 with "parent directory ... does not exist" means `--store` did not point into the
  project (an empty `${CLAUDE_PROJECT_DIR}` gives `/data/market-data`): fix the path, do not import.
- **Feeding it** — one export per instrument, keyed the same way as `quotes.py`:

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/import_quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data stooq <export.csv> --for PEO.PL
  ```

  The export is Stooq's **daily** history with "pomijaj splity + dywidendy" (skip splits and
  dividends). Stooq's daily export lists closed sessions only: a day that has not closed is not in
  it, so every row is a complete candle and a row dated today is today's closed session, imported.
  History from 2022 is enough. The export's prices and volume carry noise of about
  1e-5 of each value, which the importer takes off; a value further off rejects the whole file
  (Stooq's history before ~2022 has more noise: export a shorter range). A row dated after today
  rejects the whole file.
- The importer prints a JSON report: `{isin, key, file, added, unchanged, changed, changed_dates[],
  imported: {first, last}}`. `changed` > 0 means sessions already in the store now
  read differently: check `changed_dates` and the `git diff` before keeping them. When `added` and
  `changed` are both 0 the importer writes nothing, so importing the same export again leaves the
  file as it was; the `--store` directory itself appears only with the first write, and only under
  a parent that already exists. Exit 1: the
  export was rejected (`line N: why` on stderr), is missing, or the store file is unreadable or
  malformed, or the store cannot be written (`--store` is a file, no write permission); the store
  file was not touched. Exit 2: bad arguments (including a missing `--store`, one still holding a
  literal `${`, or one whose parent directory does not exist), or a ticker with no ISIN in the map;
  nothing is created.
- **Committing the store is the user's step**; the importer never runs git. The project's
  `.gitattributes` should carry `data/market-data/*.csv text eol=lf`.
- Consequences: with a store, a Yahoo outage still gives `ok:true` on the store's bars, and the
  outage shows in `unavailable`. Yahoo is split-adjusted and the "skip splits" export is not, so a
  split after the last import breaks continuity between store and Yahoo bars until the next import.

## Output contract

Self-describing JSON to stdout: a header `source` describing the chain that was asked — each
source's description, most trusted first, joined by ` > ` — and `quotes[<key you passed>]` with
`yahoo_symbol`, `xtb`, `resolved_by`, and either `ok:true` + `last_closed {date,c}` + `bars[]`, or
`ok:false` + `reason` + `unavailable` + `value:"[NO DATA]"`.

Every daily bar in `bars[]` carries `source`, the name of the source that supplied it: `store` (this
project's own candle store) or `yahoo`; weekly and monthly bars do not. `unavailable:
[{source, reason}]` lists the sources that did not answer (`store`, `yahoo`); an `ok:true` record
carries it only when some source did not answer.

`ok:false` when no source answered, and also when no bars came back while some source did not
answer. An `ok:false` record always carries the full `unavailable` list; `reason` is Yahoo's entry
there, else the first one's. A source that answered with nothing is not a failure: no bars and no
`unavailable` stays `ok:true`.

- `xtb` = the **execution-venue ticker** for this instrument, or `null` when the map has none.
  Reach for it when you keyed by ISIN and need the symbol a state file names. Never guessed: `null`
  means the broker does not list it, so confirm there rather than inferring from the GPW root.
- `last_closed` = the most recent **completed** D1 candle — the number to reason on.
- `atr` (only with `--atr`) = `{n, method, interval, value, bars_used, as_of, short_history}` — Wilder's
  ATR on the requested interval, the single definition every caller shares. Computed from **complete**
  candles over a fixed window (`5 x n + 1`), so the same instrument reads the same ATR for a 6-bar
  morning check and a 200-bar sizing run. `short_history:true` = fewer candles than that window: the
  value is still reported, but the recursion has not settled. Too few for `n+1` TRs → `atr: null`.
- `swing_lows` (only with `--swings`) = `{candle_interval, sessions_each_side_with_higher_lows,
  window_first_session, window_last_session, window_sessions, detectable_through, detected[]}` — the
  confirmed swing lows of that window, the single definition every caller shares. A low counts when
  the N sessions before **and** after it all traded higher, so it cannot be read until N sessions
  have closed after it: `detectable_through` is that edge, N sessions behind `window_last_session`.
  Same window as ATR (`5 x n + 1`), so a stop distance in ATR multiples and the structure it is
  measured against describe one stretch of history. Each row of `detected` (oldest first) carries
  `{date, low_price, higher_than_previous_row_low, sessions_after_in_window,
  lowest_low_in_those_sessions, undercut_by_later_session}`; `undercut` is a strict `<`, so an exact
  retest is not one, and `higher_than_previous_row_low` is `null` on the first row (no predecessor),
  never `false`. **Every** confirmed low is reported, lower ones included — which one a stop may
  anchor to is the caller's rule, not this layer's. No pivot in the window → `detected: []`.
- Bars with `source: "yahoo"` are **delayed (~15 min)** — recent, not real-time. Bars with
  `source: "store"` are closed sessions as of the last import.
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
- **An ex-date can also mint a swing low.** The same unadjusted gap drops the low of the ex-day and
  the sessions around it, so `swing_lows` can report structure that is a dividend, not a defended
  level — and it looks identical to a real one. Same division of labour as ATR: this layer has no
  event calendar, so the caller holding ex-dates decides whether a low near one still counts.
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
- **Add another data provider later** — an adapter implementing the `QuoteSource` port
  (`scripts/market_data/ports.py`), placed in the chain in `quotes.py`, plus its symbol under
  `symbols` (e.g. `"eodhd": "PKN.WAR"`). A `symbols` entry alone fetches nothing.
- **A ticker breaks after a rename** — the ISIN is stable; re-resolve that source's symbol via the
  source's own search (for Yahoo: `v1/finance/search?q=<ISIN>`) and update `symbols`. This is why
  blind suffix-swap is unsafe (a rename can move the provider symbol off the broker root).
