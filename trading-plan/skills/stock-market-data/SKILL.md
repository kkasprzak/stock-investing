---
name: stock-market-data
description: Fetch fresh delayed daily / weekly / monthly (D1 / W1 / MN) OHLC candles, last closing prices, and Wilder ATR (average true range) for named stock-market instruments (GPW / XETRA / US), keyed by ISIN (a broker ticker is translated to its ISIN by the same skill). Use whenever a task needs current or recent market prices, closes, or candles for specific tickers — a morning runaway check, a daily-close D1 evaluation, a weekly D1/W1/MN portfolio or watchlist review, or any ad-hoc "what did X close at" lookup. Also the one place ATR and confirmed swing lows are computed: reach for it for an instrument's ATR, its normal daily range, how volatile it is, a stop distance expressed in ATR multiples, or the swing lows a trailing stop is anchored to — never derive either from candles yourself, or two callers will disagree on the same number. The market-data-acquisition layer; returns facts, not decisions. Also translates a broker's ticker to an ISIN and back — reach for it for "which ISIN is PKN.PL" or "what is this ISIN's ticker at the broker", never translate by hand.
user-invocable: false
---

# stock-market-data

The market-data-acquisition layer: fresh **delayed** D1 OHLC for named instruments. Reach for this
whenever a flow needs recent prices/candles for specific instruments. It returns facts (self-describing
JSON) — the caller judges. Backend is a chain of market-data sources asked in trust order; callers
depend on the output contract, not on which source answered.

## Run

```
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PLPKN0000018 LU2237380790 PLPKO0000016   # ISINs, daily
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PLPKN0000018 --interval w     # weekly (W1); m = monthly
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PLPKN0000018 --bars 10        # more history per instrument
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PLPKN0000018 --atr            # + Wilder ATR(14) on that interval (--atr 20 to override)
python3 ${CLAUDE_SKILL_DIR}/scripts/quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data PLPKN0000018 --swings         # + confirmed swing lows (2 sessions each side; --swings 3 to override)
```

Always pass `--store` exactly as above: it points at this project's own candle store (next section).
A value given to `--atr` or `--swings` must be a whole number of at least 1; anything else exits 2
before anything is fetched.

Input is **ISIN only**. A broker ticker from a state file is turned into its ISIN first with
`symbols.py --from xtb` (next section); you never pass a broker's or a provider's symbol. Each key
is checked as given (lower case or surrounding spaces are invalid, not corrected); one that is no
ISIN gets `ok:false`, `reason:"invalid_isin"` and the rest of the run goes on. A valid ISIN outside
the map is still answered by the store; Yahoo, which needs the map's symbol, reports `unmapped`.
`--interval` picks the candle: `d` daily (default), `w` weekly, `m` monthly
— W1/MN are aggregated from the daily series (open=period start, high/low=extremes, close=period end,
each over the period's trusted sessions), so they carry the same OHLCV and `complete`/`last_closed`
semantics as daily, plus a `status` instead of a `source` (Output contract).

There is no cache: every run asks its sources afresh, and what is worth keeping lives in the own
candle store.

## Instrument names (`scripts/symbols.py`)

Translates between an ISIN and the ticker a broker uses for it, on the same symbol map. Reach for it
when a flow holds one and needs the other: a state file row in broker tickers that should be asked
for by ISIN, or an ISIN (from index-membership sourcing, from the store) that has to be written down
as the broker's ticker. Never translate by hand, and never derive a ticker from a root or a suffix.
The direction is always named:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/symbols.py --from xtb PKN.PL ALE.PL    # broker tickers -> ISINs
python3 ${CLAUDE_SKILL_DIR}/scripts/symbols.py --to xtb PLPKN0000018       # ISINs -> broker tickers
```

JSON on stdout, one record per key under the text you passed; `found` is always there.

- `--from xtb`: `{"found": true, "isin": "PLPKN0000018", "name": "PKNORLEN"}`, or `{"found": false}`
  for a ticker the map does not know.
- `--to xtb`: `{"found": true, "xtb": "PKN.PL", "name": "PKNORLEN"}`. `"xtb": null` with
  `found: true` means the instrument is mapped but the broker does not offer it (ROBYG, REX): it
  cannot be traded there, so do not look for another ticker. `{"found": false}` is a valid ISIN
  outside the map; `{"found": false, "reason": "invalid_isin"}` is text that is no ISIN (checked
  as given: lower case or surrounding spaces are invalid, not corrected).

Namespaces are brokers' and exchanges' only, today `xtb`. A data vendor's symbol (`yahoo`) is not
offered: it belongs to that vendor's adapter.
`--from yahoo`, `--to yahoo` or an unknown namespace exits 2. Nothing is fetched.

## Own candle store (required per project)

The store is this project's own record of closed daily candles, one CSV file per ISIN, filled only
by import and asked before Yahoo, which only fills what the store lacks.

- **Every project that uses this skill has its own store**, under `data/market-data/` in that
  project's repository. There is no global store. The `Run` lines point at it.
- `unavailable: [{source: "store", reason: "no_store"}]` on every record means this project has no
  store yet: do the first import (below). Until then the bars come from Yahoo alone. `quotes.py`
  exiting 2 with "parent directory ... does not exist" means `--store` did not point into the
  project (an empty `${CLAUDE_PROJECT_DIR}` gives `/data/market-data`): fix the path, do not import.
- **Feeding it** — one export per instrument, named by its ISIN like `quotes.py` (it need not be in
  the map):

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/import_quotes.py --store ${CLAUDE_PROJECT_DIR}/data/market-data stooq <export.csv> --for PLPEKAO00016
  ```

  The export is Stooq's **daily** history with "pomijaj splity + dywidendy" (skip splits and
  dividends). Stooq's daily export lists closed sessions only: a day that has not closed is not in
  it, so every row is a complete candle and a row dated today is today's closed session, imported.
  History from 2022 is enough. The export's prices and volume carry noise of about
  1e-5 of each value, which the importer takes off; a value further off rejects the whole file
  (Stooq's history before ~2022 has more noise: export a shorter range). A row dated after today
  rejects the whole file.
- The importer prints a JSON report: `{isin, file, added, unchanged, changed, changed_dates[],
  imported: {first, last}}`. `changed` > 0 means sessions already in the store now
  read differently: check `changed_dates` and the `git diff` before keeping them. When `added` and
  `changed` are both 0 the importer writes nothing, so importing the same export again leaves the
  file as it was; the `--store` directory itself appears only with the first write, and only under
  a parent that already exists. Exit 1: the
  export was rejected (`line N: why` on stderr), is missing, or the store file is unreadable or
  malformed, or the store cannot be written (`--store` is a file, no write permission); the store
  file was not touched. Exit 2: bad arguments (including a missing `--store`, one still holding a
  literal `${`, or one whose parent directory does not exist), or a `--for` that is no ISIN;
  nothing is created.
- **Committing the store is the user's step**; the importer never runs git. The project's
  `.gitattributes` should carry `data/market-data/*.csv text eol=lf`.
- Consequences: with a store, a Yahoo outage still gives `ok:true` on the store's bars, and the
  outage shows in `unavailable`. Yahoo is split-adjusted and the "skip splits" export is not, so a
  split after the last import breaks continuity between store and Yahoo bars until the next import.

## Output contract

Self-describing JSON to stdout: a header `source` describing the chain that was asked — each
source's description, most trusted first, joined by ` > ` — and `quotes[<key you passed>]` with
`yahoo_symbol`, `resolved_by`, and either `ok:true` + `last_closed {date, c, status,
excluded_sessions}` + `bars[]`, or `ok:false` + `reason` + `unavailable` + `value:"[NO DATA]"`.

A daily bar in `bars[]` is `{date, o, h, l, c, v, complete, source, trusted}`, plus
`untrusted_reason` only when `trusted` is `false`. `source` is the name of the source that supplied
it: `store` (this project's own candle store) or `yahoo`. `trusted` says whether that source vouches
for the session: the store always does; Yahoo marks a **placeholder** (`o == h == l == c` and volume
0 or missing, a session it filled in rather than one that traded) `trusted:false`,
`untrusted_reason:"placeholder"`, and a session where it sent an open, high, low or close that is
no price (0, negative, not finite) `untrusted_reason:"unusable_price"`, with that field `null`; a
price Yahoo did not send at all is only a `null` on a trusted bar. Other reasons may follow. An
untrusted bar is shown as the source gave it, never repaired.
A weekly or monthly bar is `{date, o, h, l, c, v, complete, status, excluded_sessions}`, with no
`source`.

**Derived values** — W1/MN bars, `last_closed`, `atr`, `swing_lows` — follow one rule:
a value is computed from trusted sessions only and names the ones it had to leave out; how much
left out is too much is the consumer's call. Each carries both keys, always:

- `status`: `good` (nothing left out), `uncertain` (a real value, read without the sessions in
  `excluded_sessions`), or `no_value` — only on a W1/MN bar whose period has no trusted session:
  its `o/h/l/c/v` are `null` while it stays in the series with `complete` from the calendar.
- `excluded_sessions`: ISO dates of the closed untrusted sessions left out, oldest first; `[]` when
  `good`. On W1/MN that includes the closed untrusted sessions of the period still in progress:
  they ended after every reading's date. A forming untrusted bar is not a closed session: it adds
  no values to its period and is not named. A W1/MN period holding only that bar still appears, as
  a `no_value` candle with `o/h/l/c/v` `null`, `complete:false` and `excluded_sessions:[]`.

`unavailable: [{source, reason}]` lists the sources that did not answer (`store`, `yahoo`); an
`ok:true` record carries it only when some source did not answer. Yahoo's reasons: `unmapped` (the
map gives this ISIN no Yahoo symbol, so Yahoo was not asked), `not_found` (no such symbol),
`rate_limited` (still throttled after its retries), `network_error` (no
connection, a timeout), `bad_response` (an answer that is not a chart), `http_<code>` (any other
HTTP status), or Yahoo's own error code. Throttling, a network error and a bad response are retried;
the reason is the last attempt's.

`ok:false` when no source answered, and also when no bars came back while some source did not
answer. An `ok:false` record always carries the full `unavailable` list; `reason` is Yahoo's entry
there, else the first one's. The exception is `reason:"invalid_isin"`: it comes from the key, not
from a source, so no source was asked and `unavailable` is `[]`. A source that answered with
nothing is not a failure: no bars and no `unavailable` stays `ok:true`.

- `last_closed` = the most recent **completed**, trusted candle of the requested interval that has a
  close — the number to reason on. Read over the whole fetched series, not the `--bars` slice, so a
  short slice of placeholders still finds the last real session. Its `excluded_sessions` names the
  untrusted sessions closed after it (and, for a W1/MN candle, those left out of it); it is `null`
  only when no such candle exists.
- `atr` (only with `--atr`) = `{n, method, value, bars_used, as_of, short_history, interval, status,
  excluded_sessions}` — Wilder's ATR on the requested interval, the single definition every caller
  shares. Computed from **complete**, trusted candles (a W1/MN candle with `no_value` is skipped)
  over a fixed window of the last `5 x n + 1` such candles, so the same instrument reads the same
  ATR for a 6-bar morning check and a 200-bar sizing run, and an untrusted session inside the window
  pushes it one candle further back instead of entering it. `as_of` is the last candle used.
  `short_history:true` = fewer candles than that window: the value is still reported, but the
  recursion has not settled. Fewer than `n+1` usable candles → `atr: null`; that covers both a short
  history and a window where everything is untrusted, and the output does not tell them apart.
- `swing_lows` (only with `--swings`) = `{candle_interval, sessions_each_side_with_higher_lows,
  window_first_session, window_last_session, window_sessions, detectable_through, detected[], status,
  excluded_sessions}` — the
  confirmed swing lows of that window, the single definition every caller shares. Read from
  complete, trusted candles like ATR, but a candle needs only a low here (ATR needs high, low and
  close): an untrusted session is neither a candidate nor a neighbour, so it never confirms a low. No usable candle at all → `swing_lows: null`. A low counts when
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
- A price it can't read is `[NO DATA]`, never inferred. One bad key never fails the others.

## Gotchas

- **Trust the `complete` flag over the date.** It tracks the **venue's session**, not the calendar:
  today's bar is `complete:false` while that exchange is trading and flips to `true` once its regular
  session ends (close time read from the exchange's own calendar, so an evening GPW/XETRA run gets
  today's D1 as a fact while a US name is still forming). Same rule for W1/MN — a week closes on
  Friday evening. Use `last_closed`, or filter daily bars on `complete:true` **and**
  `trusted:true`; never decide on a forming bar. `complete` stays honest about the calendar, so a
  placeholder is `complete:true` and stays in `bars[]` with its made-up OHLC: `complete` alone does
  not filter it out.
  If the provider omits the session calendar, the flag stays conservative (`false`) rather than guess.
- **A closed W1/MN candle can have `o/h/l/c/v: null`.** That is `status:"no_value"`: none of the
  period's sessions was trusted (a week of placeholders), and `excluded_sessions` lists them all.
  The candle stays in the series rather than leaving a silent hole; `atr`, `swing_lows` and
  `last_closed` skip it and name its sessions.
- **A day without trades on an illiquid instrument looks like a placeholder** (ETFs, small caps:
  one price all day, no volume) and is left out the same way, so ATR reads slightly higher than
  through 0.5.0, and an instrument without a store can stay `uncertain` for good. The cure is
  importing it into the store, whose sessions are always trusted. The same holds for Yahoo's GPW
  history: it carries flat zero-volume bars on exchange holidays (seen 2017–2020, e.g. 2020-11-11),
  so an MN reading whose window reaches back that far is `uncertain` and names those dates (a
  store whose history starts later does not cover them), while
  the value itself as a rule does not move (such a bar sits at the previous close, almost always
  inside its month's range).
- **A session the source does not return at all is not named.** `excluded_sessions` lists the
  sessions a source served and did not vouch for; a session missing from the answer has no bar to
  judge, so it shows only as a gap in the dates.
- **An ex-date inside the ATR window inflates ATR.** Candles are unadjusted, so a dividend gap enters
  True Range as volatility that never happened. This layer has no event calendar — the caller holding
  ex-dates checks whether one falls in the last `5 x n + 1` sessions.
- **An ex-date can also mint a swing low.** The same unadjusted gap drops the low of the ex-day and
  the sessions around it, so `swing_lows` can report structure that is a dividend, not a defended
  level — and it looks identical to a real one. Same division of labour as ATR: this layer has no
  event calendar, so the caller holding ex-dates decides whether a low near one still counts.
- **Prices are unadjusted (actual traded).** Around an ex-dividend, pre-ex-date bars will **not**
  match dividend-back-adjusted series — that is intended, don't try to reconcile it. A total-return
  (adjusted) series is available from the provider if ever needed.
- **The latest session's close trails `null`** in the provider's raw array until it backfills; the
  script patches it from the official close (so `last_closed` is right same-day). Relevant only if
  you ever read the provider directly instead of through this script.

## Symbol map (`scripts/symbols.json`)

The single shared symbol map for every quote script, self-contained. Keyed by **ISIN** (durable
across renames); each entry's `symbols` maps a source name (`xtb`, `yahoo`, …) to that source's
ticker. `quotes.py` is asked by ISIN and takes `symbols.yahoo` from that entry. `symbols.py` reads the
same map; a symbol given to two ISINs within one namespace is a map error, and every script that
reads the map refuses to start on it.

Upkeep:
- **Add a watched instrument** — one entry: its ISIN → `{name, symbols:{xtb, yahoo}}`. Verify the
  provider symbol live before trusting it.
- **Add another data provider later** — an adapter implementing the `QuoteSource` port
  (`scripts/market_data/ports.py`), placed in the chain in `quotes.py`, plus its symbol under
  `symbols` (e.g. `"eodhd": "PKN.WAR"`). A `symbols` entry alone fetches nothing.
- **A ticker breaks after a rename** — the ISIN is stable; re-resolve that source's symbol via the
  source's own search (for Yahoo: `v1/finance/search?q=<ISIN>`) and update `symbols`. Nothing
  derives one source's symbol from another's: a rename can move the provider symbol off the broker
  root.
