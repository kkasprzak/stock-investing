#!/usr/bin/env python3
"""Check an `llm` grader's criterion against samples whose verdict is known.

An `llm` grader is a prompt for a judge model, and a judge can be wrong without saying so. Before a
green run means anything, the judge has to be shown it can tell a good answer from a bad one. Each
directory under evals/calibration/ holds samples (outputs of the skill, `<name>.txt`) and an
`expected.tsv` (`<name><TAB>PASS|FAIL`). The directory's name is the grader's file name.

    python3 trading-plan/evals/scripts/calibrate_judge.py stop-side
    python3 trading-plan/evals/scripts/calibrate_judge.py stop-side --votes 5 --model claude-sonnet-5-5
    python3 trading-plan/evals/scripts/calibrate_judge.py stop-side --dry-run     # no model calls

For every sample it builds the judge's prompt from the grader's criterion and the sample, asks
the model `--votes` times, and compares each vote with the expected verdict. Exit status 1 if any
vote disagrees, 2 if the directory is inconsistent (a sample with no expected verdict or the other
way round). A vote that contains both PASS and FAIL is reported: the judge changed its mind, and
the runner, which asks for one word, would not see the change.

This approximates the runner, it is not the runner: the wording that asks for a verdict is ours.
The runner stays the final check (see README, "Calibrating a judge").

Costs about a cent per vote. Standard library only; needs the `claude` CLI.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)
CALIBRATION = os.path.join(EVALS, "calibration")

ASK = "Reply with exactly one word on the first line: PASS or FAIL. Then one sentence of reason.\n"


def criterion(grader_file):
    """The grader's body: what follows the frontmatter. Only `type: llm` graders are judged."""
    text = open(grader_file, encoding="utf-8").read()
    parts = text.split("\n---\n", 1)
    if not text.startswith("---\n") or len(parts) != 2:
        raise ValueError(f"{grader_file}: no frontmatter")
    if not re.search(r"(?m)^type:\s*llm\s*$", parts[0]):
        raise ValueError(f"{grader_file}: not a `type: llm` grader")
    return parts[1].strip()


def find_grader(name):
    hits = glob.glob(os.path.join(EVALS, "test-cases", "**", "graders", name + ".md"), recursive=True)
    if len(hits) != 1:
        raise ValueError(f"expected one grader file named {name}.md under test-cases/, found {len(hits)}")
    return hits[0]


def read_expected(directory):
    expected = {}
    path = os.path.join(directory, "expected.tsv")
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 2 or cols[1] not in ("PASS", "FAIL") or cols[0] in expected:
            raise ValueError(f"{path}:{n}: want `<sample><TAB>PASS|FAIL`, once per sample: {line!r}")
        expected[cols[0]] = cols[1]
    return expected


def check_consistent(directory, expected):
    on_disk = {os.path.splitext(f)[0] for f in os.listdir(directory) if f.endswith(".txt")}
    problems = []
    for s in sorted(on_disk - set(expected)):
        problems.append(f"{s}.txt has no expected verdict")
    for s in sorted(set(expected) - on_disk):
        problems.append(f"expected.tsv lists {s}, but {s}.txt does not exist")
    return problems


def build_prompt(crit, sample_text):
    return f"{crit}\n\n# Answer to judge\n\n{sample_text.rstrip()}\n\n{ASK}"


def parse_verdicts(output):
    """Every line that opens with PASS or FAIL, in order. Hook noise after the answer is dropped."""
    output = re.sub(r"SessionEnd hook.*", "", output, flags=re.S)
    return re.findall(r"(?m)^\W*(PASS|FAIL)\b", output)


def verdict_of(output):
    """(final verdict or '?', whether the vote contained both words)."""
    found = parse_verdicts(output)
    if not found:
        return "?", False
    return found[-1], len(set(found)) > 1


def vote(prompt, model):
    with tempfile.TemporaryDirectory() as cwd:
        done = subprocess.run(
            ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence"],
            input=prompt, capture_output=True, text=True, cwd=cwd, timeout=240,
        )
    return verdict_of(done.stdout + done.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("grader", help="directory name under evals/calibration/, also the grader's file name")
    ap.add_argument("--votes", type=int, default=3, help="votes per sample (default 3, as the runner)")
    ap.add_argument("--model", default="claude-sonnet-5-5", help="judge model (the Makefile's JUDGE_MODEL)")
    ap.add_argument("--dry-run", action="store_true", help="check the files and print one prompt; no model calls")
    args = ap.parse_args(argv)

    directory = os.path.join(CALIBRATION, args.grader)
    try:
        crit = criterion(find_grader(args.grader))
        expected = read_expected(directory)
        problems = check_consistent(directory, expected)
    except (ValueError, OSError) as e:
        print(f"calibrate: {e}", file=sys.stderr)
        return 2
    if problems:
        print(f"calibrate: {directory} is inconsistent:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 2

    samples = sorted(expected)
    texts = {s: open(os.path.join(directory, s + ".txt"), encoding="utf-8").read() for s in samples}
    if args.dry_run:
        print(f"{args.grader}: {len(samples)} samples, {len(samples) * args.votes} votes would be asked "
              f"of {args.model}\n")
        print(build_prompt(crit, texts[samples[0]]))
        return 0

    jobs = [(s, build_prompt(crit, texts[s])) for s in samples for _ in range(args.votes)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: vote(j[1], args.model), jobs))

    bad = 0
    for i, s in enumerate(samples):
        votes = results[i * args.votes:(i + 1) * args.votes]
        line = " ".join(v[0] for v in votes)
        flips = sum(1 for v in votes if v[1])
        ok = all(v[0] == expected[s] for v in votes)
        bad += 0 if ok else 1
        note = "" if ok else "   <-- DISAGREES"
        if flips:
            note += f"   ({flips} vote(s) said both PASS and FAIL)"
        print(f"  {s:<4} expected {expected[s]}   votes {line}{note}")
    total = len(jobs)
    right = sum(1 for (s, _), v in zip(jobs, results) if v[0] == expected[s])
    print(f"\n{args.grader}: {right} of {total} votes as expected, judge {args.model}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
