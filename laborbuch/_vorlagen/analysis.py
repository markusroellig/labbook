#!/usr/bin/env python3
"""Analysis for this entry. Produces ALL figures of the entry (each as .pdf and .png).

Call from the repository root:
    python3 laborbuch/eintraege/<id>/analysis.py R-0007 [R-0008 ...]

Rules: read data only from the outputs of the named runs (paths/checksums are in
laborbuch/runs/<R>/provenance.json). Do not enter numbers by hand. Write metrics to the
ledger with `tools/lb.py ergebnis` (`result`), cite them in the text via {{</* ergebnis R-.. metrik */>}}.
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
LB = HERE.parents[1]
FIG = HERE / "fig"
FIG.mkdir(exist_ok=True)


def provenance(run_id: str) -> dict:
    return json.loads((LB / "runs" / run_id / "provenance.json").read_text())


def save(fig, name: str) -> None:
    """PDF and PNG. Data layers with more than ~1e4 points (spectra on fine grids, per-line scatter plots)
    must be drawn with `rasterized=True` so that the PDF keeps a bitmap for the data and vector text/axes;
    otherwise the book PDF becomes slow to display (a 29 000-point scatter is 4.6 MB as vectors, 0.3 MB rasterised)."""
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(run_ids: list[str]) -> None:
    for rid in run_ids:
        prov = provenance(rid)
        print(rid, prov["befehl"], prov["ausgaben_sha256"])
    # fig, ax = plt.subplots(figsize=(5, 3.5))
    # ... load data and plot ...
    # save(fig, "name")


if __name__ == "__main__":
    main(sys.argv[1:])
