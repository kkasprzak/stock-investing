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

# Expected `buyback:` — ale-0905-replay

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-09-05**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required.

## Must state

- A buyback programme is running, and it is Phase I.
- Phase I's price cap is **PLN 45.00** per share, given as the running programme's cap.

## Must not state

- The AGM authorisation **attributed to the running programme**: saying that the programme now
  executing has a PLN 50 cap, a PLN 1.6 billion budget, or 84,210,526 shares, or that it began on
  25 June 2026. This is the one error to look for — the authorisation passing for the programme.
  Describing the authorisation's own terms is fine — its PLN 50.00 maximum ("cap" or "ceiling"),
  PLN 1.6 billion, 84,210,526 shares, its 25 June 2026 – 25 June 2027 window, even calling it
  active — as long as they are attributed to the authorisation (framework, envelope, parent
  mandate) and the running programme's own cap of PLN 45.00 is given as the programme's.
- The 2025 employee-incentive buyback as the current programme.

## Not decisive

- Size (up to PLN 800 million and/or 42,105,263 shares), window (from 15 July 2026 to no later
  than 25 June 2027), executing broker (Erste), last confirmed fills (for example 3–5 August 2026 at
  about PLN 44.67 / 44.71 / 44.97), and the programme's purpose or market.

## Not required

- A current-report number for the programme — none of the inputs carries it.
