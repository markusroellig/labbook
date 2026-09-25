#!/usr/bin/env python3
"""Analysis for this entry. Produces ALL figures of the entry (each as .pdf and .png).

Call from the repository root:
    python3 <notebook>/entries/<id>/analysis.py R-0007 [R-0008 ...]

Rules: read data only from the outputs of the named runs (paths and checksums are in
<notebook>/runs/<R>/provenance.json). Do not enter numbers by hand. Write metrics to the
ledger with `tools/lb.py result`, cite them in the text via {{</* result R-.. metric */>}}.
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parents[1]
FIG = HERE / "fig"
FIG.mkdir(exist_ok=True)


def provenance(run_id: str) -> dict:
    """Provenance record of a run. Keys (ledger format): befehl = command, parameter = parameters,
    ausgaben_sha256 = output files with checksums, eingaben_sha256 = input files, git = commit/dirty."""
    return json.loads((NOTEBOOK / "runs" / run_id / "provenance.json").read_text())


def save(fig, name: str) -> None:
    """PDF and PNG. Data layers with more than ~1e4 points should be drawn with `rasterized=True`
    so that the PDF keeps a bitmap for the data and vector text/axes; otherwise the book PDF
    becomes slow to display."""
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(run_ids: list[str]) -> None:
    for rid in run_ids:
        prov = provenance(rid)
        print(rid, prov["befehl"], prov["ausgaben_sha256"])
    # fig, ax = plt.subplots(figsize=(5, 3.5))
    # ... load data from the run outputs and plot ...
    # save(fig, "name")


if __name__ == "__main__":
    main(sys.argv[1:])
