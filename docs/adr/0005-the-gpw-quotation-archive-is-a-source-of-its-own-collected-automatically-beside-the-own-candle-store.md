---
status: "accepted"
date: 2026-10-16
decision-makers: Karol Kasprzak
consulted:
informed:
---

# The GPW quotation archive is a source of its own, collected automatically beside the own candle store

## Context and Problem Statement

The market data layer (`stock-market-data`) asks its sources in trust order: the own candle store
first (ADR 0000), then Yahoo. The store is filled by hand. To have the last session of every GPW
name we follow, the user downloads more than ten Stooq exports each day and imports them one by
one. This cannot run unattended, because Stooq blocks automatic downloads. A day nobody imports
falls back to Yahoo, and Yahoo is the provider that served fake GPW candles for old sessions in
October 2026. One provider going wrong was enough to take the whole system down.

ADR 0000 looked at the GPW quotation archive as the store and rejected it. Its reasons were that
the archive is HTML, that its volume seemed to be turnover value and not a number of shares, and
that nobody had checked whether its prices are adjusted for dividends. We have looked again, from
2026-10-14 to 2026-10-16: the archive has volume in shares and turnover in a separate column, its
open, high, low and close for the five names we compared on 14 and 15 October matched Stooq's
unadjusted export to the grosz, and a page read two days after its session had not changed. We
have not yet seen a dividend inside that window. The archive is published by the exchange, keyed
by ISIN, and one page holds the whole market for one session.

The question is how the GPW archive should feed the layer, and how it relates to the own store.

## Decision Drivers

* No single provider may be able to take the system down again. There have to be independent
  sources, and a way to put data in by hand when the others fail.
* The daily session has to arrive without anyone doing anything.
* Sources must not be mixed. The own store holds what the user imported by hand, from providers
  that publish history as files to download; it is the reserve when every other source is down.
* GPW has no interface that answers a range of sessions for one instrument. There is only one HTML
  page per session, for the whole market, which has to be read and parsed every day.
* The layer that serves quotes only reads (ADR 0000, ADR 0004).

## Considered Options

* Keep importing Stooq exports into the own store by hand
* Import the GPW archive into the own store, as a second importer beside Stooq
* Read the GPW archive pages when the layer is asked
* Collect the GPW archive automatically into a store of its own, served as a separate source

## Decision Outcome

Chosen option: "Collect the GPW archive automatically into a store of its own, served as a
separate source", because it is the only option that brings each session in without anyone's work
and still keeps the user's own store apart, as the reserve for the day every other source fails.

The GPW source sits below the own store and above Yahoo. What the user imported by hand stays the
truth; the GPW source fills what the store does not have; Yahoo is left for what neither has, such
as instruments not listed on GPW and the session of today before the archive is published.

The collecting runs on a schedule, as a tool of its own. The layer that serves quotes still writes
nothing.

This is not a cache in the sense of ADR 0004. A cache keeps a copy of what a source answers so that
the source is not asked twice. GPW cannot be asked for an instrument's history at all; the
collected sessions are the only form in which this data can be read.

The collected sessions are versioned in git in the consumer's repository, like the own store
(ADR 0001), though in a directory of their own. Once this source fills most GPW sessions, it is the
record that notes cite. That record has to stay in our hands and not depend on GPW keeping its
archive unchanged, and a candle that changes after it was collected has to be visible, not silent.

### Consequences

* Good, because a failure of Yahoo or Stooq no longer leaves GPW names without real candles.
* Good, because the last session arrives every day without a manual import.
* Good, because every candle still says which source it came from, so a hand-imported candle and a
  collected one can always be told apart.
* Good, because the archive's volume includes trades that the evening snapshot of other providers
  misses: on 15 October it was 14 to 16 percent higher for two of five names.
* Bad, because reading HTML breaks when GPW changes the page. The source then stops answering
  until the parser is fixed, and Yahoo fills the gap meanwhile.
* Bad, because the archive also lists instruments that had no trade in a session, and on some days
  its low and high differ from every other provider. The source has to say which sessions it
  vouches for; what it cannot vouch for it serves as untrusted.
* Good, because a collected candle that changes later, after a fix to the parser or a correction on
  GPW's side, shows up in git history and is not overwritten silently.
* Good, because the collected record outlives the archive: if GPW ever stops publishing past
  sessions, the copy in git remains.
* Bad, because every collected session touches one file per listed instrument, a few hundred files
  a day, so the history of that directory is noisy.
* Bad, because a series can now mix two kinds of volume: the evening snapshot from hand imports and
  the final figure from the archive.

## Pros and Cons of the Options

### Keep importing Stooq exports into the own store by hand

* Good, because nothing new has to be built.
* Bad, because more than ten files have to be downloaded and imported each day, and Stooq blocks
  doing it automatically.
* Bad, because a day nobody imports is served by Yahoo.

### Import the GPW archive into the own store, as a second importer beside Stooq

* Good, because it fits ADR 0000 as written: one store, filled from more than one source.
* Bad, because it mixes what a scheduled tool writes with what the user imported by hand, so the
  store stops being the reserve that does not depend on any automatic source.

### Read the GPW archive pages when the layer is asked

* Good, because there is nothing to store.
* Bad, because one page holds one session. A single question about twenty or more sessions, as the
  indicators need, would mean dozens of requests to the exchange's website.
* Bad, because keeping those pages to avoid the requests would be the cache ADR 0004 dropped.

### Collect the GPW archive automatically into a store of its own, served as a separate source

* Good, because it is automatic, independent of the vendors, and keeps sources apart.
* Bad, because it is one more adapter, one more store, and a scheduled job to keep running.

## More Information

Revisits the GPW archive option that ADR 0000 rejected; the own store keeps the meaning ADR 0000
gave it. Narrows ADR 0004: that record is about copies of what a vendor answers, not about a
source that can only be collected. Come back to this decision if GPW offers an interface for
historical quotes, or if the archive pages change often enough that parsing them costs more than
importing by hand.
