---
name: position-journal
description: Record that a position was opened or closed, and answer from that record what we hold, whether a name was ever ours, and how many shares we held on a given date. Use whenever a fill or an exit is confirmed at the broker (a morning check writing a filled entry, an evening check writing a stop-out), and whenever a flow needs the history behind a name — "have we held this before", "when did we leave it", "did we own it on the ex-date", "is this a re-entry", "were we entitled to that dividend". An append-only log of what happened; the folds over it are derived, never stored. NOT the operational state of the portfolio — that is the state file reconciled against the broker screenshot. NOT a record of what was supposed to happen: a plan that did not execute leaves no event.
user-invocable: false
---

# position-journal

An append-only log of position events, and the folds over it. Two things are recorded — a position
was opened, a position was closed — and everything else is derived on read. Returns facts
(self-describing JSON); the caller judges.

It exists because a state file holds only what is open. Delete the row of a position that closed and
nothing remembers the name was ever ours — so a rule like *a stopped-out instrument is not an
automatic re-entry candidate* has no data to stand on. This is that data.

## Run

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py opened --symbol ACME.PL --qty 80 --price 25.00 --currency PLN --date 2024-04-02
python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py closed --symbol ACME.PL --qty 80 --price 22.50 --currency PLN --date 2024-04-19

python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py state
python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py history --symbol HELM.PL
python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py held    --symbol TERA.PL --on 2024-07-15

python3 ${CLAUDE_SKILL_DIR}/scripts/journal.py check                      # replay the whole log through the write rules
```

Every write argument is required. `--currency` has no default — a EUR position silently read as PLN
is a mistake nobody sees. `--date` is the session the event belongs to and is never taken from the
clock: a morning check recording the previous session's stop-out is normal.

`--journal FILE` overrides the default `data/journal.jsonl`, resolved from the working directory.

Write a second `opened` on a name already held and it is an **add-on**, not a duplicate — the
position gains a tranche. Whether a position should be added to at all is a sizing question, not
this skill's.

## Output contract

**`state`** — what we hold. Field names match the columns of the portfolio state file, because
comparing the two is what this read is for.

```json
{"positions": [
  {"symbol": "NOVA.PL", "qty": 12,     "currency": "PLN", "opened": "2024-02-05", "entry": 100.0},
  {"symbol": "VEGA.DE", "qty": 9.6666, "currency": "EUR", "opened": "2023-11-06", "entry": 30.9828}
]}
```

`qty` sums the episode's tranches, `entry` is their weighted average, `opened` is the first tranche's
date. No totals: positions sit in different currencies and summing them would be a number that looks
right.

**`history`** — every episode for one symbol, oldest first. An episode is one holding: opened,
possibly added to, closed.

```json
{"symbol": "ZEN.PL", "episodes": [
  {"opened": "2024-03-05", "closed": "2024-04-18", "exit": 55.0, "currency": "PLN"},
  {"opened": "2024-06-11", "closed": null,        "exit": null, "currency": "PLN"}]}
```

Two episodes mean a re-entry. A name never held returns `{"symbol": "...", "episodes": []}` — an
empty list, never an error.

**`held`** — how many shares on a date.

```json
{"symbol": "TERA.PL", "on": "2024-07-15", "qty_on_date": 0}
{"symbol": "VEGA.DE", "on": "2024-01-02", "qty_on_date": 4.1111}
```

A count, not a yes/no: entitlement is per share, and a bare `true` invites multiplying by the
position's *current* size. Inclusive at both ends — on the close date the answer is the quantity
held, because a dividend right is established at the close of the last session carrying it.

**writes** — `written`, the echo of the call, and on a refusal the reason.

```json
{"written": true,  "event": "position_closed", "symbol": "ACME.PL", "as_of": "2024-04-19"}
{"written": false, "reason": "already recorded", "event": "position_closed", "symbol": "ACME.PL", "as_of": "2024-04-19"}
{"written": false, "reason": "no open position", "event": "position_closed", "symbol": "ACME.PL",
 "as_of": "2024-04-19", "last_event": "position_closed 2024-04-19"}
```

| refusal | meaning | exit |
| --- | --- | --- |
| `already recorded` | same `(date, event, symbol)` is in the log | **0** — a re-run is harmless, carry on |
| `no open position` | closing a name we do not hold | 1 |
| `qty exceeds position` | closing more shares than the episode still holds | 1 |
| `out of order` | dated before that symbol's last event | 1 |

The exit code is the contract: **0 means carry on, non-zero means stop.** A state refusal is not the
log being difficult — it means the screenshot was read wrong, and the next step would record a
fiction.

## Gotchas

Every one of these cost us something real. None is theoretical.

- **A split order is two fills, and the second one vanishes silently.** The duplicate key is
  `(date, event, symbol)`, so a second fill of the same order on the same session reads as a re-run:
  `already recorded`, **exit 0**, nothing written, flow carries on. Recording `30 @ 25.00` then
  `50 @ 25.10` leaves a 30-share position and no warning. **Collapse the fills first** — one event
  per `(date, symbol, direction)`, quantity summed, price the weighted average. The whole backfill
  was transcribed this way.
- **`--price` is the fill, never the level.** A position we left at a stop was recorded at the stop
  *level* the order carried, not at the price it actually filled at — the two differ by the gap, and
  the note carried the level. A price copied from a daily note or from a stop instruction is not a
  transaction: take it from the transaction screenshot.
- **The default path is relative to the working directory.** Called from anywhere but the repo root,
  `data/journal.jsonl` does not exist, the log reads as empty, and `history` answers `episodes: []` —
  indistinguishable from *we never held this*. That is exactly the answer that put a stopped-out name
  back on the watchlist. Pass `--journal` whenever the working directory is not certain.
- **A partial close is recorded, and the episode continues.** A holding scaled out of months before
  the doctrine banned scaling out is still a thing that happened. The log holds facts; whether scaling out is allowed is
  the risk doctrine's call, in the flow that decides — not a refusal here. Only `qty` above the
  balance is refused.
- **Compare quantities with a tolerance, never `==`.** A fractional ETF bought in three tranches —
  say 4.1111, 3.2222 and 2.3333 — does not sum to `9.6666` on the last bit.
- **A plan that did not execute leaves no event.** Non-execution has no fact to record, so nothing
  here can answer "did the plan execute" — that belongs to the daily note, which records a
  disposition *with its reason*, and a reason is exactly what a log of what happened cannot hold.

## The journal file (`data/journal.jsonl`)

One event per line, chronological, fixed key order so a diff stays readable:

```jsonl
{"as_of":"2024-04-02","event":"position_opened","symbol":"ACME.PL","qty":80,"price":25.00,"currency":"PLN"}
{"as_of":"2024-04-19","event":"position_closed","symbol":"ACME.PL","qty":80,"price":22.50,"currency":"PLN"}
```

Six fields, two event types, no free text and no metadata about the data. Lines are never edited and
never deleted; a mistake is corrected by appending, and `check` replays the whole file through the
same rules the write path uses — one copy of the invariant, so the two cannot drift.
