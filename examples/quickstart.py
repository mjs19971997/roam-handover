# -*- coding: utf-8 -*-
"""Quick start: A3 versus ROAM on one small scenario (about a minute on a laptop).

Scenario: UDN-40 layout, 60 users on the street grid, 60 s, one seed.  Both rules
use explicit parameters, so no tuning files are needed.  The numbers of such a
short single run are noisy; use experiments/run_experiments.py for real results.

usage: python examples/quickstart.py
"""
import sys, time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "experiments"))

from common import get_env, get_fw, scenario
from roam.simulator import SimParams, simulate
from roam.policies import A3, ROAM

ENV, PROFILE, USERS, T, SEED, WARM = "UDN-40", "street", 60, 60.0, 1, 60.0

if __name__ == "__main__":
    t0 = time.time()
    P = SimParams(T_sim=T)
    env = get_env(ENV, P)                       # radio map + heterogeneity + shadowing field
    fw = get_fw(env)                            # base layer (K-means + PCA + decision tree)
    print(f"{env.name}: {env.M} cells, base-layer accuracy {fw.acc:.3f}")

    a3 = A3(hyst=4, ttt=0.1)
    roam = ROAM(fw, h0=2, ttt=0.3, eta_H=14, eta_L=8, eta_A=8, m_cap=9, name="ROAM")

    # ROAM learns from observed outcomes: fill its table on an independent warm-up scenario first
    Pw = replace(P, T_sim=WARM)
    traj_w, svc_w = scenario(env, PROFILE, USERS, Pw, 5000 + SEED)
    roam.persist = True                         # keep the table for the next run
    simulate(env, roam, traj_w, svc_w, Pw, seed=5000 + SEED)

    # both rules see the same trajectories, services and shadowing
    traj, svc = scenario(env, PROFILE, USERS, P, SEED)
    res = [simulate(env, pol, traj, svc, P, seed=SEED) for pol in (a3, roam)]

    rows = [("handovers per user-minute", "HO_pm"), ("unnecessary HOs per user-minute", "UHO_pm"),
            ("unnecessary-handover ratio", "UHR"), ("mobility failures per user-minute", "fail_pm"),
            ("ping-pong rate", "PP_rate"), ("outage [%]", "outage_pct"),
            ("delivered / demanded rate", "satisf"), ("mean serving SINR [dB]", "sinr_db")]
    print(f"\n{'metric':<36}{'A3':>10}{'ROAM':>10}")
    for label, key in rows:
        print(f"{label:<36}{res[0][key]:>10.3f}{res[1][key]:>10.3f}")
    print(f"\ndone in {time.time() - t0:.0f} s")
