---
type: regex
name: fixture-was-read
target: trace
pattern: '~15min provider data'
weight: 2
---

Tests the harness, not the model. The string comes verbatim from the fixture
(`SPCX.US.json`, field `delayed`), so it reaches the trace only when `Read` returned the file.
If the scaffold failed to stage it, the output may still look compliant (all `[NO DATA]`) —
this grader is what tells the two apart.
