---
type: regex
name: exactly-ten-contract-lines
pattern: '^(?:symbol|trend_MN_W1|momentum_D1|key_levels|technical_status|condition|invalidation|technical_stop|score|note):'
flags: 'gm'
match: 'count:10'
weight: 2
---

Exactly ten contract lines, each a `key:` at the start of a line.
