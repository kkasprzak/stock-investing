---
status: "proposed"
date: 2026-10-10
decision-makers: Karol Kasprzak
consulted:
informed:
---

# Own candle store is the most trusted source of market data

## Context and Problem Statement

All prices, ATR and swing lows in this repo come from the market data layer (`stock-market-data`).
Until now its only source was Yahoo. From 2026-10-05 (the same day GPW moved from UTP to WATS),
Yahoo started to serve fake daily candles for all seven GPW series we track. Each such candle had
open = high = low = close = last good close (2026-10-02), volume 0, and was marked as complete. Our
checks could not see any difference between them and real candles. It was even worse: two times in
one week a session that looked real in the evening was replaced by a fake candle next morning.

The IKZE operating log uses these numbers. ATR was too low by 13.1% to 23.5%. Stop moves appeared
which the market structure did not justify. One valid setup (CAR) was rejected without any warning.
Notes from that week cite close prices which do not exist anymore at the vendor (issue sim-76h).

The question is: where should the trusted history of daily candles come from?

## Decision Drivers

* The data layer is the most important part of the system. It must be resilient.
* Yahoo history is not stable. Sessions appear few days late, or change after we read them as
  final. We cannot treat it as a record of what really happened.
* We need correct data now, for the next run. We cannot wait until the vendor fixes it.
* The trusted source should be permanent, not a temporary fix until Yahoo works again.
* It cannot depend on one provider. Today's provider is only one way to fill it.
* This is a small personal project. Paying for a licensed data feed does not make sense here.

## Considered Options

* Yahoo as the only source, detecting bad candles and failing
* The layer saves candles it has seen confirmed from Yahoo into its own store
* Stooq's raw CSV exports, kept as files, are the store
* The GPW quotation archive
* A licensed commercial data vendor
* Our own provider-independent candle store, filled by importing from trusted sources

## Decision Outcome

Chosen option: "Our own provider-independent candle store, filled by importing from trusted
sources", because only this option gives real candles today and also keeps the record of what
happened in our hands. If the store has a candle, this candle is the truth. Other sources only fill
what is missing in the store.

Today I fill it manually from Stooq exports. Stooq blocks automatic download with an anti-bot
check. Its exports with "skip splits" and "skip dividends" options are not adjusted, we checked
it. On PEO we compared 114 sessions, including a 19.77 dividend (ex-date 2026-06-12). All 110
sessions where Yahoo was honest matched to the grosz and to the share. The four fake ones
(2026-10-05 to 10-08) were real candles in Stooq. After replacing those four, ATR(14) on 2026-10-09
is 7.52, and not 5.35 like on Yahoo data.

This decision does not choose the format of the store. It stays open on purpose.

### Consequences

* Good, because a session in the store does not change when the vendor rewrites its history. Numbers
  cited in notes can still be checked later.
* Good, because later we can add a new source (free or cheap) as another way to fill the store. The
  meaning of the store stays the same.
* Bad, because filling the store is manual work. A session which nobody imported yet still comes
  from a less trusted source and still can change.
* Bad, because the system has now state. The store must be kept somewhere and kept up to date.

## Pros and Cons of the Options

### Yahoo as the only source, detecting bad candles and failing

* Good, because there is nothing new to build or maintain.
* Bad, because detection gives only an error. The run cannot continue until the vendor fixes it,
  and for past sessions this may never happen.

### The layer saves candles it has seen confirmed from Yahoo into its own store

* Good, because the store would fill itself.
* Bad, because the store would be filled from the same source it should protect us from. One bad
  read would become permanent truth.
* Bad, because the layer answers queries. Writing would give it second responsibility.

### Stooq's raw CSV exports, kept as files, are the store

* Good, because stored data would be exactly what was downloaded, without any conversion.
* Bad, because it ties the trusted record to format of one provider. The store must live longer
  than any single provider.

### The GPW quotation archive

* Good, because it is published by the exchange itself.
* Bad, because it is served as HTML pages. Parsing HTML is not a reliable way to read prices.
* Bad, because volume there seemed to be turnover value, not number of shares like in other
  sources. We did not check if prices are adjusted for dividends.

### A licensed commercial data vendor

* Good, because a paid feed should be predictable and stable.
* Bad, because all vendors I found offer only paid licences. The cost is too high for a small
  personal project.

### Our own provider-independent candle store, filled by importing from trusted sources

* Good, because it gives real candles now and they stay stable.
* Bad, because someone must import data into it, and how fresh it is depends on that.

## More Information

Come back to this decision when a predictable, stable data source with an API is available for
free or for small money, for example from my broker. It can become one more way to fill the store,
or a reason to change this decision.

Decided while working on issue sim-76h.
