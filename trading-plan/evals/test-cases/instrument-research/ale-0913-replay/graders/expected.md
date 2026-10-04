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

# Expected `buyback:` — ale-0913-replay

Reference answer for the `buyback` field of facet `events`, ALE.PL, as of **2026-09-13**, derived
**only from the files in this case's fixture directory**. A fact that is true but absent from
those files is never required. Wording, order, format and the other fields of the facet are
free; no particular status token is required.

## Must state

- A buyback programme is running: Phase I of the 2026 open-market programme, for cancellation.
- Price cap **PLN 45.00** per share, attributed to that programme.
- Size: up to PLN 800 million and/or up to 42,105,263 shares.
- Window: from 15 July 2026, ending no later than 25 June 2027.
- Executing broker: Erste (Erste Bank Polska – Erste Biuro Maklerskie).
- Last confirmed fills with dates and prices, as the inputs carry them (3–5 August 2026 at about PLN 44.67 / 44.71 / 44.97).

## Must not state

- The AGM authorisation's terms — PLN 1.6 billion, a price range up to PLN 50.00, 84,210,526
  shares — as the programme's cap, size or window. If the authorisation is mentioned, it is
  described as the authorisation, apart from the programme.
- The 2025 employee-incentive buyback as the current programme.

## Not required

- A current-report number for the programme — none of the inputs carries it.
