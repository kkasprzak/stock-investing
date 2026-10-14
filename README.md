# stock-investing

A Claude Code marketplace for reading a stock before you buy it — the boring, repeatable part of
equity analysis, packaged so it runs the same way every time.

## Why this exists

Discretionary stock analysis drifts. The same chart reads bullish on a good day and toppy on a bad
one, ATR gets eyeballed instead of computed, and "what were this company's numbers again" turns
into forty minutes of tabs. These skills fix the parts that should never have been judgment calls:
where the data comes from, what shape the answer takes, and what the analysis is not allowed to say.

Useful to you if you pick individual stocks and want your own process to be reproducible — whether
that runs in a retirement account, a taxable brokerage account, or a spreadsheet.

## Plugins

### `trading-plan`

The analysis layer of a trading plan. Four skills — three read **one instrument in isolation**, the
fourth remembers what you held:

| skill | what it does |
|---|---|
| `stock-market-data` | Fetches delayed daily / weekly / monthly OHLC candles and Wilder ATR for instruments named by ISIN (GPW / XETRA / US); the vendor's symbol comes from a shared ISIN-keyed symbol map, and the same skill translates a broker's ticker to its ISIN and back. Asks your project's own candle store first (one CSV per ISIN under `data/market-data/`, filled only by importing Stooq exports with `import_quotes.py`), and Yahoo only for the sessions the store lacks. The single place ATR is computed, so two callers never disagree on the same number. |
| `instrument-analysis` | A purely technical read of one instrument from a candle snapshot: trend, momentum, key levels, condition, invalidation, an implied stop, and a 0-10 setup score. Emits a strict ten-line contract with closed vocabularies, so an orchestrator can parse it. |
| `instrument-research` | Web-sourced company facts, one facet at a time: `events` (earnings, ex-dividend, buybacks, overhang, contested control), `fundamentals`, or `news`. Every date and number carries its source, or is marked `[UNVERIFIED]` — never inferred. A buyback's status names the company report it rests on, and is `[UNVERIFIED]` when a later event is known only from a search summary. |
| `position-journal` | An append-only log of positions opened and closed, and three folds over it: what you hold, every episode of one name, and how many shares you held on a given date. A state file forgets a position the moment you delete its row — this is what answers *have we owned this before, and when did we leave it*. |

**What they deliberately do not do:** place orders, connect to a broker, size a position, or tell
you to buy or sell anything. They take data in and return findings. Every portfolio decision
belongs to you or to whatever calls them.

`position-journal` is the one skill that holds anything of yours, and it still reads nothing: you
tell it a fill happened and it records that. The log is a plain JSONL file in your own working
directory, and it never leaves it.

## Install

```bash
claude plugin marketplace add kkasprzak/stock-investing
claude plugin install trading-plan@stock-investing
```

Skills fire automatically when a task needs them — ask for a ticker's close, an ATR, a technical
read, or a company's next earnings date.

Python 3, standard library only. No API key, no account, no paid data feed.

### Symbol map

`trading-plan/skills/stock-market-data/scripts/symbols.json` maps ISIN to each source's ticker and
ships with ~145 instruments, mostly GPW. Add your own: one entry per ISIN with `name` and
`symbols: {xtb, yahoo}`. The ISIN is the key because it survives renames. Quotes are asked for by
ISIN; an ISIN without a `yahoo` symbol gets no Yahoo data (`unmapped`), because nothing is guessed
from the broker's ticker.

## Tests

```bash
make test                                      # every skill's offline suite
RUN_LIVE_SMOKE=1 python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests
```

The offline suites run in well under a second — `stock-market-data` against frozen fixtures,
`position-journal` against none at all, since it has no network and no clock. The
`stock-market-data` suite covers the importer too: real Stooq exports parsed and pinned, and
`import_quotes.py` run end to end on a temporary store. The live smoke test
hits the data provider and is opt-in.

## Disclaimer

**This is not investment advice.**

These skills produce technical levels, stop prices, ATR values, and a numeric setup score. Those
are outputs of a mechanical procedure, not recommendations, and they carry no opinion about whether
any instrument is worth owning. Nothing here is a solicitation to buy or sell a security, and none
of it accounts for your circumstances, objectives, or risk tolerance.

Specific limits worth knowing before you rely on any number:

- **Market data is delayed** (~15 minutes) and comes from a free public endpoint that can be wrong,
  incomplete, or unavailable. Prices are unadjusted, so they do not reconcile with
  dividend-adjusted series.
- **`instrument-research` reads the open web.** Facts are sourced or explicitly marked unverified,
  but sources are not authoritative, and a company's own filings always take precedence.
- **A score is a signal, not a gate.** Nothing in this repository has been validated as
  profitable, and no backtest is included.

Trading carries risk of loss, including total loss of capital. Verify every figure against your
broker and the company's official disclosures before acting on it. You alone are responsible for
your decisions.

## License

MIT
