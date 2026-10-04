---
type: llm
name: buyback-matches-reference
weight: 3
---

You are judging one answer from the `instrument-research` skill. Judge **only its `buyback` field**
against the reference below.

PASS only if that field satisfies every item under "Must state" and contradicts no item under
"Must not state". Items under "Not decisive" are what a full answer would also give: their absence
or imprecision never fails it. "Context" explains the inputs and is not something the answer has to
say. Ignore everything under "Not required". Wording, order, formatting, a leading status token or
its absence, and the facet's other fields may all differ. If a required claim cannot be settled from
the answer alone, FAIL.

# Expected `buyback:` — ale-0926-replay

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-09-26**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required.

## Must state

- The current programme's status is **not given as confirmed**: it is marked unconfirmed
  (`[UNVERIFIED]`, or plainly as not confirmed by a company report).
- Phase II's price cap and start date are **not established**, and are marked unconfirmed. Calling
  Phase II active is acceptable only with its cap marked unconfirmed.
- If the AGM authorisation (PLN 1.6 billion, PLN 0.01–50.00) is mentioned, it is identified as the
  authorisation and kept apart from any programme. Calling its PLN 50.00 limit a cap or ceiling is
  fine; giving it as the cap of a running programme is not.

## Must not state

- A certain status — "active", "confirmed" — resting only on search-engine summaries.
- Phase I's cap raised to PLN 50 as the live state of the current programme.
- PLN 1.6 billion as the size of the running programme.

## Context

- Phase II — adopted 22 September 2026, up to PLN 800 million — appears in the inputs only in a
  search-engine summary; no company current report about it is among them. That is why its status
  cannot be confirmed. The answer does not have to say so in these words.

## Not decisive

- Executing broker, fills, and Phase II's size.

## Not required

- A current-report number for the programme — none of the inputs carries it.
