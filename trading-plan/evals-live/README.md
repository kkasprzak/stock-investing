# Live evals

Cases that run against the real web. The replays under `../evals/` freeze their inputs, so they test
how a skill **reads** sources. They cannot test whether it **reaches** good ones. These cases can.

```bash
make live                 # 3 runs per case, WebSearch and WebFetch granted for this call only
make live LIVE_RUNS=5
```

This is its own eval dir because the runner grants tools per invocation, not per case.
`--allow-tools` in a shared directory would give the network to every replay as well.

Two things to know before reading a result:

- **It is not reproducible.** The web moves. A live result is a measurement of one day, not a
  regression baseline, which is why `make evals` never runs these cases.
- **Its reference goes stale.** `expected.md` is written from the company's report list on the day
  it is written. Once a newer report on the same matter appears, the reference is wrong. Re-read the
  list and update the file before you run.

## `events-live-ale`

The question: does a live `events` run on ALE.PL open the company's own reports, and does it get
the buyback right from them? Three graders:

- `fetched-company-source` (trace): it opened a page on the company's domain, or an ESPI report or
  report list. A search summary that only mentions one does not count.
- `buyback-structure`: the field's five lines, in order.
- `expected.md` (judge): the buyback as the newest reports state it.
