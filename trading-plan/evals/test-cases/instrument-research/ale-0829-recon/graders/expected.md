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

# Expected `buyback:` — ale-0829-recon

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-08-29**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required. Wording, order, format and the other fields of the facet are
free; no particular status token is required.

## Must state

- The running programme's price cap is **not established** from the inputs (unconfirmed /
  `[UNVERIFIED]`). Nothing in them gives a programme's cap, size, window or broker.
- PLN 1.6 billion and a price range up to PLN 50.00 are the terms of the **AGM authorisation**
  of 25 June 2026, and are described as that — not as a running programme.

## Must not state

- An active programme with a PLN 50 cap, PLN 1.6 billion size and a window from 25 June 2026 —
  that is the authorisation read as a programme.
- The 2025 employee-incentive buyback as current: by its own terms it ran from 21 November 2025
  to 31 May 2026.
- An executing broker for a 2026 programme — none is in the inputs (Santander belongs to the
  2025 programme).

## Not required

- Any report number, fills, or a programme status beyond "not established".
