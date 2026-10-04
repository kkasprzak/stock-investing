#!/usr/bin/env bash
# Stage this case's web results into ./sources/ in the eval sandbox.
# PROVENANCE.md stays out: it states the ground truth. (expected.md lives with the case, not here.)
set -euo pipefail
case_name="$(basename "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../fixtures/instrument-research/$case_name" && pwd)"
mkdir -p ./sources
for f in "$src"/*; do
  case "$(basename "$f")" in PROVENANCE.md) continue ;; esac
  cp "$f" ./sources/
done
echo "scaffold: $(ls ./sources | wc -l | tr -d ' ') source(s) from $case_name -> $PWD/sources" >&2
