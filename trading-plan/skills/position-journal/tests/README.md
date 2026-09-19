# Tests — position-journal

Deterministic, offline regression tests for `scripts/journal.py`. Stdlib `unittest`, no dependencies.

```
python3 -m unittest discover -s trading-plan/skills/position-journal/tests   # ~0.02s
```

## How it stays deterministic

Nothing is frozen, because nothing moves. The script has **no network** and **no clock** — every
event carries its own `--date`, and no read consults today. That is the opposite of
`stock-market-data`, where the wall clock decides whether a candle is complete and Yahoo has to be
captured into fixtures.

So there are no fixtures here. Each test builds the log it needs from named helpers (`opened`,
`closed`) into a `tempfile` directory, and nothing leaks between cases or touches a real book.
The symbols, quantities, prices and dates are invented — shaped like real trades, because that is
what exercises the folds, but describing no position anyone holds.

## Layers

- **Transition table** (`TestWrite`) — one test per row of the rule in `SKILL.md`, each asserting the
  `reason` **and** the exit class. The two that matter most are the pair that must never merge:
  `already recorded` is exit 0 so a re-run carries on, while every state refusal is non-zero so the
  flow stops instead of recording a fiction. Also pinned here: an add-on is legal (a second `opened`
  is a tranche, not a duplicate), backdating is allowed only when nothing newer exists for that
  symbol, and ordering is **per symbol** — another name's later event does not block this one.
- **`state`** — the fold that must line up with the portfolio state file: tranche sum, weighted
  average, `opened` as the *first* tranche, a closed symbol absent, a re-entry showing only the
  current episode, currencies kept apart.
- **`history`** — never held → `[]`; a closed episode carrying the date and price we left at; an open
  episode carrying `null` on both exit fields rather than omitting them (one shape, no special case);
  a re-entry showing both episodes in order.
- **`held`** — the boundaries, which is where this read earns its place: before the first purchase,
  on the open date, **between tranches** (returning the current size here would treble a dividend),
  **on the close date** (still held — the right is established at that session's close), after the
  close, and between two episodes.
- **Fractional arithmetic** — three tranches of a fractional ETF summing to a clean `9.6666` rather
  than to float noise.
- **`check`** — a clean log passes, a missing file is an empty log rather than a crash, a bad line is
  reported with its number, and the replay uses the same rule as the write path. That last test is
  the point: two copies of the invariant would drift.

## Out of scope on purpose

- **Stop events.** The journal does not hold them, so there is nothing to test. The current stop
  lives in the portfolio state file, verified against a screenshot daily.
- **"Did the plan execute."** Non-execution leaves no event by design. A log of what happened cannot
  carry the reason something did not, and the reason is the whole value — so this is not a gap to
  cover with a test but a boundary to keep.
- **Realized results.** `(exit − entry) × qty` per episode is computable from the same events and has
  no consumer yet, so no verb and no test. The prices are on the events precisely so that adding it
  later needs no new field.
- **Anything networked.** There is none.
