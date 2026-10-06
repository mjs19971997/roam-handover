# -*- coding: utf-8 -*-
"""Parallel job runner.

A job is a plain dict:
  env, profile, users, seed, T, pol=(class_name, kwargs), P=dict(SimParams overrides),
  tag=dict(extra columns), switch_at, curve_bin, warm (warm-up length of the
  learning methods [s], default 240; 0 = cold start)
"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataclasses import replace
from multiprocessing import Pool


def n_procs():
    """Default number of worker processes: env var ROAM_PROCS, else all cores but one."""
    return max(1, int(os.environ.get("ROAM_PROCS") or (os.cpu_count() or 2) - 1))


def _make(pol, env):
    import common
    name, kw = pol
    cls = getattr(common, name)
    if name in ("ROAM", "PBPHS"):                 # the rules that use the base layer
        return cls(common.get_fw(env), **kw)
    return cls(**kw)


def run_job(job):
    """Run one job and return its row of metrics."""
    import common
    from roam.simulator import SimParams, RadioEnv, simulate
    P = replace(SimParams(T_sim=job.get("T", 240.0)), **job.get("P", {}))
    base = common.get_env(job["env"], SimParams())
    env = RadioEnv(base.base, P)                  # fresh heterogeneity object per job
    env.name = base.name
    pol = _make(job["pol"], env)
    warm = job.get("warm", 240.0)                 # warm-up of learning methods on independent traces [s]
    if warm and job["pol"][0] in ("ROAM", "STCMAB", "ClusterRL"):
        ps = 5000 + job["seed"]
        Pp = replace(P, T_sim=warm)
        tr, sv = common.scenario(env, job["profile"], job["users"], Pp, ps)
        pol.persist = True
        fr = getattr(pol, "freeze", False)
        if hasattr(pol, "freeze"):
            pol.freeze = False
        simulate(env, pol, tr, sv, Pp, seed=ps)
        if hasattr(pol, "freeze"):
            pol.freeze = fr
    traj, svc = common.scenario(env, job["profile"], job["users"], P, job["seed"])
    r = simulate(env, pol, traj, svc, P, seed=job["seed"],
                 switch_at=job.get("switch_at"), curve_bin=job.get("curve_bin"))
    if "curve" in r:
        c = r.pop("curve")
        for i, row in enumerate(c):
            r[f"cv_ho_{i}"], r[f"cv_un_{i}"], r[f"cv_fl_{i}"] = row
    if hasattr(pol, "hht") and pol.hht is not None:
        r["hht_routes"] = pol.hht.n_routes()
    r.update(env=job["env"], profile=job["profile"], seed=job["seed"], T=P.T_sim)
    r.update(job.get("tag", {}))
    return r


def run_all(jobs, out_csv, procs=None, label=""):
    """Run the jobs in a process pool and write one CSV row per job."""
    procs = procs or n_procs()
    t0 = time.time(); rows = []
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(run_job, jobs, chunksize=1)):
            rows.append(r)
            if (i + 1) % max(1, len(jobs) // 20) == 0 or i + 1 == len(jobs):
                print(f"[{label}] {i+1}/{len(jobs)}  {time.time()-t0:.0f}s", flush=True)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"[{label}] wrote {out_csv} ({len(rows)} rows, {time.time()-t0:.0f}s)", flush=True)
    return rows
