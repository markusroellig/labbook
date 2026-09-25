#!/usr/bin/env python3
"""Toy model for the labbook demo: exponential decay dy/dt = -k y, y(0) = 1, integrated with the
explicit Euler method up to t_end. Writes the trajectory as CSV and prints the error at t_end
against the exact solution exp(-k t_end).

    python3 decay.py --h 0.01 --out out/h0.01.csv
"""
import argparse
import math
from pathlib import Path


def euler(k: float, h: float, t_end: float) -> list[tuple[float, float]]:
    n = round(t_end / h)
    y, traj = 1.0, [(0.0, 1.0)]
    for i in range(1, n + 1):
        y += h * (-k * y)
        traj.append((i * h, y))
    return traj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=1.0, help="decay rate [1/s]")
    ap.add_argument("--h", type=float, required=True, help="step size [s]")
    ap.add_argument("--t-end", type=float, default=1.0, help="end time [s]")
    ap.add_argument("--out", required=True, help="CSV output file")
    a = ap.parse_args()
    traj = euler(a.k, a.h, a.t_end)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("t,y\n" + "".join(f"{t:.10g},{y:.17g}\n" for t, y in traj))
    err = abs(traj[-1][1] - math.exp(-a.k * a.t_end))
    print(f"h={a.h} y(t_end)={traj[-1][1]:.12g} abs_error={err:.6e}")


if __name__ == "__main__":
    main()
