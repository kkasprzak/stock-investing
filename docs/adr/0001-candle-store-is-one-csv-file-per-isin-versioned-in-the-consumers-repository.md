---
status: "accepted"
date: 2026-10-12
decision-makers: Karol Kasprzak
consulted:
informed:
---

# Candle store is one CSV file per ISIN, versioned in the consumer's repository

## Context and Problem Statement

ADR 0000 says our own candle store is the most trusted source of market data, and leaves its
format open. Now the market data layer (`stock-market-data`) has a port for quote sources, and the
store is the next adapter. Before anyone writes it, we have to say what the store physically is and
where it lives. This is state: changing it later means migrating data, not refactoring code.

The question is: in what form, and where, do we keep the candles?

## Decision Drivers

* The store is data of the user, not part of the plugin. The skill has to stay a clean
  distributable artifact; even its cache lives outside it.
* The record of what happened must have a history. When a candle changes after import, it must be
  visible, not silent. Numbers cited in notes have to be checkable later (ADR 0000).
* The plugin is standard library only, no virtualenv.
* It has to hold all instruments from the symbol map (144 today), later maybe other exchanges.
* Import is manual and repeated: the same export, or two exports with overlapping dates, must not
  create duplicates.
* Size does not matter here. All instruments for twenty years is well under a million rows.

## Considered Options

* One CSV file per ISIN, versioned in git in the consumer's repository
* One JSONL file per ISIN, versioned in git
* One SQLite file
* One CSV file for all instruments

## Decision Outcome

Chosen option: "One CSV file per ISIN, versioned in git in the consumer's repository", because git gives
the history and the audit for free, the diff of one import is small and readable, and a candle is
a flat row which does not need JSON.

Git is the only history. When an import changes a candle which is already there, the row is
overwritten and git shows the change. The store itself does not version rows and does not record
when a row was imported. That is a conscious choice, not an omission.

The store lives in the repository of the consumer of this data (the trading plan's operating log),
not in the plugin.

### Consequences

* Good, because any change to any candle can be found with `git log` on one file.
* Good, because a new exchange or a new instrument is only a new file. ISIN is global.
* Bad, because the store is tied to one consumer's repository. A second consumer would need its
  own copy or a shared path.
* Bad, because without a database there is no index and no constraint. Uniqueness of a session is
  kept by the importer, not by the storage.

## Pros and Cons of the Options

### One CSV file per ISIN, versioned in git

* Good, because one line is one candle, so a diff reads like a list of sessions.
* Bad, because adding a column means touching every file.

### One JSONL file per ISIN, versioned in git

* Good, because every row names its fields, so the schema can grow row by row.
* Bad, because the keys are repeated in every line, so a diff is more than twice as long for the
  same information.
* Bad, because a candle is a flat row; the structure JSON is good at is not there.

### One SQLite file

* Good, because uniqueness of a session and range queries would come from the database.
* Bad, because the file is binary. `git diff` shows nothing, so the history we rely on is gone.

### One CSV file for all instruments

* Good, because there is one file to find.
* Bad, because with 144 instruments every import is a diff inside one huge file, and two imports
  in one commit collide in it.

## More Information

Follows ADR 0000. Come back to this decision if a second consumer of the store appears, or if the
store has to be shared between machines in a way git does not cover.
