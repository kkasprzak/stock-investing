# Evals

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
make evals THRESHOLD=0.9    # let a weighted score below 1 still pass — see below
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
`runs/` follows suit: the extractor clears it before writing, so it always holds exactly one
invocation. Before that, a one-run eval overwrote `run1` and left `run2…run5` from an earlier
eval in place, and the directory read as one series when it was two. Nothing here keeps
history — copy `output/` aside if you need a run to survive the next one.

`--scaffold` is **required**. Without it the fixture never reaches the sandbox, the model emits
a `[NO DATA]` block, and the `no-data` case passes for entirely the wrong reason.

`--keep-temp` is **required** if you want the raw outputs: the runner records score, cost and
duration but not the response text, which lives only in `trace.jsonl` inside the scaffold
directory that is deleted after each run. `extract_outputs.py` recovers it into `runs/`.
The Makefile extracts even when the eval exits non-zero — a failing grader is exactly when the
raw output is needed — and still returns the eval's exit status, so CI fails as it should.

`--threshold` (`THRESHOLD=` in the Makefile) sets the score a case must reach; the default is 1.
With the default every grader is a gate and weights only move the score. Below 1, weights decide
which failures pass: at 0.9 a failed weight-1 grader leaves 0.93 and passes, a failed weight-2
one leaves 0.875 and does not. The table's `PASS%` column is a separate, stricter measure — the
share of runs in which *every* grader passed — and does not move with the threshold. CI gates on
the score; watch `PASS%` so a tolerance does not hide a trend.

## Which model runs what

Two models are in play, and neither is the one a skill's frontmatter names.

**The agent.** `model:` in a skill's `SKILL.md` does **not** reach an eval: every step of a run —
the skill call, each read, the answer — goes to the agent's model, which is the runner's default
unless the case sets `execution.model`. Read a trace's `model` fields before trusting any claim
about it. Two earlier commits got this wrong: `d9719d6` put a behaviour change between two runs
down to the `sonnet` alias moving, and `24675c5` said its trace confirmed the evals ran on the
pinned Sonnet. Both runs were in fact executed by the default model; the change more likely came
from that default moving (Opus 5 → 5.5) than from the alias. A case that must reproduce a specific
run — every `instrument-research` replay — therefore pins `execution.model` to the model that run
used.

**The judge.** `type: llm` graders are decided by a separate model, three votes, majority wins.
The runner's default judge is Haiku; the Makefile sets `JUDGE_MODEL=claude-sonnet-5-5` instead,
because calibration showed Haiku cannot be trusted with a full answer. Fed one known-good
`buyback:` field on its own, Haiku passed it six times out of six; fed the same field inside the
whole seven-field answer it was taken from — about 5,000 characters, which is what a real run
hands the judge — it failed it six times out of six. Sonnet 5.5 got every calibration text right,
both directions, including a full known-bad answer: 36 of 36 votes, about a cent per verdict.

The lesson generalises: calibrate a judge on what it will actually be shown. A calibration that
hands it a trimmed excerpt is an easier test than the real one, and passes judges that will not.

## Layout

```
fixtures/<skill>/                     input, one directory per skill under test
test-cases/<skill>/<case>/case.yaml   the case: scaffold_script + prompt
test-cases/<skill>/<case>/scaffold.sh stages the fixture into the sandbox
test-cases/<skill>/<case>/graders/    graders, one file per assertion
scripts/                         extract_outputs.py
output/runs/                     recovered raw outputs + index.tsv
output/results/                  runner artifacts (pass --output-dir)
```

Modelled on `skills/stock-market-data/tests/fixtures` — the same split between the input data
and the thing that checks it. Both trees are split by skill, one directory per case; the runner
discovers cases recursively (`<eval dir>/**/case.yaml`), so the nesting costs nothing, and
`make case CASE=<name>` still filters by the case's name, not its path.

Two constraints the runner imposes, both learned the hard way:

- `scaffold_script` names a path **inside the case directory** — `../scripts/stage.sh` is
  rejected as escaping it, and the value is a path, not inline shell. Hence a `scaffold.sh`
  per case, each anchoring on its own location to reach `../../../fixtures/<skill>/`.
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
`fixtures/instrument-analysis/` unedited. Never hand-assemble one — a hand-made fixture measures an idea of the
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

## instrument-research: the buyback fix, before and after

The commit that adds this section fixes the test set for the comparison: from here until the
"after" line below, no case, fixture or reference changes — only the spec. A test changed after
seeing its result proves nothing.

**Before the fix** — 2026-10-04, at `4b831cb`, current spec, `claude-sonnet-5`, judge Sonnet 5.5,
five runs each: `ale-0926-replay` 0/5 (0.40), every failure the 26 Sep error — a certain status
resting on search summaries, the AGM authorisation read as the programme, Phase I's raised cap
given as live; `ale-0829-recon` 0/5; controls `ale-0905-replay` 5/5, `ale-1003-replay` 4/5 (re-measured at `da98400`, see below),
`ale-0921-evening-recon` 4/5 (one run called a completed programme "active"); `events-shape` 0/5,
by construction.

`ale-1003-replay`'s reference was corrected after this line was first written and before any
result on the new spec existed: it had required a conclusion resting on a search-engine summary,
which the fix declares is not a source, so the control would have failed for obeying the fix. It
was re-measured on the current spec at `da98400`: 4/5 (0.88). The one failure is the judge's, not
the model's — asked to explain itself, the judge opens with FAIL and then concludes the answer is
correct; the runner asks for one word, so the second thought is lost. The same reference grades
both arms.

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
