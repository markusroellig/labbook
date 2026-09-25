#!/bin/bash
# End-to-end demo of labbook without Claude Code: builds a throw-away project, installs the
# framework and walks through one complete experiment (the order of convergence of explicit Euler).
# In a Claude Code session the assistant performs the same steps; the hooks then add the trace,
# the events and the protection on top.
#
#   examples/demo/run_demo.sh [TARGET_DIR]      (default: a new temporary directory)
#
# Set LB_DEMO_NO_BOOK=1 to skip rendering the HTML book even when Quarto is installed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PY=${PYTHON:-python3}
T=${1:-$(mktemp -d)/demo-project}
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "1. A small project under git: $T"
mkdir -p "$T/src"
cp "$HERE/decay.py" "$T/src/decay.py"
cd "$T"
git init -q
git config user.name "labbook demo"; git config user.email "demo@example.org"
git add -A && git commit -qm "decay model"

step "2. Install labbook (tool, hooks, skill, notebook skeleton)"
bash "$REPO/install.sh" "$T"
if ! command -v quarto >/dev/null; then
  "$PY" - <<'PY'
from pathlib import Path
p = Path(".claude/labbook.toml"); p.write_text(p.read_text().replace('render = "pdf"', 'render = "off"'))
PY
  echo "(quarto not found: render check switched off in .claude/labbook.toml)"
fi
git add -A && git commit -qm "install labbook"

step "3. The maintainer seals the protected files (human only)"
"$PY" tools/lb.py protect
git add -A && git commit -qm "labbook: protection manifest"

step "4. New entry"
ENTRY=$("$PY" tools/lb.py new euler-order --title "Order of convergence of explicit Euler")
ID=$(basename "$(dirname "$ENTRY")")
echo "$ENTRY"

step "5. A run before the hypothesis exists is refused"
"$PY" tools/lb.py run --entry "$ID" -- "$PY" src/decay.py --h 0.01 --out out/x.csv || echo "(refused, as intended)"

step "6. Preregister: write and commit the hypothesis"
"$PY" - "$ENTRY" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]); t = p.read_text()
t = t.replace("## Why\n", "## Why\n\nExplicit Euler is claimed to be first order; check it on dy/dt = -y.\n", 1)
t = t.replace("## Hypothesis / Expectation\n", "## Hypothesis / Expectation\n\n"
              "The absolute error at t = 1 s halves when the step size halves: the ratio "
              "err(h)/err(h/2) lies in [1.9, 2.1] for h = 0.02 s.\n", 1)
p.write_text(t)
PY
git add -A && git commit -qm "$ID: hypothesis"

step "7. Runs through the wrapper (provenance, checksums, run IDs)"
for h in 0.02 0.01; do
  "$PY" tools/lb.py run --entry "$ID" --param h=$h --output "out/h$h.csv" --description "Euler h=$h" \
    -- "$PY" src/decay.py --h $h --out out/h$h.csv
done

step "8. Metrics into the ledger"
RATIO=$("$PY" - <<'PY'
import math
def err(h):
    y = 1.0
    for _ in range(round(1 / h)):
        y -= h * y
    return abs(y - math.exp(-1))
print(f"{err(0.02) / err(0.01):.4f}")
PY
)
"$PY" tools/lb.py result R-0002 --metric error_ratio --value "$RATIO" --reference 2 --status keep \
  --description "err(h=0.02)/err(h=0.01) at t=1 s"

step "9. Complete and close the entry; numbers come from the ledger via shortcodes"
"$PY" - "$ENTRY" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]); t = p.read_text()
fill = {
    "## Method\n": "## Method\n\nExplicit Euler, `src/decay.py:14-20`; runs R-0001 (h = {{< run-param R-0001 h >}} s) "
                   "and R-0002 (h = {{< run-param R-0002 h >}} s).\n",
    "## Result\n": "## Result\n\nError ratio {{< result R-0002 error_ratio >}} ({{< prov R-0002 >}}).\n",
    "## Verification\n": "## Verification\n\nExact solution exp(-t) as oracle.\n",
    "## Interpretation\n": "## Interpretation\n\nConsistent with first order.\n",
    "## Consequences and next steps\n": "## Consequences and next steps\n\nNone.\n",
    "## Failed attempts\n": "## Failed attempts\n\nnone\n",
    "## Deviations from plan\n": "## Deviations from plan\n\nnone\n",
}
for k, v in fill.items():
    t = t.replace(k, v, 1)
t = t.replace("runs: []", "runs: [R-0001, R-0002]")
p.write_text(t)
PY
"$PY" tools/lb.py close "$ID" --verdict confirmed      # status, verdict and the `closed` timestamp
grep -E '^(opened|closed|status|verdict):' "$ENTRY"
"$PY" tools/lb.py check --no-render
git add -A && git commit -qm "$ID: result, entry closed"

step "10. Ledger and provenance"
column -t -s $'\t' labbook/results.tsv 2>/dev/null || cat labbook/results.tsv
"$PY" -c 'import json,sys; d=json.load(open("labbook/runs/R-0002/provenance.json")); print({k: d[k] for k in ("lauf","befehl","parameter","exit","ausgaben_sha256")})'

if command -v quarto >/dev/null && [ -z "${LB_DEMO_NO_BOOK:-}" ]; then
  step "11. The book"
  "$PY" tools/lb.py book --format html && echo "book: $T/labbook/_book/html/index.html"
fi
step "Done. Project: $T"
