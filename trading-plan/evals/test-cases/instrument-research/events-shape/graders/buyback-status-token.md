---
type: regex
name: buyback-status-token
pattern: '^buyback: (running|completed|expired|announced|\[N/A\]|\[UNVERIFIED\])'
flags: 'm'
weight: 2
---

The `buyback` field opens with a status from the closed vocabulary. This is a contract check, not
evidence of the reading error the replay cases test: on a spec without the vocabulary it fails by
construction, which is why no replay case carries it.
