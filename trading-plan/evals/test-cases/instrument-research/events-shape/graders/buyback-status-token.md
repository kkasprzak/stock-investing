---
type: regex
name: buyback-status-token
pattern: '^\s+status:\s+(running|completed|expired|announced|\[N/A\]|\[UNVERIFIED\])'
flags: 'm'
weight: 2
---

The `buyback` field's `status:` line opens with a token from the closed vocabulary. Any indent and
any run of spaces after the key: the model aligns columns, and the contract is the token, not the
spacing.
