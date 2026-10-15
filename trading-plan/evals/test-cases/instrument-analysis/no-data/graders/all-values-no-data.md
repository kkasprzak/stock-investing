---
type: regex
name: all-values-no-data
pattern: '^symbol: .+\ntrend_MN_W1: \[NO DATA\].*\nmomentum_D1: \[NO DATA\].*\nkey_levels: \[NO DATA\].*\ntechnical_status: \[NO DATA\].*\ncondition: \[NO DATA\].*\ninvalidation: \[NO DATA\].*\ntechnical_stop: \[NO DATA\].*\nscore: \[NO DATA\].*\nnote: \[NO DATA\].*\s*$'
weight: 2
---

On an all-`[NO DATA]` snapshot every line except `symbol` carries `[NO DATA]` (SKILL.md:39-40).
`symbol` is the ticker as given. Anchored to the whole output, so order and prose-free are
enforced too.
