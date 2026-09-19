---
type: regex
name: score-is-bare-integer
pattern: '^score: (?:10|[0-9])[ \t]*$'
flags: 'm'
weight: 1
---

`score` as a bare int 0-10 — not "7/10", not a range, not a decimal.
