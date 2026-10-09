# -*- coding: utf-8 -*-
"""Campaign driver: tuning -> automatic selection -> test -> robustness subset.

Standard library only:

    python campaign.py            # run / resume
    python campaign.py --status   # progress only
    python campaign.py --list     # job list only

Add "--scen urban" to any of them for the urban scenario (folder campaign_urban/ instead of
campaign/), and "--below-normal" to run the driver and its jobs at below-normal priority.

* every job is one run of ns3.48-ho-scenario-optimized.exe and has a unique id;
* a finished job appends exactly one row to campaign/results.csv; jobs whose id is already
  there are skipped, so the driver can be stopped and started again at any time;
* NS3_WORKERS jobs run at a time (default 5); tuning, selection (tuned_ns3.json), test and robustness follow each
  other automatically; campaign/DONE is written at the end.
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
CAMP = os.path.join(HERE, "campaign")
RES = os.path.join(CAMP, "res")
LOGS = os.path.join(CAMP, "logs")
BIN = os.path.join(CAMP, "bin")
RESULTS = os.path.join(CAMP, "results.csv")
TUNED = os.path.join(CAMP, "tuned_ns3.json")
LOG = os.path.join(CAMP, "campaign.log")
DONE = os.path.join(CAMP, "DONE")
NS3 = r"C:\cl\tools\ns3\ns-3-dev"
EXE_SRC = os.path.join(NS3, "build", "scratch", "ns3.48-ho-scenario-optimized.exe")
EXE = os.path.join(BIN, "ho-scenario.exe")
DLL_PATH = os.path.join(NS3, "build", "lib") + ";" + r"C:\cl\tools\msys64\ucrt64\bin"
WORKERS = int(os.environ.get("NS3_WORKERS", "5"))   # 5 of 8 logical CPUs: the machine stays usable
JOB_TIMEOUT = 6 * 3600
# CREATE_NO_WINDOW, plus BELOW_NORMAL_PRIORITY_CLASS for the runs when --below-normal is given
RUN_FLAGS = 0x08000000 | (0x00004000 if "--below-normal" in sys.argv else 0)

# ---------------------------------------------------------------------------- design
N_UE = 20
DISCARD = 60.0                      # start-up transient + history warm-up, excluded for every rule
T_TUNE = 150.0                      # 60 s discarded + 90 s measured
T_TEST = 180.0                      # 60 s discarded + 120 s measured
T_ROB = 120.0                       # 60 s discarded + 60 s measured (fast fading, 4x slower)
UDP_INTERVAL_MS = 100               # 10 packets/s per UE
VAL_TRACES = [(400, 16, 101), (400, 30, 102), (200, 16, 103), (200, 30, 104)]   # (ISD, speed, seed)
TEST_ISD = [200, 400]
TEST_SPEED = [8, 16, 30]
TEST_SEEDS = list(range(1, 11))
ROB_CELL = (400, 16)
REF_A3 = dict(hyst=3, ttt=300)      # reference of the selection rule

A3_GRID = [dict(hyst=h, ttt=t) for h in (1, 2, 3, 4, 5, 6) for t in (100, 300, 500, 1000)]
ROAM_TRIPLES = [(14, 8, 8), (6, 4, 6), (10, 6, 3)]          # (eta_H, eta_L, eta_A)
ROAM_GRID = [dict(h0=h0, ttt=t, etaH=e[0], etaL=e[1], etaA=e[2], mCap=c)
             for h0 in (1, 2) for t in (100, 300) for e in ROAM_TRIPLES for c in (5, 9)]
ETA_S = 4

# ---------------------------------------------------------------------------- scenario
# "base": the open-area scenario of phase 2, folder campaign/ (default, unchanged).
# "urban": the TR 37.885 street grid with buildings, folder campaign_urban/. Same phases, grids,
# selection rule and sizes; the only difference in the job arguments is --scen=urban.
SCEN = os.environ.get("NS3_SCEN", "base")
for _i, _a in enumerate(sys.argv):
    if _a == "--scen" and _i + 1 < len(sys.argv):
        SCEN = sys.argv[_i + 1]
    elif _a.startswith("--scen="):
        SCEN = _a.split("=", 1)[1]
SCEN_ARGS = []
if SCEN == "urban":
    CAMP = os.path.join(HERE, "campaign_urban")
    RES, LOGS, BIN = (os.path.join(CAMP, d) for d in ("res", "logs", "bin"))
    RESULTS, TUNED = os.path.join(CAMP, "results.csv"), os.path.join(CAMP, "tuned_ns3.json")
    LOG, DONE, EXE = os.path.join(CAMP, "campaign.log"), os.path.join(CAMP, "DONE"), os.path.join(BIN, "ho-scenario.exe")
    SCEN_ARGS = ["--scen=urban"]
elif SCEN != "base":
    raise SystemExit("unknown scenario %r (base | urban)" % SCEN)

if os.environ.get("NS3STUDY_SMOKE"):
    # two-minute end-to-end test of the driver itself (separate directory, tiny design)
    CAMP = CAMP + "_smoke"
    RES, LOGS, BIN = (os.path.join(CAMP, d) for d in ("res", "logs", "bin"))
    RESULTS, TUNED = os.path.join(CAMP, "results.csv"), os.path.join(CAMP, "tuned_ns3.json")
    LOG, DONE, EXE = os.path.join(CAMP, "campaign.log"), os.path.join(CAMP, "DONE"), os.path.join(BIN, "ho-scenario.exe")
    DISCARD, T_TUNE, T_TEST, T_ROB = 5.0, 20.0, 20.0, 8.0
    VAL_TRACES, TEST_ISD, TEST_SPEED, TEST_SEEDS = VAL_TRACES[:1], [400], [16], [1]
    A3_GRID = [dict(hyst=3, ttt=300), dict(hyst=5, ttt=100)]
    ROAM_GRID = ROAM_GRID[:1] + ROAM_GRID[-1:]

_lock = threading.Lock()


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _lock:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line, flush=True)


def a3_label(c):
    return "A3_h%g_t%d" % (c["hyst"], c["ttt"])


def roam_label(c):
    return "ROAM_h%g_t%d_e%g-%g-%g_c%g" % (c["h0"], c["ttt"], c["etaH"], c["etaL"], c["etaA"], c["mCap"])


def a3_args(c):
    return ["--rule=a3", "--hyst=%g" % c["hyst"], "--ttt=%d" % c["ttt"]]


def roam_args(c):
    return ["--rule=roam", "--h0=%g" % c["h0"], "--ttt=%d" % c["ttt"], "--etaH=%g" % c["etaH"],
            "--etaL=%g" % c["etaL"], "--etaA=%g" % c["etaA"], "--etaS=%g" % c.get("etaS", ETA_S),
            "--mCap=%g" % c["mCap"]]


def make_job(phase, label, config, args, isd, speed, seed, sim_time, fading=0):
    jid = "%s_%s_d%d_v%d_s%d" % (phase, label, isd, speed, seed)
    return dict(id=jid, phase=phase, label=label, config=config, isd=isd, speed=speed, seed=seed,
                args=args + SCEN_ARGS + ["--isd=%d" % isd, "--speed=%d" % speed, "--rngRun=%d" % seed,
                             "--simTime=%g" % sim_time, "--discard=%g" % DISCARD,
                             "--nUe=%d" % N_UE, "--udpInterval=%d" % UDP_INTERVAL_MS,
                             "--fading=%d" % fading, "--events=1", "--tag=%s" % jid,
                             "--outDir=%s" % RES.replace("\\", "/")])


def tuning_jobs():
    jobs = []
    for isd, speed, seed in VAL_TRACES:              # trace by trace, so partial results are balanced
        for c in A3_GRID:
            jobs.append(make_job("tune", a3_label(c), a3_label(c), a3_args(c), isd, speed, seed, T_TUNE))
        for c in ROAM_GRID:
            jobs.append(make_job("tune", roam_label(c), roam_label(c), roam_args(c), isd, speed, seed, T_TUNE))
    return jobs


def test_rules(sel):
    a3, ro = sel["A3"]["config"], sel["ROAM"]["config"]
    ov = dict(ro, etaH=0, etaL=0)
    hi = dict(ro, etaA=0)
    base = dict(hyst=ro["h0"], ttt=ro["ttt"])
    return [("A3_tuned", a3_label(a3), a3_args(a3)),
            ("ROAM", roam_label(ro), roam_args(ro)),
            ("ROAM_overlap", roam_label(ov), roam_args(ov)),
            ("ROAM_history", roam_label(hi), roam_args(hi)),
            ("A3_h0", a3_label(base), a3_args(base))]


def test_jobs(sel):
    rules = test_rules(sel)
    jobs = []
    for seed in TEST_SEEDS:                           # seed by seed: every finished seed is a complete paired block
        for isd in TEST_ISD:
            for speed in TEST_SPEED:
                for label, config, args in rules:
                    jobs.append(make_job("test", label, config, args, isd, speed, seed, T_TEST))
    return jobs


def robust_jobs(sel):
    rules = test_rules(sel)[:2]
    isd, speed = ROB_CELL
    return [make_job("rob", label, config, args, isd, speed, seed, T_ROB, fading=1)
            for seed in TEST_SEEDS for label, config, args in rules]


# ---------------------------------------------------------------------------- results file
def read_results():
    if not os.path.exists(RESULTS):
        return []
    with open(RESULTS, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_result(job, metrics):
    row = dict(job_id=job["id"], phase=job["phase"], label=job["label"], config=job["config"])
    row.update(metrics)
    with _lock:
        new = not os.path.exists(RESULTS)
        if not new:
            with open(RESULTS, newline="", encoding="utf-8") as f:
                header = next(csv.reader(f))
        else:
            header = list(row.keys())
        with open(RESULTS, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)


# ---------------------------------------------------------------------------- running
def run_one(job):
    env = dict(os.environ)
    env["PATH"] = DLL_PATH + ";" + env.get("PATH", "")
    jpath = os.path.join(RES, job["id"] + ".json")
    for attempt in (1, 2):
        if os.path.exists(jpath):
            os.remove(jpath)
        t0 = time.time()
        with open(os.path.join(LOGS, job["id"] + ".log"), "w", encoding="utf-8") as lf:
            try:
                rc = subprocess.run([EXE] + job["args"], stdout=lf, stderr=subprocess.STDOUT, env=env,
                                    cwd=CAMP, timeout=JOB_TIMEOUT, creationflags=RUN_FLAGS).returncode
            except subprocess.TimeoutExpired:
                rc = -999
        if rc == 0 and os.path.exists(jpath):
            with open(jpath, encoding="utf-8") as f:
                metrics = json.load(f)
            append_result(job, metrics)
            return True, time.time() - t0
        log("FAILED %s (attempt %d, exit code %s)" % (job["id"], attempt, rc))
    return False, 0.0


def run_jobs(jobs, name):
    done = {r["job_id"] for r in read_results()}
    todo = [j for j in jobs if j["id"] not in done]
    log("phase %s: %d jobs, %d already finished, %d to run" % (name, len(jobs), len(jobs) - len(todo), len(todo)))
    if not todo:
        return
    state = dict(n=0, fail=0, t0=time.time())

    def work(job):
        ok, wall = run_one(job)
        with _lock:
            state["n"] += 1
            state["fail"] += (not ok)
            n = state["n"]
        el = time.time() - state["t0"]
        eta = el / n * (len(todo) - n)
        log("%s %d/%d %s %s wall=%.0fs  phase ETA %.1f h" % (name, n, len(todo), "ok" if ok else "FAIL",
                                                              job["id"], wall, eta / 3600.0))

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    log("phase %s finished: %d run, %d failed, %.2f h" % (name, state["n"], state["fail"],
                                                           (time.time() - state["t0"]) / 3600.0))


# ---------------------------------------------------------------------------- selection
def select():
    """The paper's rule: among the configurations whose mobility-failure rate does not exceed that
    of the reference A3 (3 dB, 300 ms) on the same validation traces, take the one with the fewest
    unnecessary handovers per UE-minute; if none meets the budget, the one with the lowest failure
    rate."""
    rows = [r for r in read_results() if r["phase"] == "tune"]
    agg = {}
    for r in rows:
        a = agg.setdefault(r["label"], dict(un=0.0, fail=0.0, att=0.0, uemin=0.0, n=0))
        a["un"] += float(r["unnecessary"]); a["fail"] += float(r["failures"])
        a["att"] += float(r["attempts"]); a["uemin"] += float(r["ue_min"]); a["n"] += 1
    table = {}
    for lab, a in agg.items():
        table[lab] = dict(val_UHO_pm=a["un"] / a["uemin"], val_fail_pm=a["fail"] / a["uemin"],
                          val_HO_pm=a["att"] / a["uemin"], traces=a["n"],
                          unnecessary=a["un"], failures=a["fail"])
    ref = a3_label(REF_A3)
    if ref not in table:
        log("ABORT: the reference configuration %s has no tuning result" % ref)
        raise SystemExit(2)
    budget = table[ref]["val_fail_pm"]
    out = {"_budget_fail_pm": budget, "_reference": ref,
           "_validation_traces": [dict(isd=i, speed=v, seed=s) for i, v, s in VAL_TRACES],
           "_selection_rule": "min UHO_pm subject to fail_pm <= fail_pm(reference A3); "
                              "if none, min fail_pm; ties: lower fail_pm, then lower HO_pm, then grid order",
           "_incomplete": sorted(l for l, t in table.items() if t["traces"] != len(VAL_TRACES))}
    for name, grid, labf in (("A3", A3_GRID, a3_label), ("ROAM", ROAM_GRID, roam_label)):
        cands = [(i, c, table[labf(c)]) for i, c in enumerate(grid) if labf(c) in table]
        ok = [x for x in cands if x[2]["val_fail_pm"] <= budget + 1e-12]
        if ok:
            best = min(ok, key=lambda x: (x[2]["val_UHO_pm"], x[2]["val_fail_pm"], x[2]["val_HO_pm"], x[0]))
            met = True
        else:
            best = min(cands, key=lambda x: (x[2]["val_fail_pm"], x[2]["val_UHO_pm"], x[0]))
            met = False
        cfg = dict(best[1])
        if name == "ROAM":
            cfg["etaS"] = ETA_S
        out[name] = dict(config=cfg, label=labf(best[1]), met_budget=met, n_meeting_budget=len(ok),
                         **{k: best[2][k] for k in ("val_UHO_pm", "val_fail_pm", "val_HO_pm")})
        out[name + "_grid"] = {labf(c): table.get(labf(c)) for c in grid}
    with open(TUNED, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    log("selection: budget fail_pm=%.4f (reference %s)" % (budget, ref))
    for name in ("A3", "ROAM"):
        s = out[name]
        log("selected %s: %s  UHO_pm=%.3f fail_pm=%.4f HO_pm=%.2f met_budget=%s (%d of %d meet it)"
            % (name, s["label"], s["val_UHO_pm"], s["val_fail_pm"], s["val_HO_pm"], s["met_budget"],
               s["n_meeting_budget"], len(out[name + "_grid"])))
    return out


def status():
    rows = read_results()
    by = {}
    for r in rows:
        by[r["phase"]] = by.get(r["phase"], 0) + 1
    n_t = len(tuning_jobs())
    n_test = len(TEST_SEEDS) * len(TEST_ISD) * len(TEST_SPEED) * 5
    n_rob = len(TEST_SEEDS) * 2
    print("tuning %d/%d   test %d/%d   robustness %d/%d   total %d/%d   DONE marker: %s"
          % (by.get("tune", 0), n_t, by.get("test", 0), n_test, by.get("rob", 0), n_rob,
             len(rows), n_t + n_test + n_rob, os.path.exists(DONE)))
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            for line in f.readlines()[-4:]:
                print(line.rstrip())


def main():
    for d in (CAMP, RES, LOGS, BIN):
        os.makedirs(d, exist_ok=True)
    if "--status" in sys.argv:
        return status()
    if "--list" in sys.argv:
        for j in tuning_jobs():
            print(j["id"])
        print("# + 300 test jobs and 20 robustness jobs, named after the selection")
        return
    if not os.path.exists(EXE):
        shutil.copy2(EXE_SRC, EXE)            # frozen copy: a later rebuild cannot change a running campaign
    with open(EXE, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    if "--below-normal" in sys.argv:
        # BELOW_NORMAL_PRIORITY_CLASS for the driver; the runs it starts inherit it
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)
    log("campaign start/resume; scenario %s; exe sha256 %s; workers %d" % (SCEN, sha[:16], WORKERS))
    if os.path.exists(DONE):
        os.remove(DONE)
    run_jobs(tuning_jobs(), "tune")
    sel = select()
    run_jobs(test_jobs(sel), "test")
    run_jobs(robust_jobs(sel), "rob")
    n = len(read_results())
    with open(DONE, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " rows=%d\n" % n)
    log("DONE: %d rows in results.csv" % n)


if __name__ == "__main__":
    main()
