#!/usr/bin/env python3
"""Recover each eval run's raw model output from trace.jsonl into a file.

The runner records score, cost and duration in aggregate-result.json but NOT the response
text — that lives only in trace.jsonl inside the scaffold directory, which is deleted after
each run. So the eval must run with --keep-temp, and then this script.

    claude plugin eval ./trading-plan --runs 5 --keep-temp --scaffold \
        --output-dir trading-plan/evals/output/results
    python3 trading-plan/evals/scripts/extract_outputs.py

Defaults to the newest run under evals/output/results/. Replaces evals/output/runs/ with:

    <case>__run<N>.txt     the raw output, one file per run
    index.tsv              case, run, score, cost, duration, file

Standard library only, no dependencies.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)
OUTPUT = os.path.join(EVALS, "output")
RESULTS = os.path.join(OUTPUT, "results")
RUNS = os.path.join(OUTPUT, "runs")


def latest_results_dir():
    """Newest run under output/results — or that directory itself.

    With --output-dir the runner writes aggregate-result.json straight into the given
    directory; without it, into a <timestamp>/ subdirectory. Handle both.
    """
    if not os.path.isdir(RESULTS):
        sys.exit(f"no {RESULTS} — run `claude plugin eval` with "
                 f"--output-dir trading-plan/evals/output/results first")
    if os.path.isfile(os.path.join(RESULTS, "aggregate-result.json")):
        return RESULTS
    dirs = [d for d in sorted(os.listdir(RESULTS))
            if os.path.isfile(os.path.join(RESULTS, d, "aggregate-result.json"))]
    if not dirs:
        sys.exit(f"no aggregate-result.json under {RESULTS}")
    return os.path.join(RESULTS, dirs[-1])


def final_text(trace_path):
    """The last non-empty assistant text block in trace.jsonl."""
    last = None
    try:
        fh = open(trace_path)
    except OSError as e:
        return None, f"[trace unreadable: {e}]"
    with fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    last = block["text"]
    return last, None if last else "[no assistant text in trace]"


def main():
    run_dir = sys.argv[1] if len(sys.argv) > 1 else latest_results_dir()
    with open(os.path.join(run_dir, "aggregate-result.json")) as f:
        agg = json.load(f)

    # runs/ must hold exactly one invocation. Left alone, a 1-run eval overwrites run1 and
    # leaves run2..runN from an earlier eval in place, and the directory reads as one series
    # when it is two. Cleared only after a result was found above, so a failed lookup
    # never wipes the last good outputs.
    shutil.rmtree(RUNS, ignore_errors=True)
    os.makedirs(RUNS)
    rows = []
    for case in agg.get("cases", []):
        name = case["name"]
        for arm, runs in case.get("arms", {}).items():
            for i, run in enumerate(runs, 1):
                stem = f"{name}__run{i}" if arm == "with" else f"{name}__{arm}__run{i}"
                path = os.path.join(RUNS, stem + ".txt")
                trace = run.get("tracePath") or ""
                text, problem = final_text(trace) if trace else (None, "[no tracePath]")
                header = (
                    f"# case: {name}\n"
                    f"# arm: {arm}   run: {i}\n"
                    f"# score: {run.get('score')}   passed: {run.get('passed')}\n"
                    f"# cost_usd: {run.get('costUsd')}   duration_s: {run.get('durationSeconds')}\n"
                    f"# started: {run.get('startedAt')}\n"
                    f"# trace: {trace}\n"
                    f"# error: {run.get('error')}\n"
                    "# " + "-" * 68 + "\n"
                )
                with open(path, "w") as out:
                    out.write(header + (text if text else problem) + "\n")
                rows.append((name, arm, i, run.get("score"), run.get("costUsd"),
                             run.get("durationSeconds"), problem or "", stem + ".txt"))

    index = os.path.join(RUNS, "index.tsv")
    with open(index, "w") as f:
        f.write("case\tarm\trun\tscore\tcost_usd\tduration_s\tproblem\tfile\n")
        for r in rows:
            f.write("\t".join("" if v is None else str(v) for v in r) + "\n")

    print(f"source:  {run_dir}")
    print(f"wrote {len(rows)} run(s) to {RUNS}")
    missing = [r for r in rows if r[6]]
    if missing:
        print(f"WARNING: {len(missing)} with no text — was the eval run with --keep-temp?")
        for r in missing:
            print(f"  {r[7]}: {r[6]}")


if __name__ == "__main__":
    main()
