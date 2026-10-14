---
status: "accepted"
date: 2026-10-14
decision-makers: Karol Kasprzak
consulted:
informed:
---

# Market data is requested by ISIN only, and naming an instrument is a separate tool

## Context and Problem Statement

The market data layer (`stock-market-data`) has accepted two kinds of key for an instrument: a
broker's ticker or an ISIN. One request could mix both. When a ticker was not in the symbol map,
the layer guessed the vendor's symbol from it, and a security review found that this guess was the
only path by which a caller's text reached the vendor's URL. The question is which key a request
for market data takes, and where the knowledge of how brokers and exchanges name an instrument
lives.

## Decision Drivers

* One kind of key per request. With two kinds, a single request can mix tickers and ISINs.
* Brokers and exchanges each name the same instrument differently. Knowing those names is not the
  job of the layer that serves prices.
* An ISIN does not change when an instrument is renamed, and the symbol map and the own candle
  store are already keyed by it (ADR 0001).
* The layer never guesses. A guessed vendor symbol can point at the wrong instrument, and it
  carries the caller's text into the vendor's URL.

## Considered Options

* A broker ticker or an ISIN, each checked as its own kind of key
* ISIN only, and every caller translates its own names
* ISIN only, and one separate tool translates between ISINs and the names brokers and exchanges use

## Decision Outcome

Chosen option: "ISIN only, and one separate tool translates between ISINs and the names brokers and
exchanges use", because a request then has exactly one kind of key, one that survives renames, and
the naming of instruments has one owner instead of being spread over every caller or mixed into
the market data layer.

The market data layer takes ISINs and nothing else. It does not report a broker's ticker either.
How a broker or an exchange names an instrument, in either direction, is answered by the separate
tool, which reads the same symbol map. Translating an ISIN into a data vendor's own symbol stays
with that vendor's adapter, since it is knowledge about that vendor.

### Consequences

* Good, because no caller text reaches a vendor, and no symbol is ever guessed.
* Good, because the names of instruments are kept in one map and translated by one tool, so two
  callers cannot translate the same ticker differently.
* Bad, because this breaks every caller that asks by broker ticker. State files and flows that
  speak in broker tickers have to carry ISINs, or translate through the tool first.
* Bad, because an instrument missing from the symbol map gets no vendor data until it is added.
  The own store still answers for it, since it is keyed by ISIN.

## Pros and Cons of the Options

### A broker ticker or an ISIN, each checked as its own kind of key

* Good, because callers keep asking by the names they already hold.
* Bad, because one request can still mix the two kinds of key.
* Bad, because the market data layer keeps knowing how brokers and exchanges name instruments.

### ISIN only, and every caller translates its own names

* Good, because the market data layer has one kind of key.
* Bad, because every caller would hold its own translation, and two of them would sooner or later
  disagree on the same instrument.

### ISIN only, and one separate tool translates between ISINs and the names brokers and exchanges use

* Good, because the request has one kind of key and the naming has one owner.
* Bad, because a caller holding only a ticker makes two calls instead of one.

## More Information

Follows ADR 0000 and ADR 0001: the own candle store, the most trusted source, is keyed by ISIN.
Worth revisiting if a caller needs market data for something that has no ISIN.
