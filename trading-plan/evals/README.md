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
from that default moving (Opus 5 → 5.5) than from the alias. While the buyback fix was
being measured, every `instrument-research` case pinned `execution.model` to the model the failing
runs used, `claude-sonnet-5`, so the error could reproduce. With the comparison closed the cases
follow the skill instead: `execution.model` is the model `SKILL.md` pins, `claude-sonnet-5-5`, so a
run measures what production runs. The two move together — change the pin, change this line in
every case. Checked before the switch: the replay and recon cases scored 25/25 on both models.

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
calibration/<grader>/            outputs with an expected verdict, for checking an llm judge
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

**Two cases, two instruments.** `instrument-analysis` is measured on `KTY.PL` (a full snapshot)
and `SPCX.US` (an all-`[NO DATA]` snapshot) and nothing else. A structure with no room between
`invalidation` and the stop, a clean breakout, a clean downtrend: none is in the set. That is
step 4, and it needs labels from someone who reads charts, not from the agent.

**The layer-2 judges are tied to one fixture.** `technical-stop-below-last-close` and
`key-levels-within-snapshot-range` carry the `KTY.PL` facts in their criterion (last close 1204,
price range 658.5–1362), because the judge sees the answer and not the snapshot. Re-capture the
fixture and both must be edited by hand. The range is the widest one, the MN window, so a level
outside the D1 window but inside MN passes.

**The stop's side is an inference.** `SKILL.md` defines `invalidation` as the price whose close
*below* breaks the structure, which makes the tool long-only, but it never says
`technical_stop` sits below the market. The grader assumes it does.

**Judges are checked on hand-built samples, not on the bounds.** Each judge was calibrated on
5–6 samples, three votes each, in two prompt shapes (verdict first, reasoning first): 66 of 66 as
expected (`calibration/`). No sample sits exactly on a bound — 1362, 658.5, a stop at 1203.99.

**A judge that decides before it counts is wrong on numbers.** Before the criteria told the
judge to list and compare every number first, 3 of 9 votes on a compliant `key_levels` line opened
with FAIL, and 3 of 3 on a stop above the close opened with PASS, each then correcting itself in
the next sentence. The runner asks for one word, so that correction would be lost. Both criteria
now ask for the comparison before the verdict; after that, no vote disagreed with its sample.

**Calibrate on text that looks like the real thing.** `key_levels` in a real output is prose with
dates and ranges (`support 1200-1201 (lows of Aug 20 and Sep 3), 1175 …`). The first, clean
samples would have passed a judge that mistakes `20` for a price.

**`no-data` now reads the fixture.** `fixture-was-read` greps the run's trace for a string taken
verbatim from `SPCX.US.json`, so it separates a compliant answer from a compliant answer
produced without the snapshot. Checked both ways on 2026-10-15: 5 of 5 green with the scaffold;
with a wrong file name in the prompt it went red in 2 of 5 while `all-values-no-data` and
`exactly-ten-contract-lines-in-order` stayed green in those same runs.

## instrument-analysis: baseline

Measured 2026-10-15 and 2026-10-16, plugin `0.7.0`, five runs per case, judge Sonnet 5.5.

| case | graders | runs passing | score | cost |
|---|---|---|---|---|
| `no-data` | 4 (all regex or trace) at `99959fc` | 5/5 | 1.00 | $0.35 |
| `contract-shape` | 10 (one `llm`) at `f753978` | 5/5 | 1.00 | $0.84 |
| `contract-shape` | 12 (three `llm`) at `a059803` | 5/5 | 1.00 | $1.17, of which judges $0.38 |

**There is no before-and-after here, and that is the result.** On 14 September, checking the raw
outputs by hand, `no-data` conformed to the contract in 2 of 5 runs (prose before and after the
block in two, wrong field order in one) while the suite showed 100%. The 15 October run, with
the order-and-nothing-around-it pattern in place, is 5 of 5. The two numbers are not the same
experiment: different plugin version (`0.2.0` then, `0.7.0` now), and the earlier one was
counted by hand. So the table does not say the skill got better, and nothing about `SKILL.md`
was changed to produce it. What it does say is that on these two snapshots the graders as they
stand find no defect, and the layer-2 invariants — the one place a drifting model would show — also
hold.

The measure-tighten-measure sequence therefore has nothing to tighten yet. It starts when a case
exists that the skill fails; that is what step 4's golden set is for.

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

**After the fix** — 2026-10-04, at `0eff4a4`, same tests, same model and judge, five runs each:

| case | before | 1 prose rule | 2 rule in the field | 3 + later events | 4 structured | 5 + programme line |
|---|---|---|---|---|---|---|
| `ale-0926-replay` | 0/5 | 0/5 | 1/5 | 1/5 | 3/5, pilot 4/5 | **5/5**, pilot 5/5 |
| `ale-0829-recon` | 0/5 | 3/5 | 5/5 | 5/5 | 5/5 | **5/5** |
| `ale-0905-replay` | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| `ale-1003-replay` | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| `ale-0921-evening-recon` | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |

The fix took five versions of the spec. Only the first (`bb03ba9`) and the last (`0eff4a4`) were
committed; the three between were measured on the working tree and are recorded only here, which
is the reason to keep them in the table. The first
three state a rule in prose: a search summary is not a source, then the same rule inside the
`buyback` field, then a sentence saying a later event known only from a summary leaves the newest
report out of date. The model read each one and reasoned around it. In `ale-0926-replay` it took a
14 September transaction report as "the latest report" and wrote `running`, while a summary in the
same inputs reported Phase II on 22 September.

What worked was making the evidence part of the output. The field now opens with
`latest_report_read` and `later_events_unread`, and the status follows from them. On the first
structured version every run of 0926 gave `[UNVERIFIED]`. Of its failures, two filed the
authorisation's PLN 1.6 bn as the programme's budget, which one more line on `programme` closed; the
third was the judge's (below).
A rule the model has to show its work for holds where a rule it only has to obey does not.

`events-shape` is not in the table: it says nothing about the fix. Its old regex allowed one space
after `buyback:`, the model aligns columns with several, and the case's instrument (V80A.DE, an ETF)
has no buyback, so both specs answer `[N/A]`. After the comparison closed it got two patterns for
the structured field: `buyback-status-token` reads the token on the `status:` line, at any indent,
and `buyback-structure` requires the five lines in order before `share_overhang:`. Checked offline
against the saved outputs of both arms, the structure pattern matches 0 of 30 answers on the prose
spec and 29 of 30 on the structured one; the one miss had dropped its `programme:` line. It is still
a format check on an instrument without a programme.

**The sub-keys, after 0.3.0.** Once the five replay and recon cases carried `buyback-structure`, it
failed answers that were right in substance but wrote a note between key and colon
(`later_events_unread (all from summaries):`). The grader stayed strict and the contract was
tightened in 0.3.1: each key exactly as written, the colon right after it. On `claude-sonnet-5-5`
that took the rate from 2 in 25 to 1 in 50, with ten runs per case and the judge at 50/50. The
remaining 2% is known and accepted. One more failure in that run was of a different kind: the model
indented the whole facet block, as `SKILL.md` shows it, so `^buyback:` did not match. The content
was right, and nothing downstream cares about indentation. Expect it as an occasional false red,
not as a defect.

The judge erred in both directions along the way. On the third version it passed an answer that gave
the status as confirmed. On the fourth it failed an answer that, asked to reason item by item, it
passed twice. Both are long answers near the line, and the runner takes one word per vote. A single
run of five is a sample, not a verdict: read the answers behind a score before acting on it.

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
