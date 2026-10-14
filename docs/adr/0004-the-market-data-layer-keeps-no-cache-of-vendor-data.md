---
status: "accepted"
date: 2026-10-14
decision-makers: Karol Kasprzak
consulted:
informed:
---

# The market data layer keeps no cache of vendor data

## Context and Problem Statement

The market data layer (`stock-market-data`) had an optional cache on disk: a vendor's daily series
was saved so that a second read on the same day could skip the fetch. A security review found that
the cache never landed where it was meant to, inside the project, but always in the shared temporary
directory. There another user could plant a link that made the layer overwrite a file of theirs
choosing, or plant an entry that the layer then served as vendor data. Only one flow of the consumer
asked for the cache: a screen over about sixty names that are not in the own candle store. The
question is whether to keep a cache, in a safer place, or to drop it.

## Decision Drivers

* The candles worth keeping are kept by the own candle store (ADR 0000, ADR 0001), so a second
  copy of vendor data on disk has no job the store does not already do better.
* The layer only reads. Writing would give it a second responsibility (ADR 0000).
* A file the layer writes and later serves as vendor data is a way for forged data to come in.

## Considered Options

* Keep the cache, in a directory the project names
* Drop the cache

## Decision Outcome

Chosen option: "Drop the cache", because what is worth keeping already lives in the own candle
store, and the layer that serves market data then writes nothing at all.

### Consequences

* Good, because the market data layer writes nothing to disk, so there is nothing on disk to forge.
* Good, because the logic that decided when a cached series went stale, across a session's close,
  goes with it.
* Bad, because a second run of the same screen on the same day fetches every series again: about
  sixty requests to the vendor, at a pause of 1.5 seconds each, and more exposure to its rate limit.

## Pros and Cons of the Options

### Keep the cache, in a directory the project names

* Good, because a repeated read on the same day stays cheap.
* Bad, because the layer keeps writing vendor data and serving it back, which is the path the
  security review found.
* Bad, because it is a second store of candles beside the own store, with weaker guarantees.

### Drop the cache

* Good, because the layer is read only, as ADR 0000 says.
* Bad, because repeated reads of names outside the store cost a fetch each time.

## More Information

Follows ADR 0000. If repeated reads of names outside the own store become costly, the way out is
importing those names into the store, not a cache.
