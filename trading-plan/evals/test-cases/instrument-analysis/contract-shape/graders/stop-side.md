---
type: llm
name: technical-stop-below-last-close
weight: 2
---

You are judging one answer from the `instrument-analysis` skill. Judge **only the `technical_stop`
line**. Ignore every other line, and ignore wording, order and formatting.

The instrument is KTY.PL. Its last closed D1 candle closed at **1204** (2026-09-11). This is a
fact of the input, not something the answer has to state.

The skill is long-only: `invalidation` is the price whose close *below* breaks the structure, so
protection sits **below** the market. A `technical_stop` that is a single price **below 1204** is
on the correct side.

Before you decide, do the comparison explicitly in your reasoning: quote the `technical_stop`
line, say which number it holds, and say whether that number is smaller than 1204, equal to it,
or larger. Do not give a verdict until you have done that, and make the verdict follow from it.

PASS if `technical_stop` is a single number strictly **below 1204**.

FAIL if `technical_stop` is 1204 or higher, is not a number, or is a range or several numbers.
If you cannot settle it from the answer alone, FAIL.

DRAFT — coupled to the `KTY.PL` fixture: if `fixtures/instrument-analysis/KTY.PL.json` changes,
update the last close above. Assumes long-only, which SKILL.md implies through `invalidation`
(line 27) but does not state for `technical_stop`.
