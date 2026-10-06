# -*- coding: utf-8 -*-
"""Shared experiment harness: repository paths, the six radio environments, the
base layer and the scenario generator used by every experiment script."""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

from roam.radiomap import load_dataset, RadioMap
from roam.mobility import PROF_BY_KEY
from roam.simulator import SimParams, RadioEnv, gen_traj, assign_services, simulate
from roam.policies import (BaseLayer, A3, ROAM, PBPHS, TrajPred, ToSSkip,
                           STCMAB, ClusterRL, MPScreen)

DATA = str(ROOT / "data")
OUT = os.environ.get("ROAM_RESULTS") or str(ROOT / "results")     # result files (override: ROAM_RESULTS)
FIG = str(ROOT / "figures")
os.makedirs(OUT, exist_ok=True); os.makedirs(FIG, exist_ok=True)

DS = {
    "UDN-20": os.path.join(DATA, "synthetic", "realistic_5G_drive_test.csv"),
    "UDN-40": os.path.join(DATA, "synthetic", "realistic_5G_2x.csv"),
    "UDN-60": os.path.join(DATA, "synthetic", "realistic_5G_3x.csv"),
    "DT01": os.path.join(DATA, "drive_tests", "drive_test_measurements01.csv"),
    "DT02": os.path.join(DATA, "drive_tests", "drive_test_measurements02.csv"),
    "DT03": os.path.join(DATA, "drive_tests", "drive_test_measurements03.csv"),
}
_ENV, _FW = {}, {}


class RobustEnv(RadioMap):
    """Same construction as RadioMap, but a cell whose own log-distance
    fit is unreliable (few samples, narrow distance span, exponent on a bound)
    inherits the pooled fit of the whole trace.  This is what makes trace DT03
    usable; DT01/DT02 and the synthetic layouts are unaffected in practice."""

    def _fit_pathloss(self):
        d_all = np.clip(self.df.Distance.values, 1.0, None)
        slope, icpt = np.polyfit(np.log10(d_all), self.df.RSRP.values, 1)
        n_pool = float(np.clip(-slope / 10.0, 2.0, 4.5))
        self.pl = {}; self.fit_info = {}
        for c in self.cells:
            sub = self.df[self.df.PCI == c]
            d = np.clip(sub.Distance.values, 1.0, None); X = np.log10(d); r = sub.RSRP.values
            ok = False
            if len(d) >= 30 and X.std() > 0.1:
                s, i0 = np.polyfit(X, r, 1); n = -s / 10.0
                ok = 1.7 <= n <= 4.8
            if ok:
                A = i0
            else:                       # pooled exponent, cell-specific intercept
                n = n_pool; A = float(np.median(r + 10 * n * X))
            self.pl[c] = (float(A), float(n)); self.fit_info[c] = (len(d), bool(ok))
        self.global_pl = (float(np.median([v[0] for v in self.pl.values()])), n_pool)
        self.A_arr = np.array([self.pl[c][0] for c in self.cells])
        self.n_arr = np.array([self.pl[c][1] for c in self.cells])


def get_env(name, P):
    """Radio environment by name (UDN-20/40/60: synthetic layouts, DT01-03: measured
    drive-test traces, whose users follow the measured route).  Cached per process."""
    if name not in _ENV:
        real = name.startswith("DT")
        if not os.path.exists(DS[name]):
            if real:
                raise FileNotFoundError(
                    f"Drive-test trace not found: {DS[name]}\n"
                    "The measured traces are third-party data and are not distributed with this repository.\n"
                    "Download drive_test_measurements01.csv, 02.csv and 03.csv from "
                    "https://github.com/jpshlima/lstm-handover and place them in data/drive_tests/ "
                    "(see data/drive_tests/README.md).  Only the 'real' experiment block needs them.")
            raise FileNotFoundError(f"Synthetic layout not found: {DS[name]}")
        df = load_dataset(DS[name])
        base = (RobustEnv if real else RadioMap)(df, name=name)
        if real:
            xy = np.c_[base.df.x.values, base.df.y.values]
            keep = np.r_[True, np.hypot(*np.diff(xy, axis=0).T) > 2.0]
            base.route = xy[keep]
        _ENV[name] = RadioEnv(base, P)
    return _ENV[name]


def get_fw(env):
    """Base layer (K-means + PCA + decision tree) of an environment.  Cached per process."""
    if env.name not in _FW:
        _FW[env.name] = BaseLayer(env)
    return _FW[env.name]


def scenario(env, profile, U, P, seed):
    """Trajectories + service assignment shared by every policy of a (scenario, seed)."""
    S = int(round(P.T_sim / P.dt))
    rng = np.random.default_rng(100003 * seed + 17)
    traj = gen_traj(env, PROF_BY_KEY[profile], U, S, P.dt, rng)
    svc = assign_services(U, np.random.default_rng(500 + seed))
    return traj, svc
