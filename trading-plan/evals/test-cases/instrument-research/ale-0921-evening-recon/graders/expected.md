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

# Expected `buyback:` — ale-0921-evening-recon

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-09-21, evening**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required.

## Must state

- Phase I has **completed**, as the company has reported.
- There is **no current programme** in the inputs: nothing announces a phase after Phase I.

## Must not state

- A running programme, or any cap — PLN 45 or the raised PLN 50 — as a cap currently in force.
- A Phase II, or any detail of one.

## Context

- The company's report of Phase I's end gives 17,879,330 shares, about PLN 800 million, an average
  of about PLN 44.74, and a last transaction on 21 September 2026. None of these figures is required.

## Not required

- Report numbers, the executing broker, or the AGM authorisation's terms (the inputs carry the
  resolution's adoption, not its terms).
