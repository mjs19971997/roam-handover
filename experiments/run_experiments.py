# -*- coding: utf-8 -*-
"""All test experiments (frozen, tuned configurations from results/tuned.json).

usage: python experiments/run_experiments.py <block> [<block> ...]
blocks: profiles load density real ablation hht nonstat sens thresh posthoc tempo

  profiles  central comparison: all methods on the five mobility profiles
  load      all methods at 100 / 500 / 700 users (street grid)
  density   all methods on the UDN-20 and UDN-60 layouts (street grid)
  real      all methods on the three measured drive-test routes
  ablation  ROAM with single terms switched off or on
  hht       outcome table: warm / cold start, frozen, fixed at its prior, removed
  nonstat   environment re-drawn at 240 s; forgetting time constants
  sens      one-at-a-time sensitivity of ROAM, motion-estimate errors, shadowing model
  thresh    all methods under rescaled outcome thresholds (T_min, theta_Q)
  posthoc   ROAM with a positive margin floor
  tempo     ROAM variants and A3 with temporal shadowing only

Each block writes results/exp_<block>.csv.  Test seeds are 1..N (validation used 101-102).
The method label "Proposed" in the result files is ROAM.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import run_all
from common import OUT

ORDER = ["Proposed", "A3", "MP-Screen", "ToS-Skip", "Traj-Pred", "ST-CMAB", "Cluster-RL", "PBPHS"]


def tuned():
    """Method family -> (class name, keyword arguments) selected by select_configs.py."""
    with open(os.path.join(OUT, "tuned.json")) as fh:
        t = json.load(fh)
    return {k: (v["cls"], v["kw"]) for k, v in t.items() if not k.startswith("_")}


def jobs_main(env, profile, users, seeds, T=240.0, extra=None, P=None):
    """Jobs of all eight tuned methods on one scenario."""
    TN = tuned()
    return [dict(env=env, profile=profile, users=users, seed=s, T=T, pol=(TN[f][0], dict(TN[f][1], name=f)),
                 P=P or {}, tag=dict(extra or {}, method=f, users_n=users))
            for f in ORDER for s in seeds]


URB = "street"                                   # urban reference profile for the secondary studies


def block_profiles():
    """Central comparison: every method on the five mobility profiles (UDN-40, 300 users, 8 seeds)."""
    j = []
    for pr in ("pedestrian", "vehicular", "street", "highway", "train"):
        j += jobs_main("UDN-40", pr, 300, range(1, 9))
    return j


def block_load():
    """Traffic load: 100 / 500 / 700 users on the street grid (300 users come from block profiles)."""
    j = []
    for u in (100, 500, 700):
        j += jobs_main("UDN-40", URB, u, range(1, 7))
    return j


def block_density():
    """Cell density: the UDN-20 and UDN-60 layouts (UDN-40 comes from block profiles)."""
    j = []
    for e in ("UDN-20", "UDN-60"):
        j += jobs_main(e, URB, 300, range(1, 7))
    return j


def block_real():
    """Measured drive-test routes DT01-DT03 (60 users following the route)."""
    j = []
    for e in ("DT01", "DT02", "DT03"):
        j += jobs_main(e, "vehicular", 60, range(1, 7))
    return j


def prop(kw, name, **over):
    """A ROAM variant: tuned keyword arguments with overrides, labelled `name`."""
    return ("ROAM", dict(kw, name=name, **over))


def block_ablation():
    """Ablation of ROAM: terms added to the base rule one by one and removed from the full method."""
    kw = tuned()["Proposed"][1]
    off = dict(use_hht=False, use_area=False, use_svc=False, use_init=False, use_hold=False)
    prior = (kw["eta_H"] - kw["eta_L"]) / 4.0
    V = [
        prop(kw, "(a) base rule only", **off),
        prop(kw, "(b) base + hold timer", **dict(off, use_hold=True)),
        prop(kw, "(c) base + history table", **dict(off, use_hold=True, use_hht=True)),
        prop(kw, "(d) base + path overlap", **dict(off, use_hold=True, use_area=True)),
        prop(kw, "(e) full w/o a_init bonus", use_init=False),
        prop(kw, "(f) full method"),
        prop(kw, "(g) full w/o service term", use_svc=False),
        prop(kw, "(h) full w/o lateness credit", eta_L=0.0),
        prop(kw, "(i) full w/o hold timer", use_hold=False),
        prop(kw, "(j) full, route-level table only", loc_res=None),
        prop(kw, "(k) full, table fixed at its prior", use_hht=False, h0=kw["h0"] + prior),
    ]
    return [dict(env="UDN-40", profile=pr, users=300, seed=s, T=240.0, pol=v, tag=dict(method=v[1]["name"]))
            for pr in (URB, "highway", "vehicular") for v in V for s in range(1, 7)]


def block_hht():
    """Role of the outcome table: warm / cold start, frozen, fixed at its prior, removed; with time curves."""
    kw = tuned()["Proposed"][1]
    prior = (kw["eta_H"] - kw["eta_L"]) / 4.0
    V = [
        (prop(kw, "warm start + online"), 240.0),
        (prop(kw, "cold start, online"), 0.0),
        (prop(kw, "warm start, frozen", freeze=True), 240.0),
        (prop(kw, "table fixed at its prior", use_hht=False, h0=kw["h0"] + prior), 0.0),
        (prop(kw, "no history table", use_hht=False), 0.0),
    ]
    j = []
    for pr in (URB, "highway"):
        for v, w in V:
            for s in range(1, 7):
                j.append(dict(env="UDN-40", profile=pr, users=300, seed=s, T=240.0, pol=v, curve_bin=20.0, warm=w,
                              tag=dict(method=v[1]["name"])))
    a3 = tuned()["A3"]
    j += [dict(env="UDN-40", profile=pr, users=300, seed=s, T=240.0, pol=(a3[0], dict(a3[1], name="A3")),
               curve_bin=20.0, tag=dict(method="A3")) for pr in (URB, "highway") for s in range(1, 7)]
    return j


def block_nonstat():
    """Non-stationary environment: hotspots and blockage re-drawn at 240 s of a 720 s run."""
    kw = tuned()["Proposed"][1]
    prior = (kw["eta_H"] - kw["eta_L"]) / 4.0
    V = [prop(kw, "no forgetting", tau_f=None), prop(kw, "tau_f = 600 s", tau_f=600.0),
         prop(kw, "tau_f = 150 s", tau_f=150.0), prop(kw, "table fixed at its prior", use_hht=False, h0=kw["h0"] + prior)]
    a3 = tuned()["A3"]
    V.append((a3[0], dict(a3[1], name="A3")))
    return [dict(env="UDN-40", profile=pr, users=300, seed=s, T=720.0, pol=v, switch_at=240.0,
                 curve_bin=40.0, tag=dict(method=v[1]["name"])) for pr in (URB, "highway") for v in V for s in range(1, 7)]


def block_sens():
    """One-at-a-time sensitivity of ROAM to its parameters, to heading / speed errors and
    to the shadowing model."""
    kw = tuned()["Proposed"][1]
    S = [("tuned", {}, {})]
    for k, vals in (("eta_H", (0.5, 1.5)), ("eta_A", (0.5, 1.5)), ("eta_L", (0.5, 1.5)), ("h0", (0.5, 1.5))):
        for m in vals:
            S.append((f"{k} x{m}", {k: kw.get(k, 0) * m}, {}))
    for k, vals in (("eta_S", (0.0, 2.0, 8.0)), ("alpha", (0.3, 0.9)), ("beta", (0.5, 3.0)), ("eps", (0.0, 2.0)),
                    ("T_hold", (0.0, 3.0)), ("T_p", (2.0, 10.0)), ("half", (0.3, 1.0)), ("m_cap", (6.0, 12.0)),
                    ("ttt", (0.1, 0.5)), ("kappa", (0.0, 4.0)), ("loc_res", (20.0, 80.0)), ("loc_kappa", (1.0, 10.0))):
        for v in vals:
            S.append((f"{k} = {v:g}", {k: v}, {}))
    for he in (0.2, 0.5, 1.0):
        S.append((f"heading error {he:g} rad", {}, dict(head_err=he)))
    for se in (0.2, 0.5):
        S.append((f"speed error {se:g}", {}, dict(speed_err=se)))
    S.append(("temporal shadowing only", {}, dict(shadow_mode="temporal")))
    return [dict(env="UDN-40", profile=URB, users=300, seed=s, T=240.0,
                 pol=("ROAM", dict(kw, name="Proposed", **over)), P=Pov, tag=dict(variant=nm, method="Proposed"))
            for nm, over, Pov in S for s in range(1, 5)]


def block_thresh():
    """Robustness to the outcome definition: T_min and theta_Q rescaled for all methods."""
    j = []
    for nm, Pov in (("T_min x0.5", dict(tmin_scale=0.5)), ("T_min x1.5", dict(tmin_scale=1.5)),
                    ("theta_Q x0.5", dict(thq_scale=0.5)), ("theta_Q x2", dict(thq_scale=2.0))):
        j += jobs_main("UDN-40", URB, 300, range(1, 5), extra=dict(variant=nm), P=Pov)
    return j


def block_posthoc():
    """Post-hoc variant (decided after seeing test results; reported as such): a positive margin floor."""
    kw = tuned()["Proposed"][1]
    V = [prop(kw, "ROAM, m_min = 0 dB (tuned)"), prop(kw, "ROAM, m_min = 1 dB", m_floor=1.0), prop(kw, "ROAM, m_min = 2 dB", m_floor=2.0)]
    return [dict(env="UDN-40", profile=pr, users=300, seed=s, T=240.0, pol=v, tag=dict(method=v[1]["name"]))
            for pr in ("pedestrian", URB) for v in V for s in range(1, 7)]


def block_tempo():
    """Central comparison repeated with the per-user temporal shadowing process only
    (no static field): outcomes are then not a repeatable property of place."""
    kw = tuned()["Proposed"][1]
    prior = (kw["eta_H"] - kw["eta_L"]) / 4.0
    a3 = tuned()["A3"]
    V = [prop(kw, "ROAM"), prop(kw, "table fixed at its prior", use_hht=False, h0=kw["h0"] + prior),
         prop(kw, "no history table", use_hht=False), (a3[0], dict(a3[1], name="A3"))]
    return [dict(env="UDN-40", profile=pr, users=300, seed=s, T=240.0, pol=v, P=dict(shadow_mode="temporal"),
                 tag=dict(method=v[1]["name"])) for pr in (URB, "highway") for v in V for s in range(1, 7)]


BLOCKS = dict(tempo=block_tempo, posthoc=block_posthoc, profiles=block_profiles, load=block_load, density=block_density, real=block_real,
              ablation=block_ablation, hht=block_hht, nonstat=block_nonstat, sens=block_sens, thresh=block_thresh)

if __name__ == "__main__":
    names = "profiles load density real ablation hht nonstat sens thresh posthoc tempo".split()
    if len(sys.argv) < 2:
        print("usage: python experiments/run_experiments.py <block> [<block> ...]")
        print("blocks:", " ".join(names))
        sys.exit(0)
    bad = [b for b in sys.argv[1:] if b not in BLOCKS]
    if bad:
        sys.exit(f"unknown block(s): {' '.join(bad)}; available: {' '.join(names)}")
    for b in sys.argv[1:]:
        run_all(BLOCKS[b](), os.path.join(OUT, f"exp_{b}.csv"), label=b)
