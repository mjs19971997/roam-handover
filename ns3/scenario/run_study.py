# -*- coding: utf-8 -*-
"""Run every stage of the ns-3 study, in order, resumable. Standard library only.

    python run_study.py                 run / resume everything (then ../analyze_study.py on the new runs)
    python run_study.py --status        progress and ETA per stage
    python run_study.py --list          job counts and estimated hours per stage
    python run_study.py --only S3     only the named stage(s), comma separated (S1 .. S5)
    python run_study.py --smoke         a few-minute run of every stage type with tiny sizes (folder smoke/)
    options: --normal (do not lower the priority), --no-analysis

Workers: environment variable NS3_WORKERS (default: logical CPUs minus 4).
Every job is one run of the scenario program and appends one row to results.csv of its stage
folder; a job whose id is already there is skipped, so the command can be repeated at any time.
A failed job is retried once, listed in failed_jobs.txt of its folder and at the end, and does
not stop the stage or the stages after it. The stage definitions are frozen in ../PLAN.md.
The stage folders are written next to this file (ns3/scenario/), not into ns3/results/, which
holds the runs of the paper.
"""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import campaign as C   # grids, labels and argument builders of the core campaigns (unchanged)

SMOKE = "--smoke" in sys.argv
ROOT = os.path.join(HERE, "smoke") if SMOKE else HERE
NS3 = C.NS3
EXE_SRC = C.EXE_SRC
EXE = os.path.join(ROOT, "study_bin", "ho-scenario.exe")
DLL_PATH = C.DLL_PATH
WORKERS = int(os.environ.get("NS3_WORKERS", str(max(1, (os.cpu_count() or 8) - 4))))
BELOW = "--normal" not in sys.argv
RUN_FLAGS = (0x08000000 | (0x00004000 if BELOW else 0)) if os.name == "nt" else 0
JOB_TIMEOUT = 12 * 3600
LOG = os.path.join(ROOT, "run_study.log")

# ------------------------------------------------------------------ frozen design (PLAN.md)
N_UE, DISCARD, UDP_MS = 20, 60.0, 100
T_TUNE, T_TEST, T_ROB = 150.0, 180.0, 120.0
VAL_TRACES = list(C.VAL_TRACES)
CELLS = [(isd, v) for isd in (200, 400) for v in (8, 16, 30)]
REF_CELLS = [(400, 16), (200, 16)]            # cells of the sensitivity conditions
ROB_CELL = (400, 16)
A3_GRID, ROAM_GRID = list(C.A3_GRID), list(C.ROAM_GRID)
SEEDS_CORE = list(range(1, 21))
SEEDS_ROB = list(range(1, 11))
SEEDS_FRONT = list(range(1, 5))
SEEDS_LOAD = list(range(1, 6))
T_TUNE_LOAD, T_TEST_LOAD, T_FULL, FULL_RATE = 100.0, 120.0, 100.0, 8
SEEDS_SENS = list(range(1, 11))
T_LONG = 600.0

if SMOKE:
    DISCARD, T_TUNE, T_TEST, T_ROB, T_LONG = 4.0, 12.0, 12.0, 6.0, 16.0
    T_TUNE_LOAD, T_TEST_LOAD, T_FULL = 8.0, 8.0, 6.0
    VAL_TRACES = VAL_TRACES[:1]
    CELLS = [(400, 16)]
    REF_CELLS = [(400, 16)]
    A3_GRID = [dict(hyst=3, ttt=300), dict(hyst=5, ttt=100)]
    ROAM_GRID = ROAM_GRID[:1] + ROAM_GRID[-1:]
    SEEDS_CORE = SEEDS_ROB = SEEDS_FRONT = SEEDS_LOAD = SEEDS_SENS = [1]

# relative cost of one simulated second (light traffic, 20 UEs, no fading = 1); measured, see PLAN.md
COST = dict(mixed=6.5, full=13.0, fading=4.3, ue10=0.5, ue40=2.9, ue60=6.5)

_lock = threading.Lock()
_failed = []


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _lock:
        os.makedirs(ROOT, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line, flush=True)


# ------------------------------------------------------------------ jobs
def make_job(folder, phase, label, config, rule_args, isd, speed, seed, sim_time, jid=None,
             scen="base", traffic="light", fading=0, extra=(), n_ue=N_UE, cost=1.0):
    jid = jid or "%s_%s_d%d_v%d_s%d" % (phase, label, isd, speed, seed)
    res = os.path.join(ROOT, folder, "res").replace("\\", "/")
    args = list(rule_args) + (["--scen=urban"] if scen == "urban" else []) + [
        "--isd=%d" % isd, "--speed=%d" % speed, "--rngRun=%d" % seed, "--simTime=%g" % sim_time,
        "--discard=%g" % DISCARD, "--nUe=%d" % n_ue, "--udpInterval=%d" % UDP_MS,
        "--fading=%d" % fading, "--events=1", "--tag=%s" % jid, "--outDir=%s" % res]
    if traffic != "light":
        args.append("--traffic=%s" % traffic)
    args += list(extra)
    c = cost * sim_time * (COST["fading"] if fading else 1.0) * COST.get(traffic, 1.0)
    return dict(id=jid, folder=folder, phase=phase, label=label, config=config, args=args, cost=c)


def tuning_jobs(folder, scen, traffic="light", t_sim=None):
    jobs = []
    t_sim = t_sim or T_TUNE
    for isd, speed, seed in VAL_TRACES:
        for c in A3_GRID:
            jobs.append(make_job(folder, "tune", C.a3_label(c), C.a3_label(c), C.a3_args(c), isd, speed, seed,
                                 t_sim, scen=scen, traffic=traffic))
        for c in ROAM_GRID:
            jobs.append(make_job(folder, "tune", C.roam_label(c), C.roam_label(c), C.roam_args(c), isd, speed,
                                 seed, t_sim, scen=scen, traffic=traffic))
    return jobs


def rules_of(sel):
    """The five test rules from a selection (tuned_ns3.json); placeholders when sel is None
    (job ids do not depend on the selected configurations)."""
    if sel is None:
        a3, ro = A3_GRID[0], ROAM_GRID[0]
    else:
        a3, ro = sel["A3"]["config"], sel["ROAM"]["config"]
    ov, hi = dict(ro, etaH=0, etaL=0), dict(ro, etaA=0)
    base = dict(hyst=ro["h0"], ttt=ro["ttt"])
    return [("A3_tuned", C.a3_label(a3), C.a3_args(a3)), ("ROAM", C.roam_label(ro), C.roam_args(ro)),
            ("ROAM_overlap", C.roam_label(ov), C.roam_args(ov)),
            ("ROAM_history", C.roam_label(hi), C.roam_args(hi)),
            ("A3_h0", C.a3_label(base), C.a3_args(base))]


def test_jobs(folder, scen, sel, seeds, traffic="light", t_sim=None, n_rules=5, extra=()):
    return [make_job(folder, "test", lab, cfg, args, isd, v, s, t_sim or T_TEST, scen=scen, traffic=traffic,
                     extra=extra)
            for s in seeds for isd, v in CELLS for lab, cfg, args in rules_of(sel)[:n_rules]]


def rob_jobs(folder, scen, sel, seeds):
    isd, v = ROB_CELL
    return [make_job(folder, "rob", lab, cfg, args, isd, v, s, T_ROB, scen=scen, fading=1)
            for s in seeds for lab, cfg, args in rules_of(sel)[:2]]


def frontier_jobs(folder, scen):
    jobs = []
    for s in SEEDS_FRONT:
        for isd, v in CELLS:
            for c in A3_GRID:
                jobs.append(make_job(folder, "front", C.a3_label(c), C.a3_label(c), C.a3_args(c), isd, v, s,
                                     T_TEST, scen=scen))
            for c in ROAM_GRID:
                jobs.append(make_job(folder, "front", C.roam_label(c), C.roam_label(c), C.roam_args(c), isd, v,
                                     s, T_TEST, scen=scen))
    return jobs


def sens_jobs(folder, scen, sel):
    """Sensitivities with the frozen settings of the core campaign of the scenario."""
    rules = rules_of(sel)
    two = rules[:2]
    conds = []          # (name, rules, cells, sim_time, kwargs)
    for n in (10, 40, 60):
        conds.append(("ue%d" % n, two, REF_CELLS if n != 60 else REF_CELLS[:1], T_TEST,
                      dict(n_ue=n, cost=COST["ue%d" % n])))
    for v in (3, 42):
        conds.append(("v%d" % v, two, [(200, v), (400, v)] if not SMOKE else [(400, v)], T_TEST, {}))
    for isd in ((300, 500) if scen == "base" else (300,)):
        conds.append(("isd%d" % isd, two, [(isd, 16)], T_TEST, {}))
    conds.append(("fading", two, CELLS, T_ROB, dict(fading=1)))
    for d in (20, 100):
        conds.append(("prep%d" % d, two, REF_CELLS, T_TEST, dict(extra=["--prepDelay=%d" % d])))
    for t in (500, 2000):
        conds.append(("t310x%d" % t, two, REF_CELLS, T_TEST, dict(extra=["--t310=%d" % t])))
    conds.append(("long%d" % int(T_LONG), rules[:4], REF_CELLS, T_LONG, {}))
    jobs = []
    for s in SEEDS_SENS:
        for name, rr, cells, tsim, kw in conds:
            for isd, v in cells:
                for lab, cfg, args in rr:
                    jid = "sens_%s_%s_d%d_v%d_s%d" % (name, lab, isd, v, s)
                    j = make_job(folder, "sens", lab, cfg, args, isd, v, s, tsim, jid=jid, scen=scen, **kw)
                    j["cond"] = name
                    jobs.append(j)
    return jobs


# ------------------------------------------------------------------ results files
def results_path(folder):
    return os.path.join(ROOT, folder, "results.csv")


def read_results(folder):
    p = results_path(folder)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_result(job, metrics):
    row = dict(job_id=job["id"], phase=job["phase"], label=job["label"], config=job["config"])
    if "cond" in job:
        row["cond"] = job["cond"]
    row.update(metrics)
    p = results_path(job["folder"])
    with _lock:
        if not os.path.exists(p):
            header = list(row.keys())
            rows = []
        else:
            with open(p, newline="", encoding="utf-8") as f:
                rd = csv.DictReader(f)
                header = list(rd.fieldnames)
                new = [k for k in row if k not in header]
                rows = list(rd) if new else None
            if new:                                   # a newer program writes more columns: widen the file
                header += new
        if rows is not None:
            tmp = p + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
                w.writerow(row)
            os.replace(tmp, p)
        else:
            with open(p, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=header, extrasaction="ignore").writerow(row)


# ------------------------------------------------------------------ running
def run_one(job):
    env = dict(os.environ)
    if os.name == "nt":
        env["PATH"] = DLL_PATH + ";" + env.get("PATH", "")
    else:                                             # MSYS (POSIX-style) python
        env["PATH"] = ":".join("/" + q[0].lower() + q[2:].replace("\\", "/") for q in DLL_PATH.split(";")) + ":" + env.get("PATH", "")
    fdir = os.path.join(ROOT, job["folder"])
    jpath = os.path.join(fdir, "res", job["id"] + ".json")
    for attempt in (1, 2):
        if os.path.exists(jpath):
            os.remove(jpath)
        t0 = time.time()
        with open(os.path.join(fdir, "logs", job["id"] + ".log"), "w", encoding="utf-8") as lf:
            try:
                rc = subprocess.run([EXE] + job["args"], stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=fdir,
                                    timeout=JOB_TIMEOUT, creationflags=RUN_FLAGS).returncode
            except subprocess.TimeoutExpired:
                rc = -999
        if rc == 0 and os.path.exists(jpath):
            with open(jpath, encoding="utf-8") as f:
                append_result(job, json.load(f))
            return True, time.time() - t0
        log("FAILED %s/%s (attempt %d, exit code %s)" % (job["folder"], job["id"], attempt, rc))
    with _lock:
        _failed.append("%s/%s" % (job["folder"], job["id"]))
        with open(os.path.join(fdir, "failed_jobs.txt"), "a", encoding="utf-8") as f:
            f.write(job["id"] + "\n")
    return False, 0.0


def run_jobs(stage, jobs):
    if not jobs:
        return
    folder = jobs[0]["folder"]
    for d in ("res", "logs"):
        os.makedirs(os.path.join(ROOT, folder, d), exist_ok=True)
    done = {r["job_id"] for r in read_results(folder)}
    todo = [j for j in jobs if j["id"] not in done]
    name = "%s %s/%s" % (stage, folder, jobs[0]["phase"])
    log("%s: %d jobs, %d already finished, %d to run" % (name, len(jobs), len(jobs) - len(todo), len(todo)))
    if not todo:
        return
    state = dict(n=0, fail=0, t0=time.time())

    def work(job):
        ok, wall = run_one(job)
        with _lock:
            state["n"] += 1
            state["fail"] += (not ok)
            n = state["n"]
        if n % 10 == 0 or n == len(todo) or not ok:
            el = time.time() - state["t0"]
            log("%s %d/%d (failed %d) last %s wall=%.0fs  phase ETA %.2f h"
                % (name, n, len(todo), state["fail"], job["id"], wall, el / n * (len(todo) - n) / 3600.0))

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    log("%s finished: %d run, %d failed, %.2f h" % (name, state["n"], state["fail"],
                                                    (time.time() - state["t0"]) / 3600.0))


# ------------------------------------------------------------------ selection (the rule of campaign.py)
def tuned_path(folder):
    return os.path.join(ROOT, folder, "tuned_ns3.json")


def select(folder):
    rows = [r for r in read_results(folder) if r["phase"] == "tune"]
    agg = {}
    for r in rows:
        a = agg.setdefault(r["label"], dict(un=0.0, fail=0.0, att=0.0, uemin=0.0, n=0))
        a["un"] += float(r["unnecessary"]); a["fail"] += float(r["failures"])
        a["att"] += float(r["attempts"]); a["uemin"] += float(r["ue_min"]); a["n"] += 1
    table = {lab: dict(val_UHO_pm=a["un"] / a["uemin"], val_fail_pm=a["fail"] / a["uemin"],
                       val_HO_pm=a["att"] / a["uemin"], traces=a["n"], unnecessary=a["un"], failures=a["fail"])
             for lab, a in agg.items()}
    ref = C.a3_label(C.REF_A3)
    if ref not in table:
        log("%s: the reference configuration %s has no tuning result; stage skipped" % (folder, ref))
        return None
    budget = table[ref]["val_fail_pm"]
    out = {"_budget_fail_pm": budget, "_reference": ref,
           "_validation_traces": [dict(isd=i, speed=v, seed=s) for i, v, s in VAL_TRACES],
           "_selection_rule": "min UHO_pm subject to fail_pm <= fail_pm(reference A3); "
                              "if none, min fail_pm; ties: lower fail_pm, then lower HO_pm, then grid order",
           "_incomplete": sorted(l for l, t in table.items() if t["traces"] != len(VAL_TRACES))}
    for name, grid, labf in (("A3", A3_GRID, C.a3_label), ("ROAM", ROAM_GRID, C.roam_label)):
        cands = [(i, c, table[labf(c)]) for i, c in enumerate(grid) if labf(c) in table]
        if not cands:
            log("%s: no tuning result for %s; stage skipped" % (folder, name))
            return None
        ok = [x for x in cands if x[2]["val_fail_pm"] <= budget + 1e-12]
        if ok:
            best = min(ok, key=lambda x: (x[2]["val_UHO_pm"], x[2]["val_fail_pm"], x[2]["val_HO_pm"], x[0]))
        else:
            best = min(cands, key=lambda x: (x[2]["val_fail_pm"], x[2]["val_UHO_pm"], x[0]))
        cfg = dict(best[1])
        if name == "ROAM":
            cfg["etaS"] = C.ETA_S
        out[name] = dict(config=cfg, label=labf(best[1]), met_budget=bool(ok), n_meeting_budget=len(ok),
                         **{k: best[2][k] for k in ("val_UHO_pm", "val_fail_pm", "val_HO_pm")})
        out[name + "_grid"] = {labf(c): table.get(labf(c)) for c in grid}
    with open(tuned_path(folder), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    log("%s selection: budget fail_pm=%.4f; A3 %s; ROAM %s" % (folder, budget, out["A3"]["label"],
                                                               out["ROAM"]["label"]))
    return out


def load_sel(folder):
    p = tuned_path(folder)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


# ------------------------------------------------------------------ stages
CORE = {"urban": "campaign_urban", "base": "campaign"}


def core_stage(stage, scen, folder, seeds, traffic="light", rob=True, planning=False, t_tune=None, t_test=None):
    """tuning -> selection -> test (-> fast-fading subset); yields job lists."""
    yield tuning_jobs(folder, scen, traffic, t_tune)
    sel = None if planning else select(folder)
    if sel is None and not planning:
        return
    yield test_jobs(folder, scen, sel, seeds, traffic, t_test)
    if rob:
        yield rob_jobs(folder, scen, sel, SEEDS_ROB)


def stage_lists(stage, planning=False):
    """Generator of job lists of a stage, in running order."""
    if stage == "S1":
        yield from core_stage(stage, "urban", CORE["urban"], SEEDS_CORE, planning=planning)
    elif stage == "S2":
        yield from core_stage(stage, "base", CORE["base"], SEEDS_CORE, planning=planning)
    elif stage == "S3":
        yield frontier_jobs("s3_frontier_urban", "urban")
        yield frontier_jobs("s3_frontier_base", "base")
    elif stage == "S4":
        for scen in ("urban", "base"):
            yield from core_stage(stage, scen, "s4_mixed_" + scen, SEEDS_LOAD, "mixed", rob=False, planning=planning,
                                  t_tune=T_TUNE_LOAD, t_test=T_TEST_LOAD)
        # downlink overload: test only, with the settings frozen under mixed traffic (urban)
        sel = None if planning else load_sel("s4_mixed_urban")
        if sel is not None or planning:
            yield test_jobs("s4_full_urban", "urban", sel, SEEDS_LOAD, "full", T_FULL, n_rules=2,
                            extra=["--fullRate=%g" % FULL_RATE])
        else:
            log("S4 full: no frozen settings in s4_mixed_urban; skipped")
    elif stage == "S5":
        for scen in ("urban", "base"):
            sel = None if planning else load_sel(CORE[scen])
            if sel is None and not planning:
                log("S5 %s: no frozen settings in %s (run S1/S2 first); skipped" % (scen, CORE[scen]))
                continue
            yield sens_jobs("s5_sens_" + scen, scen, sel)


ORDER = ["S1", "S2", "S3", "S4", "S5"]
TITLE = {"S1": "urban core (tuning, test seeds 1-20, fading subset)",
         "S2": "base core (tuning, test seeds 1-20, fading subset)",
         "S3": "all 48 configurations on the test cells (frontier)",
         "S4": "loaded network: traffic mixed (urban, base), overload test (urban)",
         "S5": "sensitivities with the frozen settings"}


def speed0():
    """Simulated seconds per wall second of a light 20-UE run on this machine, from finished rows."""
    v = []
    for folder in CORE.values():
        for r in read_results(folder):
            try:
                if r.get("fading") in ("0", "0.0") and float(r["nUe"]) == 20 and r.get("traffic", "light") in ("light", ""):
                    v.append(float(r["sim_per_wall"]))
            except (KeyError, ValueError):
                pass
    v.sort()
    return v[len(v) // 2] if v else 1.0


def plan(stages):
    sp = speed0()
    tot_n = tot_left = 0
    tot_h = left_h = 0.0
    print("%-3s %-58s %6s %6s %8s %8s" % ("", "stage", "jobs", "done", "hours", "left h"))
    for st in stages:
        n = d = 0
        cost = left = 0.0
        done_cache = {}
        for jobs in stage_lists(st, planning=True):
            for j in jobs:
                if j["folder"] not in done_cache:
                    done_cache[j["folder"]] = {r["job_id"] for r in read_results(j["folder"])}
                n += 1
                cost += j["cost"]
                if j["id"] in done_cache[j["folder"]]:
                    d += 1
                else:
                    left += j["cost"]
        h, lh = cost / sp / WORKERS / 3600.0, left / sp / WORKERS / 3600.0
        print("%-3s %-58s %6d %6d %8.2f %8.2f" % (st, TITLE[st], n, d, h, lh))
        tot_n += n; tot_left += n - d; tot_h += h; left_h += lh
    print("%-3s %-58s %6d %6d %8.2f %8.2f" % ("", "total (jobs / jobs left / hours / hours left)", tot_n, tot_left,
                                                tot_h, left_h))
    print("workers %d; %.2f simulated s per wall s for a light 20-UE run (%s); estimated finish %s"
          % (WORKERS, sp, "measured on this machine" if sp != 1.0 else "assumed, nothing measured yet",
             time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + left_h * 3600))))


def main():
    stages = ORDER
    for i, a in enumerate(sys.argv):
        if a == "--only" and i + 1 < len(sys.argv):
            stages = [s.strip().upper() for s in sys.argv[i + 1].split(",")]
        elif a.startswith("--only="):
            stages = [s.strip().upper() for s in a.split("=", 1)[1].split(",")]
    bad = [s for s in stages if s not in ORDER]
    if bad:
        raise SystemExit("unknown stage(s) %s; stages are %s" % (bad, ORDER))
    if "--status" in sys.argv or "--list" in sys.argv:
        return plan(stages)
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    with open(EXE_SRC, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    if not os.path.exists(EXE) or hashlib.sha256(open(EXE, "rb").read()).hexdigest() != sha:
        shutil.copy2(EXE_SRC, EXE)      # one frozen program copy for the whole study
    if BELOW and os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)
    log("run_study start/resume: stages %s; workers %d; program sha256 %s%s"
        % (",".join(stages), WORKERS, sha[:16], "; SMOKE" if SMOKE else ""))
    t0 = time.time()
    for st in stages:
        log("=== stage %s: %s" % (st, TITLE[st]))
        try:
            for jobs in stage_lists(st):
                run_jobs(st, jobs)
        except Exception as e:                      # a broken stage must not stop the others
            log("stage %s stopped by an error: %r" % (st, e))
    log("all stages done in %.2f h; failed jobs: %d" % ((time.time() - t0) / 3600.0, len(_failed)))
    for f in _failed:
        log("  failed: " + f)
    if "--no-analysis" not in sys.argv:
        for script in ("analyze_study.py",):         # the analysis script is one folder up; it reports on ROOT
            p = os.path.join(os.path.dirname(HERE), script)
            if os.path.exists(p):
                r = subprocess.run([sys.executable, p, "--root", ROOT],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                log("%s: exit code %d %s" % (script, r.returncode, (r.stdout.strip().splitlines() or [""])[-1]))
    with open(os.path.join(ROOT, "RUN_DONE"), "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " failed=%d\n" % len(_failed))
    log("RUN_DONE")


if __name__ == "__main__":
    main()
