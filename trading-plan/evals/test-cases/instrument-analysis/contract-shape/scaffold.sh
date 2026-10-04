#!/usr/bin/env bash
# Stage the fixture into the eval sandbox's working directory.
# Invoked by `claude plugin eval --scaffold` via context.scaffold_script.
# Anchors on its own location, so it does not depend on cwd.
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../fixtures/instrument-analysis" && pwd)/KTY.PL.json"
[ -f "$src" ] || { echo "scaffold: missing $src" >&2; exit 1; }
cp "$src" "./KTY.PL.json"
echo "scaffold: KTY.PL.json -> $PWD" >&2
