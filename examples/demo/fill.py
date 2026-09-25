#!/usr/bin/env python3
"""Writes the demo texts into the notebook documents -- the part an assistant or a human writes by
hand in a real session. Every number in the texts comes from the ledger through shortcodes.

    python3 fill.py KEY FILE      KEY: plan | order-hypothesis | order-result | coarse-hypothesis |
                                       coarse-result | summary
"""
import sys
from pathlib import Path

TEXT = {
    "plan": {
        "Goal": "Establish the order of convergence of the explicit Euler integrator in `src/decay.py` and "
                "the range of step sizes in which the textbook first-order behaviour holds.",
        "Hypotheses": "1. **H1** For $h \\le 0.04$ s the error at $t = 1$ s halves when $h$ halves: every "
                      "error ratio lies in $[1.9, 2.1]$.\n2. **H2** The same holds for the coarse pair "
                      "$h = 0.5 \\to 0.25$ s.",
        "Planned experiments and tests": "Runs at $h$ = 0.04, 0.02, 0.01 s (H1) and 0.5, 0.25 s (H2); "
                                         "each takes milliseconds.",
        "Scope of action": "May change: the notebook and the analysis scripts. May not change: "
                           "`src/decay.py`, the decision interval.",
        "Stop criteria": "Stop after the five runs. Further step sizes only with a new plan.",
        "Test oracle": "The exact solution $y(t) = e^{-kt}$ with $k = 1\\,\\mathrm{s^{-1}}$.",
    },
    "order-hypothesis": {
        "Why": "The integrator `src/decay.py` uses the explicit Euler method, which is expected to be first-order "
               "accurate. Before it is used for longer integrations, its order is checked on a problem with a "
               "known solution (plan H1).",
        "Hypothesis": "For $\\mathrm{d}y/\\mathrm{d}t = -ky$, $y(0) = 1$, $k = 1\\,\\mathrm{s^{-1}}$, the absolute "
                      "error at $t = 1$ s halves when the step halves: both error ratios, for "
                      "$h = 0.04 \\to 0.02$ s and $0.02 \\to 0.01$ s, lie in $[1.9, 2.1]$. "
                      "Refuted if either ratio falls outside.",
    },
    "order-result": {
        "Method": """
### Sources

`src/decay.py`; the analysis script `analysis.py` of this entry.

### Equations and code references

$$
y_{n+1} = y_n - h\\,k\\,y_n
$$ {#eq-euler-order-step}

implemented in `src/decay.py:14-19`; $h$ step size in s, $k$ decay rate in s$^{-1}$, $y$ dimensionless.
Error and observed order (`analysis.py`, functions `final_error` and `main`):

$$
\\varepsilon(h) = \\left|y_N - e^{-k t_\\mathrm{end}}\\right|, \\qquad
p = \\frac{\\ln\\left[\\varepsilon(h_1)/\\varepsilon(h_2)\\right]}{\\ln(h_1/h_2)}
$$ {#eq-euler-order-p}

### Parameters and test coverage

| Run | $h$ [s] | Purpose |
|---|--:|---|
| R-0001 | {{< run-param R-0001 h >}} | coarsest of the fine steps |
| R-0002 | {{< run-param R-0002 h >}} | |
| R-0003 | {{< run-param R-0003 h >}} | finest |
""",
        "Result": """
![Absolute error at $t = 1$ s against the step size, with a slope-1 reference line. {{< prov R-0003 >}}](fig/error_vs_h){#fig-euler-order-error}

@fig-euler-order-error shows the error falling with the step size. The error ratios are
{{< result R-0002 error_ratio >}} (R-0001 → R-0002) and {{< result R-0003 error_ratio >}}
(R-0002 → R-0003); the observed orders (@eq-euler-order-p) are {{< result R-0002 observed_order >}}
and {{< result R-0003 observed_order >}}.
""",
        "Verification": "Oracle: the exact solution $e^{-t}$. Limiting case: the error decreases monotonically "
                        "towards zero with $h$ in all three runs. Conservation laws: not applicable (one linear "
                        "equation).",
        "Interpretation": "Both ratios lie inside the decision interval. The observed order approaches 1 from "
                          "above as $h$ decreases, as expected when an $O(h)$ leading error carries an $O(h^2)$ "
                          "correction.",
        "Consequences": "Only $hk \\le 0.04$ was tested. Whether the rule also holds for coarse steps is plan "
                        "hypothesis H2 (next entry).",
        "Failed attempts": "none",
        "Deviations from plan": "none",
    },
    "coarse-hypothesis": {
        "Why": "The previous entry confirmed first order for $hk \\le 0.04$. Coarse steps are tempting for long "
               "integrations; plan hypothesis H2 asks whether step halving still predicts the error there.",
        "Hypothesis": "The error ratio for $h = 0.5 \\to 0.25$ s lies in $[1.9, 2.1]$, as for fine steps. "
                      "(The author expects a refutation, because $hk = 0.5$ is far from the asymptotic "
                      "regime; the interval decides.)",
    },
    "coarse-result": {
        "Method": """
### Sources

Same model and analysis as the previous entry.

### Equations and code references

As in the previous entry: the Euler step in `src/decay.py:14-19`, error and observed order in `analysis.py`.

### Parameters and test coverage

| Run | $h$ [s] | Purpose |
|---|--:|---|
| R-0004 | {{< run-param R-0004 h >}} | coarse |
| R-0005 | {{< run-param R-0005 h >}} | half of it |
""",
        "Result": """
![Absolute error at $t = 1$ s for the coarse steps, with a slope-1 reference line. {{< prov R-0005 >}}](fig/error_vs_h){#fig-coarse-steps-error}

The error ratio is {{< result R-0005 error_ratio >}}, outside the decision interval; the observed order is
{{< result R-0005 observed_order >}} (@fig-coarse-steps-error).
""",
        "Verification": "Same oracle as before; both errors are positive and decrease with $h$.",
        "Interpretation": "At $hk = 0.5$ the $O(h^2)$ terms are not negligible and the method has not yet "
                          "reached its asymptotic regime. First order is a statement about $h \\to 0$, not a rule "
                          "for coarse steps.",
        "Consequences": "Error estimates by step halving need $hk \\lesssim 0.04$ for this problem. The boundary "
                        "between $hk = 0.04$ and $0.5$ was not resolved.",
        "Failed attempts": "none",
        "Deviations from plan": "none",
    },
    "summary": {
        "Planned": "Two hypotheses on the order of explicit Euler (plan H1, H2).",
        "Carried out": "Five runs in two entries: fine steps (R-0001 to R-0003) and coarse steps (R-0004, R-0005). "
                       "This demo ran without Claude Code, so the mechanical trace below has no records.",
        "Deviations from plan": "none",
        "Key findings": "H1 confirmed: observed order {{< result R-0003 observed_order >}} at the finest pair. "
                        "H2 refuted: error ratio {{< result R-0005 error_ratio >}} for the coarse pair.",
        "Open questions": "Where between $hk = 0.04$ and $0.5$ the asymptotic regime begins.",
    },
}


def main(key: str, path: str) -> None:
    p = Path(path)
    t = p.read_text()
    for heading, text in TEXT[key].items():
        i = t.index(f"\n## {heading}")
        eol = t.index("\n", i + 1)
        rest = t[eol + 1:]
        if "\n### " in "\n" + text:   # text with its own subsections replaces the template's section body
            nxt = rest.find("\n## ")
            rest = rest[nxt:] if nxt >= 0 else ""
        t = t[:eol + 1] + "\n" + text.strip("\n") + "\n" + rest
    p.write_text(t)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
