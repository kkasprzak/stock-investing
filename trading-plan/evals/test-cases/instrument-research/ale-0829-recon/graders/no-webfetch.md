---
type: tool_used
name: no-webfetch
tool: WebFetch
min: 0
max: 0
arm: both
weight: 1
---

A replay must read only ./sources/. `allowed_tools` pre-approves tools rather than restricting them,
so a live WebFetch call would turn the replay into a live test without anyone noticing.
