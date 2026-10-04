---
type: regex
name: buyback-structure
pattern: '^buyback:(?:(?!^share_overhang:)[\s\S])*?^\s+latest_report_read:(?:(?!^share_overhang:)[\s\S])*?^\s+later_events_unread:(?:(?!^share_overhang:)[\s\S])*?^\s+status:(?:(?!^share_overhang:)[\s\S])*?^\s+authorisation:(?:(?!^share_overhang:)[\s\S])*?^\s+programme:'
flags: 'm'
weight: 2
---

The `buyback` field carries its five lines, in order, before `share_overhang:` begins:
`latest_report_read`, `later_events_unread`, `status`, `authorisation`, `programme`. The order is
the point — the status follows from the two evidence lines above it — so a line moved or dropped
fails, even when the status itself is right. A company with no programme still writes all five.
