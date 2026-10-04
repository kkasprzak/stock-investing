---
type: llm
name: buyback-matches-reference
weight: 3
---

You are judging one answer from the `instrument-research` skill. Judge **only its `buyback` field**
against the reference below.

PASS only if that field satisfies every item under "Must state" and contradicts no item under
"Must not state". Ignore everything under "Not required". Wording, order, formatting, a leading
status token or its absence, and the facet's other fields may all differ. If a required claim cannot
be settled from the answer alone, FAIL.

# Expected `buyback:` — ale-1003-replay

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-10-03**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required. Wording, order, format and the other fields of the facet are
free; no particular status token is required.

## Must state

- Phase II is the current programme: up to 42,105,263 shares, price not exceeding **PLN 50**
  per share, up to PLN 800 million, starting 23 September 2026 and ending no later than
  25 June 2027.
- Phase I has ended; it is not the current programme.
- PLN 65 is a **proposal** — a higher maximum price put to shareholders at a general meeting on
  18 November 2026 — not the current cap.

## Must not state

- PLN 65 as the price cap in force.
- Phase I, or its raised PLN 50 cap, as the running programme.

## Not required

- A current-report number for the programme — none of the inputs carries it.
- The executing broker — none of the inputs names one for Phase II.
