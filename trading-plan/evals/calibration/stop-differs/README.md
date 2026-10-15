Hand-built outputs for calibrating the `invalidation-differs-from-stop` judge
(`test-cases/instrument-analysis/contract-shape/graders/stop-differs.md`). Built on the KTY.PL
fixture; only `invalidation`, `technical_stop`, `note` differ between them.

| file | invalidation / technical_stop | note | expected |
|---|---|---|---|
| A.txt | 1195 / 1168 | justifies the stop | PASS |
| B.txt | 1195 / 1195 | silent on the equality | FAIL |
| C.txt | 1195 / 1195 | says the structure leaves no room | PASS |
| D.txt | 1195 / 1195 | explains something unrelated | FAIL |

Not part of any case: no `case.yaml` here, the runner ignores this directory.
