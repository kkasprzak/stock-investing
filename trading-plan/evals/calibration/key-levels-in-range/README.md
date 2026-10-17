Hand-built outputs for calibrating the `key-levels-within-snapshot-range` judge
(`test-cases/instrument-analysis/contract-shape/graders/key-levels-in-range.md`). The snapshot
range in the KTY.PL fixture is 658.5-1362.

| file | key_levels | expected |
|---|---|---|
| K1.txt | 1324, 1257, 1200, 1170 | PASS |
| K2.txt | adds 1450 (above) | FAIL |
| K3.txt | adds 600 (below) | FAIL |
| K4.txt | a real model output verbatim: prose, ranges, dates | PASS |
| K5.txt | K4 plus `1450 (projected target)` | FAIL |
| K6.txt | K4 plus `620 (Oct 2023 low)`, a price next to a date | FAIL |

K4 is the realistic one: the judge has to tell prices from `Aug 20` and `Sep 3`.
The verdicts the script checks live in `expected.tsv`; the table above is for reading.
Run `make calibrate GRADER=key-levels-in-range`. No `case.yaml` here, the runner ignores this directory.
