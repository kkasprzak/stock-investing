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

# Expected `buyback:` — events-live-ale

Reference for the `buyback` field of facet `events`, ALE.PL, as of the day of the run,
taken from Allegro's ESPI report list. Wording, order and format are free.

Written 2026-10-04 from the list as it stood that day. A newer report about the programme
makes this reference stale: re-read the list and update it before a run.

## Must state

- Status `running`, resting on a company report read in this run: Phase II of the
  programme, adopted 22 Sep 2026 (current report 51/2026).
- Phase II's price cap is PLN 50.00.
- PLN 65 is only a board recommendation (report 53/2026) for the general meeting on
  18 Nov 2026 — not the cap in force.

## Must not state

- Phase I as the running programme, or PLN 45 as the current cap.
- PLN 65 as the cap in force.
- PLN 1.6 bn as the running programme's budget.

## Not decisive

- Phase II's budget (PLN 800 m), share count (42,105,263), start (23 Sep 2026),
  broker (Erste), the latest transaction report (52/2026) and fills.

## Context

- Phase I ended 21 Sep 2026 (report 50/2026). The general meeting of 18 Nov 2026 was
  convened on 1 Oct (report 54/2026).
