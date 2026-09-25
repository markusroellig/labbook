---
name: labbook
description: Traceable documentation of numerical experiments, tests, debugging and parameter studies in the Quarto lab notebook (labbook/). Use BEFORE a model run, test experiment, debugging attempt or autonomous session begins, when hooks report events that must be documented (E-NNNN), and when entries, figures, equations or session summaries are written.
---

# Lab notebook

The lab notebook makes every statement about the code and its results reconstructible: why
something was tested, what was expected, what exactly ran, what came out, what follows from it –
and what went wrong. The reader is an expert colleague who did not watch you work and checks
months later.

Mechanics that run independently of you (do not bypass, do not fight):
- Hooks write every tool call to `labbook/_trace/`.
- Relevant changes generate events `E-NNNN`; you receive them as context.
- The stop hook lets you finish only when all events are documented and all changed `.qmd`
  pass the schema check and render.
- Protected paths (reference data, conventions, ledgers, infrastructure) are locked.
  A blocked attempt becomes an event itself. If a protected file seems wrong:
  stop, document the finding, report to the human – do not work around it.

## Workflow of an experiment

1. **Create an entry:** `python3 tools/lb.py new <slug> --title "..."`
2. Fill in **Why** and **Hypothesis / Expectation** – quantitative, with a decision criterion.
   Then **commit** (`git commit`). `lb.py run` refuses runs without a committed hypothesis.
3. **Run through the wrapper**, never directly:
   `python3 tools/lb.py run --entry <id> --param h=0.01 --input config/x.toml --output "out/*.csv" --description "..." -- ./simulate config/x.toml`
   Result: `RUN R-NNNN exit=…`, provenance in `labbook/runs/R-NNNN/`.
4. **Analysis** only in `entries/<id>/analysis.py`; figures each as `.pdf` and `.png` into `fig/`.
5. **Metrics into the ledger:** `python3 tools/lb.py result R-NNNN --metric rel_error --value 0.07 --reference 0.05 --status info --description "..."`
6. **Complete the entry**, set `runs:` and `events:` in the frontmatter.
7. **Close it:** `python3 tools/lb.py close <id> --verdict confirmed|refuted|undecided|not-applicable`
   sets `status`, `verdict` and the `closed` timestamp (`opened` was set by `new`); do not type
   timestamps by hand. Then `python3 tools/lb.py check` and commit. The commit message begins with
   the entry ID.

## Autonomous session

- Start: `python3 tools/lb.py session start <slug> --title "..."`, fill in `plan.qmd` completely
  (goal, hypotheses, scope of action, stop criteria, test oracle), commit,
  `python3 tools/lb.py preflight`.
- During: document decisions **immediately**, do not reconstruct them at the end – the context
  gets compressed. Justify deviations from the plan in the entry under "Deviations from plan";
  the plan itself is not rewritten after the start (every change becomes an event).
- Respect the stop criteria. When one is reached: stop, document the state.
- End: `python3 tools/lb.py session end`, then fill in `summary.qmd`. The trace statistics in
  it are generated; explain contradictions between text and statistics explicitly.

## Writing rules

**Separate observation from interpretation.** "Result" contains only what was measured.
Plausible explanations belong in "Interpretation", with uncertainty and alternatives.

**Never type numbers by hand.** In the text: `{{< result R-0007 rel_error >}}`,
`{{< run-param R-0007 h >}}`. Figure captions end with `{{< prov R-0007 >}}`. If a number does
not come from the ledger, name its origin.

**Equations with code references.** Every equation: implementation location `file:lines`, all
symbols defined with units. If formula and code do not agree, say so explicitly.
Read equations off the code, do not supplement them from textbook knowledge.

**Conventions** from `labbook/conventions.qmd`. Mark deviations explicitly.

**Labels** with slug prefix: `{#fig-<slug>-name}`, `{#eq-<slug>-name}`; reference with
`@fig-<slug>-name`. The reference generates the prefix itself ("Fig. 4.1", "Eq. 4.1") – do not
write an additional "Fig." in front of it.

**Verification is mandatory.** At least the applicable ones of: conservation laws, limiting cases
with known solutions, convergence with respect to resolution and tolerance, comparison with the
test oracle. Which points of the parameter space were tested is stated in the table "Parameters
and test coverage". A single fiducial point is not sufficient coverage.

**Document negatives.** Failed approaches with the reason. Do not delete, weaken or bypass
failing tests; do not change tolerances, time limits, parameter grids and reference values
to make something pass. If that seems scientifically necessary: justify it as a deviation
and submit it to the human for decision.

**Immutability.** Entries with `status: closed` are not changed any more.
Correction as a new entry with `corrected: <old-id>`. `reviewed_by` is set only by the human.

## Documenting events

Every reported `E-NNNN` appears in the frontmatter of an entry or a session file:
- `events: [E-0012]` – handled in the entry, or
- `discarded:` with a concrete justification why it is not worth recording, e.g.
  ```yaml
  discarded:
    E-0014: "Build error caused by a typo in my own change, fixed immediately, no influence on results"
  ```
Discarding is legitimate but is checked by the auditor. "Unimportant" is not a justification.

## Commands

| Command | Purpose |
|---|---|
| `lb.py events --open` | undocumented events |
| `lb.py check [--all]` | the same check as the stop hook |
| `lb.py trace-stats` | mechanical statistics of the current session |
| `lb.py book` | complete PDF (normally the human) |

`lb.py protect` is reserved for the human. German command names of earlier versions
(`neu`, `ergebnis`, `pruefe`, ...) still work.
