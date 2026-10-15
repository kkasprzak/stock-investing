# Tests — stock-market-data

Deterministic, offline regression tests for `scripts/quotes.py` (read side), `scripts/import_quotes.py`
(write side, the own candle store), `scripts/symbols.py` (instrument names) and the
`scripts/market_data/` package behind them. Stdlib `unittest`, no dependencies.

```
make test                                                                          # from the repo root, every skill's tests
python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests        # offline
RUN_LIVE_SMOKE=1 python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests   # + live Yahoo
```

## Files

One test file per module of `scripts/`, plus shared support:

```
support.py              frozen clock (FROZEN_TODAY, FROZEN_DATE, FROZEN_NOW, GPW_CLOSE, warsaw()), TOL,
                        fixture loaders (load_yahoo, load_stooq), DIVIDEND_WEEKS, pipeline() (DailyBar
                        or PeriodBar), bar builders (daily_bar: a DailyBar from plain numbers, trusted
                        unless trust= says otherwise; flat_bar; price: a Price; num: a Price as the
                        float the output prints), FakeSource; puts ../scripts on sys.path
test_model.py           market_data/model.py — DateRange, Interval, PeriodInterval (its periods), AtrPeriod and
                        SessionsEachSide, Instrument, Isin, Price, Volume, DailyQuote, Trust, Status,
                        Quality, DailyBar, PeriodBar (and each as the Candle the readings see)
test_store_file.py      market_data/store_file.py — the store's file schema: read, write, merge, StoredQuote
test_store.py           market_data/adapters/store.py — StoreQuotes: what the store answers (every bar trusted),
                        no_store, malformed, the store ahead of a lower source in a chain
test_import_stooq.py    market_data/importers/stooq.py and scripts/import_quotes.py — parse, snap, the real-export
                        guards and ATR pins, the importer end to end on a temp store, its usage errors
test_indicators.py      market_data/indicators.py — aggregate, last_closed, ATR, swing lows (the readings' derived
                        fields and the counts they refuse), the quality every reading carries,
                        placeholder sessions (ADR 0002), Stooq oracle
test_quote_chain.py     market_data/quote_chain.py — QuoteChain: trust order, gap filling, sources that did not answer
test_yahoo.py           market_data/adapters/yahoo.py — resolve (the map's symbol or none; no symbol is
                        unmapped, with no request and no pause), range buckets, session close, backfill,
                        to_bar (row to DailyBar, an unusable price to a gap on an untrusted bar), the
                        placeholder rule, fetch_chart (the symbol escaped into the URL, retries and
                        their pauses, the last attempt's reason), live smoke
test_symbol_index.py    market_data/adapters/symbol_index.py — lookup by ISIN (one outside the map: no symbols),
                        find (a namespace's symbol back to its ISIN), name, every map entry indexed,
                        a bad ISIN or a symbol twice in one namespace fails construction
test_symbols.py         scripts/symbols.py — --from xtb and --to xtb, found / not found, a mapped ISIN
                        the broker does not offer (xtb null), invalid_isin, mixed keys in one call,
                        yahoo or an unknown namespace exits 2
test_cli.py             scripts/quotes.py — build_source (the composition root), main() over an injected source,
                        flags reaching build, --atr/--swings counts below 1 rejected, ISIN-only input
                        (invalid_isin, unmapped), to_json, the output pins (continuity with 0.6.0,
                        0.7.0 byte for byte), placeholder sessions end to end
fixtures/               see below
```

### Fixtures

```
yahoo_{PKN,KGH,LPP}.json        captured Yahoo chart responses (trimmed ~7 months)
stooq_{pkn,kgh,lpp}_{d,w,m}.csv Stooq's default export (dividend-adjusted), last ~16 rows: the hand-verified
                                golden OHLC for the Stooq oracle, and the importer's format cases
                                (stooq_pkn_d.csv parses; stooq_lpp_m.csv has a weekend session: rejected).
                                Good for the format, not for the store's truth.
stooq_peo_d_raw.csv             Karol's export with "skip splits + dividends", PEO 2022-01-03..2026-10-09, 1195
                                sessions (cut from the full history since 1998, whose volume noise is beyond
                                the snap radius); the snap-radius guard and the ATR pin 7.52
stooq_lpp_d_raw.csv             same kind of export, LPP 2022-01-03..2026-10-12, 1196 sessions, CRLF, rows byte
                                for byte (cut from the full history since 2001, rejected the same way): five-
                                digit prices with noise in the tenths (17250.135879362) and fractional volume,
                                all within the relative radius; the guard that both snap and land on 0-1 places
stooq_ale_d_raw.csv             same kind of export, ALE 2026-05-04..2026-10-09, 114 sessions; ATR regression pin
stooq_peo_w_raw.csv             same kind of export, weekly (41 weeks dated on Sundays): must be rejected
store/PLPKN0000018.csv          hand-written, in the store's own schema (LF): 2026-10-02 and 10-05..10-09, round numbers
cli_0_4_0_PKN.json              the output of plugin 0.4.0 (commit 2589785) for `PKN.PL --atr --swings` on
                                yahoo_PKN.json, minus `generated`; read only for its header's `source`
                                (test_yahoo.py)
cli_0_6_0_PKN.json              the output of plugin 0.6.0 for the same arguments on the same fixture, minus
                                `generated`; never edited: minus `xtb` and keyed by the ISIN it is what
                                0.7.0 prints (the continuity test)
cli_0_7_0_PLPKN0000018.json     the output of plugin 0.7.0 for `PLPKN0000018 --atr --swings` on the same
                                fixture, minus `generated`: without a store the output must not change,
                                byte for byte
```

No fixture holds the October placeholders. `TestPlaceholderSessionsEndToEnd` (`test_cli.py`) builds
its Yahoo response by hand, modelled on what Yahoo served in October 2026: real sessions
09-01..10-02 with moving prices, then 10-05..10-09 as placeholders (all four prices at the 10-02
close, volume 0), plus a temp store holding the real sessions up to 10-02. `store/PLPKN0000018.csv`
does not fit, because it holds 10-05..10-09 itself and would hide the gap. The indicator-level
scenario (`TestPlaceholderSessions`) instead turns the last five sessions of `yahoo_PKN.json`
(07-20..07-24) into placeholders at the 07-17 close.

Every Stooq CSV, the `_raw` exports included, is committed as Stooq serves it: CRLF, Polish header,
no BOM. The parser reads it with `newline=""`, so CRLF and LF both pass; the inline exports in
`test_import_stooq.py` cover LF and the English header. Only the store's own files are LF by
contract.

Every test file imports `support` (`import support` or `from support import ...`) before anything
from `scripts/`: that import puts `../scripts` on `sys.path`, so the file can then `import quotes`
and `import market_data...`. The module is named `support`, not
`fixtures`, because `fixtures/` is the directory of captured vendor responses.

No mocks. Whatever a test needs to replace is a seam the code already offers: a source is a fake
class implementing the `QuoteSource` port — `support.FakeSource` (one fixed answer or one fixed
error, recording what it was asked; used by `test_cli.py` and `test_store.py`), and `ChainFake`,
local to `test_quote_chain.py`, for the chain's own cases. The Yahoo adapter takes its `fetch`,
`opener` and `sleep` as constructor arguments, so `test_yahoo.py` hands it fixtures and a no-op or
recording sleep; `fetch_chart` itself takes the `opener` in place of `urlopen`, so its tests script
bodies, HTTP errors and timeouts without the network and without really pausing.
`quotes.main(argv, source=, build=, today=)` and `build_source(store_dir=..., fetch=..., opener=...,
sleep=...)` take the same injections, so the CLI is tested without the network. The store is a
directory on disk: the
`fixtures/store/` directory, or a temp one; `import_quotes.main(argv, today=)` takes the date, so
"no session after today" does not follow the clock.

## How it stays deterministic

The pipeline depends on live Yahoo and the wall clock (the `complete` flag). Both are frozen:
- **Yahoo** → captured raw responses in `fixtures/yahoo_*.json` (trimmed ~7 months).
- **clock** → `FROZEN_TODAY = 2026-07-25` / `FROZEN_NOW` injected into `build_daily`, `FROZEN_DATE`
  (the same day as a date) into `aggregate`;
  session-boundary cases build their own epochs with `warsaw(...)`.

Expected OHLC is anchored to `fixtures/stooq_{pkn,kgh,lpp}_*.csv` — the independent source (Stooq) we cross-checked
by hand for PKN, KGH, LPP across D1/W1/MN. That manual verification is the provenance of the golden
values; the tests re-assert them on every run.

## Layers

- **Unit** — `resolve` (`test_yahoo.py`), `_period`, `aggregate`, `last_closed`
  (`test_indicators.py`), `build_daily` null-close backfill and `fetch_chart`'s URL, retries and
  reasons over a scripted opener (`test_yahoo.py`), the value objects
  (`test_model.py`) and symbol lookup (`test_symbol_index.py`).
- **Stooq oracle** (`TestStooqOracle`) — pipeline vs Stooq, to the grosz, over the hand-verified
  recent window per interval. Low/Close always match; the two ex-dividend weeks (PKN 2026-06-15,
  KGH 2026-06-22) keep our unadjusted Open/High while Stooq back-adjusts — asserted explicitly, not
  skipped.
- **Completeness / last_closed** — flags relative to `FROZEN_TODAY` (July month still forming; the
  just-closed week complete on a Saturday); `last_closed` is that newest closed period on every
  interval, at Stooq's close for it.
- **Session close** (`TestSessionClose`) — the flag follows the venue's session, not the date: today's
  bar forming during the session, complete after the close and all evening, conservative when the
  vendor omits the trading period, market tz beating machine tz. Weekly/monthly counterparts live in
  `TestAggregate`.
- **ATR** (`TestATR`) — the number two risk skills must agree on, pinned from three sides: arithmetic
  hand-computable at `n=2` (including the `|prevC - L|` branch), independence from `--bars` in both
  directions (a short slice cannot starve it, a wide fetch cannot shift it), and a regression golden at
  `n=14`. The `n=14` value is a **regression pin**, not an independently verified one — the Stooq CSVs
  are ~16 rows, too short for a 14-period run-up; correctness of the arithmetic rides on the `n=2` test.
- **Port contract** — `TestQuoteChain`: a higher source wins a shared date and a lower one fills the
  gaps, a source that raises lands in `unavailable`, all of them raising is an error, an empty answer
  is not; `TestDaily`: Yahoo labels every bar with its `source` and raises when it did not answer.
- **Trust** — each source judges its own sessions. `TestPlaceholder` (`test_yahoo.py`): a bar with
  `o == h == l == c` and volume 0 or missing is untrusted `"placeholder"`, judged alone (the first
  bar of an answer too, five in a row all of them), forming bars included; a flat bar
  with volume, a bar with a range and no volume, and a bar with a missing price stay trusted.
  `TestToBar`: an open, high, low or close Yahoo sent that is no price (0, negative, not finite)
  becomes `null` and makes the bar untrusted `"unusable_price"`, which also wins over `"placeholder"`
  on a bar flat at 0; a price Yahoo did not send, or an unusable volume, leaves the bar trusted.
  `test_store.py`: every store bar is trusted, even one shaped like a placeholder. `TestTrust`,
  `TestQuality`, `TestPeriodBar` (`test_model.py`): an empty reason is rejected; quality is sorted and
  unique, and `uncertain` as soon as it names a session; a period bar without a close is `no_value`.
  `TestDailyBarAsCandle`, `TestPeriodBarAsCandle`: a daily bar's day is its session and it is
  trusted as its source says; an untrusted session that ended leaves itself out of a reading, a
  forming one leaves nothing out; a period bar's day is its first day and it is always trusted,
  judged by its quality instead.
- **Quality of readings** — `TestReadingsCarryQuality`: without an untrusted session no reading
  leaves anything out and every week is `good` (the golden tests pin the values on that same
  series). `TestPlaceholderSessions`: ATR and its
  `as_of` equal the ATR on the clean prefix, `uncertain` with the five dates; a gap inside the window
  is named and pushes the window one candle further back; no swing low is confirmed by a placeholder,
  and one is once real sessions follow the gap; `last_closed` is the last real session, read over the
  whole series even when the `--bars` slice is all placeholders; a week of placeholders stays in the
  series as `no_value`, a week with two real sessions is read from those two, a placeholder Friday
  still closes the week, weekly readings skip the `no_value` week and name its sessions; a forming
  untrusted bar adds nothing to its period. Several of these also show that the test has teeth: the
  same series read as if trusted gives a different answer.
  `TestClosedPlaceholderInThePeriodInProgress`: with a closed placeholder Monday and a forming
  placeholder Tuesday after a real week, weekly `last_closed`, ATR and swing lows keep their values
  and name the Monday, as D1 `last_closed` does; the forming Tuesday is named by none.
- **Store, file** (`test_store_file.py`) — `read` rejects every broken rule with its line (header,
  columns, number, OHLC, weekend, duplicate, order, CRLF, BOM, not UTF-8, unreadable); `write`
  round-trips byte for byte, sorts, replaces atomically; `merge` counts added / unchanged / changed
  by value (`133.5` equals `133.50`), `source` aside.
- **Store, adapter** (`test_store.py`) — every row up to the period end and none after; an empty
  answer for an ISIN without a file (still resolved); an ISIN outside the map answered as any other; `no_store`
  when the directory is missing, `malformed` (plus `path:line` on stderr) for a broken file; in a
  chain the store wins a shared date.
- **Importer** (`test_import_stooq.py`) — snap examples for prices and volume (the radius is 1e-5
  of the value, no cap; a value outside it is rejected, never cut); `parse` on both headers and line
  endings and every rejection, including real full-history rows (PEO, LPP) whose volume noise is
  beyond the radius, inline because the full files are not committed; on the real exports, guards
  that every noisy PEO price and every noisy LPP price and volume sits within the radius, and ATR
  pins taken the way the CLI gets them (parse, the store file written to a temp directory, read back
  through `StoreQuotes`): PEO 7.52 agrees with the 2026-10-10 hand computation; ALE is a regression
  pin. `main()` on a temp store: the first import creates the store, the same export twice changes
  nothing (same bytes), a changed close is reported with its date, today's row is imported, a
  header-only export writes nothing. Exit 1, store untouched: a session after today, a bad row (the stored file stays byte for
  byte), a broken store file (not overwritten), a missing export; and, without a traceback
  (`TestImportStorePath`), a `--store` that is a file, a store directory without write permission,
  one that cannot be created (both skipped as root). An ISIN outside the map is imported. Exit 2: a
  missing `--store`, a `--for` that is no ISIN (a ticker, a check digit, lower case, a space), a literal `${` in `--store`, a `--store` whose parent directory does not exist (nothing
  created).
- **CLI** (`test_cli.py`) — `build_source` fetches on every call (there is no cache), with a
  store asks it before Yahoo, and hands its opener and sleep through to Yahoo's fetch; the `ok:true` / `ok:false` records (one `ok:false` path
  for a failed chain and for no bars while a source did not answer), no `xtb` field, a key that is
  no ISIN (check digit, garbage, a ticker, lower case, a space) `invalid_isin` for that key alone,
  an ISIN outside the map answered by the store with Yahoo `unmapped` and never fetched, the header
  naming every source in trust order, and `--bars` edge values that must not crash.
  `TestFlagsReachTheCompositionRoot`: `--store` reaches `build_source` through `main()`, and
  `--cache`, a literal `${` in `--store`, or a `--store` whose parent directory does not exist,
  exits 2 before anything is built; a missing store directory under an existing parent still reaches it.
  `to_json`: a daily bar prints `trusted` and, only when false, `untrusted_reason`; a W1/MN bar and
  every reading print `status` and `excluded_sessions`. `TestOutputPinned`: without a store the
  output equals `fixtures/cli_0_6_0_PKN.json` minus `xtb` and keyed by the ISIN (continuity), and
  `fixtures/cli_0_7_0_PLPKN0000018.json` byte for byte; without placeholders every bar is trusted
  and every derived value `good` on D1, W1 and MN; the comparison itself catches a changed value,
  a float printed as an int, an added key and a new key order. `TestPlaceholderSessionsEndToEnd`: store bars
  trusted, Yahoo placeholders marked, ATR and `last_closed` as of the last real session and
  `uncertain` with the gap's dates, the week of placeholders `no_value`.
- **Names** (`test_symbols.py`) — `main()` with its output parsed: a ticker or an ISIN the map does
  not know is `found:false`, never guessed; a mapped ISIN the broker does not offer is `found:true`
  with `xtb:null`; text that is no ISIN (check digit, lower case, a space, a ticker) is
  `invalid_isin` for that key only; the CCC rename guard; `--from yahoo`, `--to yahoo`, an unknown
  namespace, no direction or both exit 2 with nothing on stdout.
- **Live smoke** (opt-in, `RUN_LIVE_SMOKE=1`) — hits Yahoo to catch API/shape drift the fixtures
  can't see until re-captured.

Out of scope on purpose: deep history. The trimmed fixture starts mid-period (oldest week/month is
partial) and old bars reintroduce every past corporate action, which we did not verify by hand.

## Updating fixtures

When Yahoo's format or the mapping changes, re-capture: fetch `range=1y&interval=1d` for each ticker,
keep the last ~150 bars + `meta` (`gmtoffset`, `regularMarketPrice`, `regularMarketTime`,
`currentTradingPeriod`), and re-trim
the `stooq_{pkn,kgh,lpp}_*` CSVs to their last ~16 rows. Then re-pin `FROZEN_TODAY` and refresh the
expected values. A re-captured `yahoo_PKN.json` also means regenerating `cli_0_6_0_PKN.json` with
plugin 0.6.0 and `cli_0_7_0_PLPKN0000018.json` with plugin 0.7.0, not with the current code, or the
pins stop pinning anything.

The `_raw` exports are not re-captured: the ATR pins and the snap guard are tied to them as they
are. A new export goes in under a new name.
