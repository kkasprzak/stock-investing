---
type: llm
name: key-levels-within-snapshot-range
weight: 2
---

You are judging one answer from the `instrument-analysis` skill. Judge **only the `key_levels`
line**. Ignore every other line, and ignore wording, order and formatting.

The instrument is KTY.PL. Across every candle in its snapshot (D1, W1 and MN) the lowest price
is **658.5** and the highest is **1362**. These are facts of the input, not something the answer
has to state.

Levels are derived from the snapshot's own candles, so each must lie inside that range.

`key_levels` is often prose. Pick out the **prices** and ignore every other number: a day of the
month ("Aug 20", "Sep 3"), a year, a count and similar digits are not prices. A range such as
`1200-1201` holds two prices, both of which count.

Before you decide, do the comparison explicitly in your reasoning: list every price you found in
the line, and next to each say whether it is below 658.5, inside 658.5-1362, or above 1362. Do
not give a verdict until you have listed them all, and make the verdict follow from the list.

PASS if the line lists at least one price and **every** price is between 658.5 and 1362
inclusive.

FAIL if any price is below 658.5 or above 1362, or the line holds no price. One price outside the
range is a FAIL even when all the others are fine. If you cannot settle it from the answer alone,
FAIL.

DRAFT — coupled to the `KTY.PL` fixture: if `fixtures/instrument-analysis/KTY.PL.json` changes,
update the range above. The range is the widest one, the MN window; a level outside the D1 window
but inside MN still passes.
