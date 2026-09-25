#!/usr/bin/env python3
"""Analysis of the demo entries: absolute error of explicit Euler at t_end against exp(-k t_end),
read from the CSV outputs of the named runs, one figure (error vs. step size), and the metrics
written to the ledger through `tools/lb.py result`.

    python3 labbook/entries/<id>/analysis.py R-0001 R-0002 R-0003
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parents[1]
ROOT = NOTEBOOK.parent
FIG = HERE / "fig"
FIG.mkdir(exist_ok=True)


def provenance(run_id: str) -> dict:
    return json.loads((NOTEBOOK / "runs" / run_id / "provenance.json").read_text())


def final_error(run_id: str) -> tuple[float, float]:
    """(h, |y_Euler(t_end) - exp(-t_end)|) of a run; k = 1, t_end = 1 as in decay.py's defaults."""
    prov = provenance(run_id)
    csv = next(iter(prov["ausgaben_sha256"]))
    t_end, y_end = map(float, (ROOT / csv).read_text().splitlines()[-1].split(","))
    return float(prov["parameter"]["h"]), abs(y_end - math.exp(-t_end))


def record(run_id: str, metric: str, value: float, reference: str, description: str) -> None:
    subprocess.run([sys.executable, "tools/lb.py", "result", run_id, "--metric", metric, "--value", f"{value:.6g}",
                    "--reference", reference, "--status", "keep", "--description", description],
                   cwd=ROOT, check=True)


def main(run_ids: list[str]) -> None:
    data = sorted((final_error(r) + (r,) for r in run_ids), reverse=True)     # largest step first
    hs, errs, rids = zip(*data)
    for h, e, r in data:
        record(r, "abs_error", e, "", f"|y_Euler(1) - exp(-1)| for h = {h:g} s")
    for (h1, e1, _), (h2, e2, r2) in zip(data, data[1:]):
        record(r2, "error_ratio", e1 / e2, "2", f"err(h={h1:g}) / err(h={h2:g})")
        record(r2, "observed_order", math.log(e1 / e2) / math.log(h1 / h2), "1",
               f"log(err ratio) / log(step ratio) between h={h1:g} and h={h2:g}")

    fig, ax = plt.subplots(figsize=(5, 3.4))
    ax.loglog(hs, errs, "o-", label="explicit Euler")
    ax.loglog(hs, [errs[-1] * h / hs[-1] for h in hs], "--", color="0.5", label="slope 1")
    for h, e, r in data:
        ax.annotate(r, (h, e), textcoords="offset points", xytext=(4, -10), fontsize=7)
    ax.set_xlabel("step size $h$ [s]")
    ax.set_ylabel(r"$|y(1) - e^{-1}|$")
    ax.legend(frameon=False)
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"error_vs_h.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main(sys.argv[1:])
