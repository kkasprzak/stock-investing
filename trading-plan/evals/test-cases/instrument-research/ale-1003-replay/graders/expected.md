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

# Expected `buyback:` — ale-1003-replay

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-10-03**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required.

## Must state

- Whatever it says about the programmes is consistent with this picture: Phase II is the current
  programme, with a price cap of **PLN 50** per share, and Phase I has ended. Three answers are
  equally correct: this picture stated as confirmed; the same picture marked unconfirmed
  (`[UNVERIFIED]`) because its only source is a search-engine summary; or a status of
  `[UNVERIFIED]` with no programme detail, because no company report is among the inputs.
- If PLN 65 is mentioned, it is a **proposal** for a general meeting on 18 November 2026, not the
  cap in force.

## Must not state

- PLN 65 as the price cap in force.
- Phase I, or its raised PLN 50 cap, as the running programme.
- Any other cap for Phase II, or any other programme as the current one.

## Context

- Everything the inputs say about the buyback — Phase II's terms, Phase I's end, the PLN 65
  proposal — comes from one search-engine summary (file `03`); no company current report is among
  them. Under a spec that accepts such summaries the picture can be stated as confirmed; under one
  that does not, it cannot. Both readings pass; only a wrong picture fails.

## Not decisive

- Phase II's size (up to 42,105,263 shares and/or PLN 800 million) and window (from 23 September
  2026 to no later than 25 June 2027), and Phase I's outcome.

## Not required

- A current-report number for the programme — none of the inputs carries it.
- The executing broker — none of the inputs names one for Phase II.
