---
type: llm
name: invalidation-differs-from-stop
weight: 2
---

You are judging one answer from the `instrument-analysis` skill. Judge **only three of its lines**:
`invalidation`, `technical_stop` and `note`. Ignore every other line, and ignore wording, order and
formatting.

The rule being checked: `invalidation` (the price whose close breaks the structure) and
`technical_stop` (where protection belongs) must be **different numbers**. One number for both is a
defect, with a single exception: the two may be equal when the structure leaves no room between
them **and `note` says so**.

PASS if either:
- `invalidation` and `technical_stop` are different numbers, or
- they are the same number **and** `note` states that the structure leaves no room between them
  (any wording that says the two levels coincide, collapse, or have no gap between them counts).

FAIL if:
- they are the same number and `note` does not say why, or
- the same number is repeated and `note` is silent on it or explains something unrelated.

Numbers are compared as values: `155` and `155.00` are the same number. If you cannot settle it
from the answer alone, FAIL.
