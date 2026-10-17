Hand-built outputs for calibrating the `technical-stop-below-last-close` judge
(`test-cases/instrument-analysis/contract-shape/graders/stop-side.md`). The last close in the
KTY.PL fixture is 1204.

| file | technical_stop | expected |
|---|---|---|
| S1.txt | 1180 | PASS |
| S2.txt | 1204 (equal to the last close) | FAIL |
| S3.txt | 1230 | FAIL |
| S4.txt | 1174, a real model output verbatim | PASS |
| S5.txt | 1230, S4 with the stop moved | FAIL |

S1–S3 are built on `stop-differs/A.txt`. The verdicts the script checks live in `expected.tsv`; the table above is for reading.
Run `make calibrate GRADER=stop-side`. No `case.yaml` here, the runner ignores this directory.
