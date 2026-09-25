#!/bin/bash
# End-to-end demo of labbook without Claude Code: builds a throw-away project, installs the framework
# and runs a small autonomous-style session -- a plan with two hypotheses on the explicit Euler method,
# two entries (one confirmed, one refuted), five runs, an analysis with a figure, metrics in the ledger,
# a session summary and the book. In a Claude Code session the assistant performs the same steps; the
# hooks then add the trace, the events and the protection on top.
#
#   examples/demo/run_demo.sh [TARGET_DIR]      (default: a new temporary directory)
#
# LB_DEMO_NO_BOOK=1 skips rendering the book even when Quarto is installed. Needs matplotlib.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PY=${PYTHON:-python3}
T=${1:-$(mktemp -d)/demo-project}
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fill() { "$PY" "$HERE/fill.py" "$@"; }
LB() { "$PY" tools/lb.py "$@"; }

step "1. A small project under git: $T"
mkdir -p "$T/src"
cp "$HERE/decay.py" "$T/src/decay.py"
cd "$T"
git init -q
git config user.name "labbook demo"; git config user.email "demo@example.org"
git add -A && git commit -qm "decay model"

step "2. Install labbook (tool, hooks, skill, notebook skeleton)"
bash "$REPO/install.sh" "$T"
"$PY" - <<'PY'
from pathlib import Path
import shutil
p = Path(".claude/labbook.toml"); t = p.read_text()
t = t.replace('title = "Lab notebook"', 'title = "labbook demo"').replace('author = ""', 'author = "labbook demo"')
if shutil.which("quarto") is None:
    t = t.replace('render = "pdf"', 'render = "off"')
    print("(quarto not found: render check switched off)")
p.write_text(t)
PY
git add -A && git commit -qm "install labbook"

step "3. The maintainer seals the protected files (human only)"
LB protect
git add -A && git commit -qm "labbook: protection manifest"

step "4. Session with a plan, committed before any run"
PLAN=$(LB session start euler-study --title "Convergence of explicit Euler" | head -1)
fill plan "$PLAN"
git add -A && git commit -qm "session euler-study: plan"

step "5. Entry 1: a run before the hypothesis exists is refused"
E1=$(LB new euler-order --title "Order of convergence of explicit Euler")
ID1=$(basename "$(dirname "$E1")")
LB run --entry "$ID1" -- "$PY" src/decay.py --h 0.01 --out out/x.csv || echo "(refused, as intended)"

step "6. Preregister: write and commit the hypothesis"
fill order-hypothesis "$E1"
git add -A && git commit -qm "$ID1: hypothesis"

step "7. Runs through the wrapper (provenance, checksums, run IDs)"
for h in 0.04 0.02 0.01; do
  LB run --entry "$ID1" --param h=$h --output "out/h$h.csv" --description "Euler h=$h" \
    -- "$PY" src/decay.py --h $h --out out/h$h.csv
done

step "8. Analysis: figure and metrics into the ledger"
cp "$HERE/analysis_euler.py" "$(dirname "$E1")/analysis.py"
"$PY" "$(dirname "$E1")/analysis.py" R-0001 R-0002 R-0003

step "9. Complete the entry and close it (status, verdict, closed timestamp)"
fill order-result "$E1"
sed -i.bak 's/^runs: \[\]/runs: [R-0001, R-0002, R-0003]/' "$E1" && rm "$E1.bak"
LB close "$ID1" --verdict confirmed
git add -A && git commit -qm "$ID1: result, entry closed"

step "10. Entry 2: the same rule for coarse steps"
E2=$(LB new coarse-steps --title "Does step halving still work for coarse steps?")
ID2=$(basename "$(dirname "$E2")")
fill coarse-hypothesis "$E2"
git add -A && git commit -qm "$ID2: hypothesis"
for h in 0.5 0.25; do
  LB run --entry "$ID2" --param h=$h --output "out/h$h.csv" --description "Euler h=$h" \
    -- "$PY" src/decay.py --h $h --out out/h$h.csv
done
cp "$HERE/analysis_euler.py" "$(dirname "$E2")/analysis.py"
"$PY" "$(dirname "$E2")/analysis.py" R-0004 R-0005
fill coarse-result "$E2"
sed -i.bak 's/^runs: \[\]/runs: [R-0004, R-0005]/' "$E2" && rm "$E2.bak"
LB close "$ID2" --verdict refuted
git add -A && git commit -qm "$ID2: result, entry closed"

step "11. End the session: summary with generated trace statistics"
SUM=$(LB session end)
fill summary "$SUM"
LB check --no-render
git add -A && git commit -qm "session euler-study: summary"

step "12. Ledger and provenance"
column -t -s $'\t' labbook/results.tsv 2>/dev/null || cat labbook/results.tsv
"$PY" -c 'import json; d=json.load(open("labbook/runs/R-0003/provenance.json")); print({k: d[k] for k in ("lauf","befehl","parameter","exit","ausgaben_sha256")})'

if command -v quarto >/dev/null && [ -z "${LB_DEMO_NO_BOOK:-}" ]; then
  step "13. The book (month > week > day > entry)"
  LB book --format html && echo "html: $T/labbook/_book/html/index.html"
  LB book --format pdf && echo "pdf:  $T/labbook/_book/pdf/labbook.pdf"
fi
step "Done. Project: $T"
