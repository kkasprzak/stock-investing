# Evals — instrument-analysis

These measure the **model's output**, not the code. The unit tests under
`skills/stock-market-data/tests` check that a function computes what it claims; here we check
that the model honours a contract whose output is stochastic by nature — the same snapshot run
five times can read differently.

The runner ships with Claude Code (`claude plugin eval`), so there is no harness of our own
here — only cases, graders, and one script that recovers raw outputs.

## Running

```bash
make evals                  # the suite, 5 runs per case, then recover raw outputs
make quick                  # one run per case — a smoke check
make case CASE=no-data      # a single case
make evals RUNS=10 MAX_COST=12
```

`make` with no target lists them. What `make evals` actually runs:

```bash
claude plugin eval ./trading-plan --runs 5 --scaffold --keep-temp --ablation none \
    --output-dir trading-plan/evals/output/results
python3 trading-plan/evals/scripts/extract_outputs.py
```

Every flag below is load-bearing, which is why the Makefile exists.

`--output-dir` keeps the runner's artifacts inside `output/`, the one directory that is
gitignored. Drop the flag and they land in `evals/results/` instead — outside the ignore, so
they show up as untracked noise. It also flattens the layout: with the flag the runner writes
`aggregate-result.json` and `report.html` straight into that directory, so **each run
overwrites the previous one**; without it, every run gets its own `<timestamp>/` subdirectory.
Keep the flag and keep the history in `runs/` instead, which is what the extractor is for.

`--scaffold` is **required**. Without it the fixture never reaches the sandbox, the model emits
a `[NO DATA]` block, and the `no-data` case passes for entirely the wrong reason.

`--keep-temp` is **required** if you want the raw outputs: the runner records score, cost and
duration but not the response text, which lives only in `trace.jsonl` inside the scaffold
directory that is deleted after each run. `extract_outputs.py` recovers it into `runs/`.

## Layout

```
fixtures/                        input — candle snapshots, one file per instrument
test-cases/<case>/case.yaml      the case: scaffold_script + prompt
test-cases/<case>/scaffold.sh    stages the fixture into the sandbox
test-cases/<case>/graders/       graders, one file per assertion
scripts/                         extract_outputs.py
output/runs/                     recovered raw outputs + index.tsv
output/results/                  runner artifacts (pass --output-dir)
```

Modelled on `skills/stock-market-data/tests/fixtures` — the same split between the input data
and the thing that checks it. One directory per case, all of them under `test-cases/`; the
runner discovers them recursively (`<eval dir>/**/case.yaml`), so the nesting costs nothing.

Two constraints the runner imposes, both learned the hard way:

- `scaffold_script` names a path **inside the case directory** — `../scripts/stage.sh` is
  rejected as escaping it, and the value is a path, not inline shell. Hence a `scaffold.sh`
  per case, each anchoring on its own location to reach `../../fixtures/`.
- Unknown top-level keys in `case.yaml` are **silently ignored**. A misplaced key looks like
  working configuration and does nothing — `scaffold_script` belongs under `context:`, not at
  the top level and not under `execution:`.

## Fixture provenance

**These are not invented or hand-assembled.** Both files are unedited captures of the snapshot
a calling orchestrator hands an `instrument-analysis` subagent — the same bytes, frozen on
**2026-09-13**.

That is the only reason these evals measure anything useful: the input has the same shape the
skill actually receives. A snapshot composed by an agent "to match the description in SKILL.md"
looks different — verified, two sessions of the same skill produced two different formats.

File shape:

```json
{
 "symbol": "KTY.PL",
 "delayed": "~15min provider data; candles unadjusted for dividends",
 "D1": { "last_closed": {"date": "...", "c": 0.0}, "bars": [ {date,o,h,l,c,v,complete} ] },
 "W1": { ... },
 "MN": { ... }
}
```

Constants of this capture: **D1 = 30 bars, W1 = 26, MN = 24**. D1 and W1 fully closed; the
current month in MN carries `complete: false` — an ordinary state, not an anomaly.

`SPCX.US.json` is an actual `[NO DATA]` capture: all three timeframes hold
`{"status": "[NO DATA]", "reason": "not_found"}`. Note that `[NO DATA]` arrives **per
timeframe**, not only as a whole-snapshot state.

A fixture carries market data and nothing else: symbol, candles, last close. Quantities, entry
prices, stop levels, P&L and equity have no place in one — the skill's contract forbids feeding
it any level a caller already holds, precisely so that its `technical_stop` is arrived at
independently and a divergence from the caller's own level stays meaningful.

## Refreshing fixtures

When the snapshot shape changes, re-capture from the same source and swap the files into
`fixtures/` unedited. Never hand-assemble one — a hand-made fixture measures an idea of the
input rather than the input.

## What these graders do not check

The suite is young and its coverage is uneven — worth knowing before reading a green run as
proof of anything.

`invalidation-differs-from-stop` does not know the exception `SKILL.md` documents: one number
for both is admissible when the structure leaves no room between them and `note` says so. It
will fail an output that is in fact compliant.

Two invariants are not covered at all, and cannot be with the graders available: that
`technical_stop` sits on the correct side of the last close, and that `key_levels` fall within
the snapshot's price range. Both are numeric comparisons, and a `regex` grader matches patterns
rather than comparing values — expressing them needs a paid `llm` grader or a check outside the
runner.

The `no-data` case checks the shape of the block — ten keys, in order, nothing around them — but
not that the fixture was actually read. Its expected output is also what the model tends to emit
when the fixture never reached the sandbox, so it can pass whether or not the snapshot was
staged: run without `--scaffold` and it may go green for the wrong reason.

## Further reading

`claude plugin eval` is in early access and has **no public documentation** — the plugins
reference does not mention it, the docs index carries no eval page, and there is no dedicated
page to link. What the runner accepts was recovered from `--help`, from its own validation
errors, and from the schema it enforces. The two constraints called out under Layout are the
ones that cost the most to find.

Worth reading anyway:

- [Claude Code Plugin Eval: Catch a Skill That Never Activates](https://www.matthewswong.com/en/blog/claude-code-plugin-eval-test-suite/)
  — the best public write-up of the runner: a full worked case, the grader types, and how to
  read an ablation delta. Third-party, not official.
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  — Anthropic on designing evals in general: code-based versus model-based graders, and when
  human review is the only honest option. Not about this runner, but it is the reasoning behind
  why the graders here are split the way they are.
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — official, and the
  place to look for everything about plugin structure *except* evals.
