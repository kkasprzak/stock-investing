---
status: "accepted"
date: 2026-10-12
decision-makers: Karol Kasprzak
consulted:
informed:
---

# Derived values are computed only from trusted sessions and carry a status

## Context and Problem Statement

The market data layer (`stock-market-data`) computes values on top of daily candles: ATR, swing
lows, weekly and monthly candles. In October 2026 the vendor served placeholder candles for every
GPW series we track, five sessions in a row, and the layer computed on them as if they were real.
ATR came out up to 23.5% too low. Stop moves appeared which the market did not justify, entries
were sized 10 to 20% too large, a valid setup was rejected, and swing lows were "confirmed" by
sessions which never traded. The consumer (the operating log of the trading plan) caught it only
because a human compared the numbers with the broker.

Now the layer can tell a candle it does not trust from one it does. The question is: what does it
promise the consumer about a derived value when some sessions in its window are not trusted?

## Decision Drivers

* A wrong number must not look like a right one. That was the whole damage of the incident.
* The layer returns facts, not decisions. The consumer judges; the layer has to name the fact.
* The consumer asked for a signal, not a repair: "make the layer say so, instead of the caller
  having to know". It needs a named condition for "this value may be used again", and
  it explicitly did not want that condition to be a number of sessions to wait out.
* The consumer must not compute ATR itself. Two callers would disagree on the same number.
* The layer never guesses a price for a session it does not have.
* The contract already has this pattern: a value computed on too short a history is still
  reported, but marked, "never a silent [NO DATA]".

## Considered Options

* Refuse: no value at all while any session in the window is not trusted
* Compute only from trusted sessions, and say what was left out and that the window was not whole
* Compute from everything, as today, and only mark how many sessions were not trusted

## Decision Outcome

Chosen option: "Compute only from trusted sessions, and say what was left out and that the window
was not whole", because it is the only one which gives a number that is true and at the same time
something the consumer can write a rule against. This is what the consumer asked for.

Every derived value carries a status with three meanings: good (every session in the window was
trusted), uncertain (the value is true, but computed without some sessions, which are named, so it
may be older than the last session), or no value. A consumer may use a good value, must treat an
uncertain one with care, and decides itself how old is too old. The layer does not know that
threshold.

This binds every derived value: ATR, swing lows, weekly and monthly candles, and any indicator
added later. An untrusted session is never counted as a session which confirmed a swing low.
Completeness of a candle stays honest: a session which ended is complete even when it is not
trusted. Trust is a separate fact.

### Consequences

* Good, because the consumer can name its own condition, "the status is good", and hold or release
  decisions on it without reading candles.
* Good, because a true but older value is still available. After the vendor incident the ATR as of
  the last real session can be used, with that date stated, instead of nothing.
* Bad, because a true value can be stale. The consumer has to read the date it is valid for, not
  only the number.
* Bad, because the first real session after a gap is measured against the last trusted one, so one
  true range covers more than one day. That is how holidays already work, but now it can happen
  mid-week.

## Pros and Cons of the Options

### Refuse: no value at all while any session in the window is not trusted

* Good, because no wrong number can leave the layer.
* Bad, because "no number" is a decision taken for the consumer. It turns every gap into a
  blockade until someone imports the sessions, and the consumer did not want to wait out sessions.
* Bad, because the consumer loses even the true value as of the last real session.

### Compute only from trusted sessions, and say what was left out and that the window was not whole

* Good, because the number is true and the fact which makes it uncertain is stated next to it.
* Good, because it follows how price validation and industrial data quality work: inputs which did
  not pass are not used, and a computed value carries whether all its inputs were good.
* Bad, because the value can be older than the last session, and someone reading only the number
  will not see it.

### Compute from everything, as today, and only mark how many sessions were not trusted

* Good, because it is the cheapest change.
* Bad, because the number is still wrong. A mark next to a wrong number does not fix the incident,
  it only labels it.

## More Information

Follows ADR 0000: sessions the own store has are trusted, so this decision matters for sessions
nobody imported yet. Which candle counts as not trusted is a rule in the code and its tests, not
part of this record. How the consumer reacts to an uncertain value (stops, sizing, entries) is the
consumer's rule, in its own repository.

Industry practice this follows: OPC UA status codes (good / uncertain / bad, and for a computed
value whether all inputs were good); price validation in EDM systems, where a price which fails
validation does not enter the golden copy.
