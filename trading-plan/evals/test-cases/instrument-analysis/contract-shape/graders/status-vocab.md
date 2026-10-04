---
type: regex
name: status-closed-vocabulary
pattern: '^technical_status: (?:below trigger|after breakout|in decision zone)[ \t]*$'
flags: 'm'
weight: 1
---

`technical_status` exactly one of the three tokens, with nothing trailing.
