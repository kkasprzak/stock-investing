---
type: regex
name: exactly-ten-contract-lines-in-order
pattern: '^symbol: .+\ntrend_MN_W1: .+\nmomentum_D1: .+\nkey_levels: .+\ntechnical_status: .+\ncondition: .+\ninvalidation: .+\ntechnical_stop: .+\nscore: .+\nnote: .+\s*$'
weight: 2
---

Exactly ten contract lines, each a `key:` at the start of a line.
