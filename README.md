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

The analysis layer of a trading plan. Three skills, each working on **one instrument in isolation**:

| skill | what it does |
|---|---|
| `stock-market-data` | Fetches delayed daily / weekly / monthly OHLC candles and Wilder ATR for named tickers (GPW / XETRA / US), resolved through a shared ISIN-keyed symbol map. The single place ATR is computed, so two callers never disagree on the same number. |
| `instrument-analysis` | A purely technical read of one instrument from a candle snapshot: trend, momentum, key levels, condition, invalidation, an implied stop, and a 0-10 setup score. Emits a strict ten-line contract with closed vocabularies, so an orchestrator can parse it. |
| `instrument-research` | Web-sourced company facts, one facet at a time: `events` (earnings, ex-dividend, buybacks, overhang, contested control), `fundamentals`, or `news`. Every date and number carries its source, or is marked `[UNVERIFIED]` — never inferred. |

**What they deliberately do not do:** place orders, connect to a broker, read your account, size a
position, or tell you to buy or sell anything. They take data in and return findings. Every
portfolio decision belongs to you or to whatever calls them.

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
ships with ~144 instruments, mostly GPW. Add your own: one entry per ISIN with `name` and
`symbols: {xtb, yahoo}`. The ISIN is the key because it survives renames — a blind ticker-suffix
swap does not.

## Tests

```bash
python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests
RUN_LIVE_SMOKE=1 python3 -m unittest discover -s trading-plan/skills/stock-market-data/tests
```

The offline suite runs against frozen fixtures in about a hundredth of a second. The live smoke
test hits the data provider and is opt-in.

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
