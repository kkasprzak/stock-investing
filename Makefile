# stock-investing — evals and tests
#
#   make            list the targets
#   make evals      run the eval suite and recover raw outputs
#   make test       run the offline unit tests
#
# `claude plugin eval` is in early access and gated per organisation. If it is not
# enabled for you, the run says so in its own words. Whatever your environment needs
# in order to enable it belongs in your shell, in ~/.claude/settings.json under `env`,
# or in evals.local.mk — a gitignored file included below, so nothing local to your
# machine or your organisation ends up committed here.

PLUGIN      := ./trading-plan
EVALS       := trading-plan/evals
OUT         := $(EVALS)/output
RESULTS     := $(OUT)/results
EXTRACT     := python3 $(EVALS)/scripts/extract_outputs.py
SKILLS      := trading-plan/skills
LIVE_OUT    := trading-plan/evals-live/output

RUNS        ?= 5
CASE        ?=
ABLATION    ?= none
MAX_COST    ?= 12
THRESHOLD   ?=
JUDGE_MODEL ?= claude-sonnet-5-5
CONCURRENCY ?= 4
LIVE_RUNS   ?= 3

-include evals.local.mk

CASE_FLAG   := $(if $(CASE),--case $(CASE),)
THRESH_FLAG := $(if $(THRESHOLD),--threshold $(THRESHOLD),)
EVAL_CMD     = claude plugin eval $(PLUGIN) \
                 --runs $(RUNS) \
                 --ablation $(ABLATION) \
                 --max-cost-usd $(MAX_COST) \
                 --judge-model $(JUDGE_MODEL) \
                 --concurrency $(CONCURRENCY) \
                 --scaffold \
                 --keep-temp \
                 --no-publish \
                 --output-dir $(RESULTS) \
                 $(CASE_FLAG) \
                 $(THRESH_FLAG)

.PHONY: help evals quick case baseline live outputs report test clean clean-temp check

help:
	@echo "stock-investing"
	@echo
	@echo "  make evals               eval suite, $(RUNS) runs per case, then recover raw outputs"
	@echo "  make quick               one run per case — a smoke check"
	@echo "  make case CASE=no-data   one named case (directory name under $(EVALS)/test-cases)"
	@echo "  make baseline            also run a no-plugin arm and report the score delta"
	@echo "  make live                the live suite (evals-live/): real web, $(LIVE_RUNS) runs — not reproducible"
	@echo "  make outputs             re-run the extractor over the last results, no model calls"
	@echo "  make report              open the HTML report from the last run"
	@echo "  make test                offline unit tests for every skill"
	@echo "  make clean               remove $(OUT) and any kept eval sandboxes"
	@echo
	@echo "  variables: RUNS=$(RUNS) ABLATION=$(ABLATION) MAX_COST=$(MAX_COST) CASE=$(CASE) THRESHOLD=$(THRESHOLD)"
	@echo "             JUDGE_MODEL=$(JUDGE_MODEL) CONCURRENCY=$(CONCURRENCY)"
	@echo "  example:   make evals RUNS=10 MAX_COST=12"

# No pre-flight gate check: `--help` answers even when the command is gated off, and the
# gate itself only fires once there is real work to do, so there is nothing cheap to probe.
# If eval is not enabled, the run below says so in its own words — trust that message.
check:
	@command -v claude >/dev/null 2>&1 || { echo "claude not on PATH"; exit 1; }
	@test -d $(EVALS)/test-cases || { echo "no $(EVALS)/test-cases"; exit 1; }

evals: check
	@echo "==> $(RUNS) run(s) per case, ablation=$(ABLATION), ceiling \$$$(MAX_COST)"
	@echo "$(strip $(EVAL_CMD))"
	@# Extract even when the eval exits non-zero: a failed grader is exactly when the raw output
	@# is needed. The eval's exit status is kept and returned afterwards, so CI still fails.
	@$(EVAL_CMD); status=$$?; $(EXTRACT); exit $$status

quick:
	@$(MAKE) --no-print-directory evals RUNS=1 MAX_COST=2

case:
	@test -n "$(CASE)" || { echo "usage: make case CASE=<directory name>"; exit 1; }
	@$(MAKE) --no-print-directory evals RUNS=$(RUNS) CASE=$(CASE)

baseline:
	@$(MAKE) --no-print-directory evals ABLATION=with-without MAX_COST=12

# The live suite is its own eval dir because the web is granted per invocation, not per case:
# --allow-tools here would hand the network to every replay if they shared a directory. Its
# results are not reproducible — the web moves — so it never runs as part of `make evals`.
live: check
	@claude plugin eval $(PLUGIN) --eval-dir evals-live \
	    --allow-tools WebSearch WebFetch --ablation none \
	    --runs $(LIVE_RUNS) --max-cost-usd $(MAX_COST) --judge-model $(JUDGE_MODEL) \
	    --concurrency $(CONCURRENCY) --keep-temp --no-publish \
	    --output-dir $(LIVE_OUT)/results; \
	  status=$$?; $(EXTRACT) $(LIVE_OUT)/results $(LIVE_OUT)/runs; exit $$status

outputs:
	@$(EXTRACT)

report:
	@test -f $(RESULTS)/report.html || { echo "no report — run \`make evals\` first"; exit 1; }
	@open $(RESULTS)/report.html 2>/dev/null || echo "$(RESULTS)/report.html"

# Discovered per skill: the tests/ dirs are not packages, so a single discover from
# $(SKILLS) would not descend into them.
test:
	@for d in $(SKILLS)/*/tests; do \
	  [ -d "$$d" ] || continue; \
	  echo "==> $$d"; \
	  python3 -m unittest discover -s "$$d" || exit 1; \
	done

clean: clean-temp
	rm -rf $(OUT) $(LIVE_OUT)

# --keep-temp leaves sealed sandboxes behind; they are mode 000 and need a chmod first.
clean-temp:
	@for d in /private/tmp/e-*; do \
	  [ -d "$$d" ] || continue; \
	  chmod -R u+rwx "$$d" 2>/dev/null || true; \
	  rm -rf "$$d" 2>/dev/null || true; \
	done; \
	echo "removed kept eval sandboxes under /private/tmp"
