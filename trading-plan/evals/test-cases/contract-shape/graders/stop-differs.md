---
type: regex
name: invalidation-differs-from-stop
pattern: 'invalidation:\s*([0-9]+(?:\.[0-9]+)?)[\s\S]*?technical_stop:\s*\1(?![0-9.])'
match: 'not_contains'
weight: 2
---

SKILL.md calls one number for both an outright defect.

KNOWN DEFECT: this grader does not know the documented exception — equal values are
admissible when the structure leaves no room between them and `note` says so. It will
fail a compliant output. See README, Status.
