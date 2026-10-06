# -*- coding: utf-8 -*-
"""Equal-budget tuning of every method on validation traces (24 configurations each).

Validation: UDN-40, 300 users, street-grid and highway profiles, seeds 101-102,
120 s.  These seeds are never used for the reported test results.

usage: python experiments/tune.py              -> results/tune.csv  (all families)
       python experiments/tune.py <family> ... -> results/tune_extra.csv  (only the named families)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import run_all
from common import OUT


def grids():
    """Method family -> list of 24 (class name, keyword arguments) configurations.
    The family "Proposed" is ROAM."""
    g = {}
    g["A3"] = [("A3", dict(hyst=h, ttt=t)) for h in (1, 2, 3, 4, 5, 6) for t in (0.1, 0.3, 0.5, 1.0)]
    g["Proposed"] = [("ROAM", dict(h0=h, ttt=t, eta_H=eh, eta_L=el, eta_A=ea, m_cap=9))
                     for h in (1, 2) for t in (0.1, 0.3)
                     for eh, el, ea in ((6, 0, 6), (6, 4, 6), (10, 6, 6), (6, 4, 3), (14, 8, 8), (10, 6, 3))]
    g["PBPHS"] = [("PBPHS", dict(m=m, bias=b)) for m in (0, 1, 2, 3, 4, 6) for b in (0, 1.5, 3, 6)]
    g["Traj-Pred"] = [("TrajPred", dict(T_h=T, g=gg)) for T in (1, 2, 3, 5) for gg in (0, 1, 2, 3, 4, 6)]
    g["ToS-Skip"] = [("ToSSkip", dict(hyst=h, ttt=t, tau=ta))
                     for h in (1, 2, 3) for t in (0.1, 0.3) for ta in (2, 3, 5, 7)]
    g["ST-CMAB"] = [("STCMAB", dict(hyst=h, ttt=t, cu=c))
                    for h in (1, 2, 3, 4) for t in (0.1, 0.3, 0.5) for c in (0.2, 1.0)]
    g["Cluster-RL"] = [("ClusterRL", dict(c_ho=c, lr=l, eps=e))
                       for c in (0.25, 0.5, 1, 2, 4, 8) for l in (0.05, 0.2) for e in (0.01, 0.05)]
    g["MP-Screen"] = [("MPScreen", dict(hyst=h, ttt=t, angle=a))
                      for h in (1, 2, 3, 4) for t in (0.1, 0.3) for a in (30, 45, 60)]
    return g


if __name__ == "__main__":
    jobs = []
    only = sys.argv[1:]                       # optional: tune only the named families
    for fam, lst in grids().items():
        if only and fam not in only:
            continue
        assert len(lst) == 24, (fam, len(lst))
        for ci, pol in enumerate(lst):
            for prof in ("street", "highway"):
                for seed in (101, 102):
                    jobs.append(dict(env="UDN-40", profile=prof, users=300, seed=seed, T=120.0, pol=pol,
                                     tag=dict(family=fam, cfg=ci, kw=repr(pol[1]))))
    run_all(jobs, os.path.join(OUT, "tune_extra.csv" if only else "tune.csv"), label="tune")
