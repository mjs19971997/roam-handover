# -*- coding: utf-8 -*-
"""Analysis of one stage of the ns-3 study (ROAM versus Event A3).

    python analyze_ns3.py results/campaign_urban        # a stage folder, or its results.csv
    python analyze_ns3.py                               # results/campaign (open area, core)
    python analyze_ns3.py urban                         # results/campaign_urban

Reads the results.csv of the campaign (whatever is finished), prints

  * the tuning table and the automatic selection,
  * per speed and inter-site distance: mean +/- 95 % confidence interval (Student t over seeds)
    of every metric for every rule,
  * ROAM (and its ablations) against the tuned A3: relative change of the means, mean paired
    difference with its confidence interval and the two-sided paired Wilcoxon signed-rank test
    (exact null distribution, ties get average ranks, zero differences are dropped),
  * the same pooled over all cells, and for the fast-fading robustness subset,

and writes ns3_summary.json next to the results file. Standard library only (scipy is used for
the t quantile when it can be imported).
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
METRICS = ["ho_pm", "uho_pm", "fail_pm", "uhr", "pp_ratio", "delivery", "sinr_db"]
EXTRA = ["attempts", "useful", "unnecessary", "early", "late", "censored", "failures",
         "rlf_t310", "rlf_late_cmd", "rlf_during_ho", "rlf_rlc", "rlf_no_pending", "pp",
         "mean_margin", "dwell_s", "los_serving"]
RULES = ["A3_tuned", "ROAM", "ROAM_overlap", "ROAM_history", "A3_h0"]
PAIRS = [("ROAM", "A3_tuned"), ("ROAM_overlap", "A3_tuned"), ("ROAM_history", "A3_tuned"),
         ("A3_h0", "A3_tuned"), ("ROAM", "A3_h0"), ("ROAM", "ROAM_overlap"), ("ROAM", "ROAM_history")]

_T975 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179,
         2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060,
         2.056, 2.052, 2.048, 2.045, 2.042]


def t975(df):
    try:
        from scipy import stats
        return float(stats.t.ppf(0.975, df))
    except Exception:
        if df < 1:
            return float("nan")
        if df <= 30:
            return _T975[df]
        return 1.96 + 2.4 / df


def mean_ci(x):
    n = len(x)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(x) / n
    if n < 2:
        return m, float("nan")
    s = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m, t975(n - 1) * s / math.sqrt(n)


# Rates per UE-minute are counts divided by the UE-minutes of a run and are stored in results.csv with
# eight significant digits.  Differences of equal counts then differ in the last stored digit, and a
# tolerance of 1e-12 would rank such tied differences as if they were distinct.  For the count rates the
# signed-rank test therefore treats differences within TIE_TOL as tied (and as zero): the rounding error
# of a difference is below 3e-6 for rates up to 30, the smallest true step is 1/UE-minutes >= 0.003.
TIE_TOL = 1e-5
COUNT_RATES = ("uho_pm", "fail_pm", "ho_pm")


def wilcoxon(d, tol=1e-12):
    """Two-sided exact Wilcoxon signed-rank p-value for paired differences d (average ranks for ties,
    zeros dropped; differences within tol count as tied)."""
    d = [v for v in d if abs(v) > tol]
    n = len(d)
    if n == 0:
        return 1.0, 0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks2 = [0] * n                      # twice the average rank (integer)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) <= tol:
            j += 1
        r2 = (i + 1) + (j + 1)            # 2 * mean of ranks i+1..j+1
        for k in range(i, j + 1):
            ranks2[order[k]] = r2
        i = j + 1
    w_plus = sum(r for r, v in zip(ranks2, d) if v > 0)
    total = sum(ranks2)
    dist = [0.0] * (total + 1)
    dist[0] = 1.0
    for r in ranks2:                      # exact null distribution of W+ by dynamic programming
        for s in range(total, r - 1, -1):
            dist[s] += dist[s - r]
    z = float(2 ** n)
    lo = sum(dist[: w_plus + 1]) / z
    hi = sum(dist[w_plus:]) / z
    return min(1.0, 2.0 * min(lo, hi)), n


def num(r, k):
    try:
        return float(r[k])
    except Exception:
        return float("nan")


def fmt(m, ci, p=3):
    if m != m:
        return "n/a"
    if ci != ci:
        return ("%." + str(p) + "f") % m
    return ("%." + str(p) + "f +/- %." + str(p) + "f") % (m, ci)


def compare(cellrows, a, b, metric):
    """a against b, paired by (isd, speed, seed)."""
    xa = {(r["isd"], r["speed"], r["rngRun"]): num(r, metric) for r in cellrows if r["label"] == a}
    xb = {(r["isd"], r["speed"], r["rngRun"]): num(r, metric) for r in cellrows if r["label"] == b}
    keys = sorted(set(xa) & set(xb))
    if not keys:
        return None
    va, vb = [xa[k] for k in keys], [xb[k] for k in keys]
    d = [p - q for p, q in zip(va, vb)]
    ma, mb = sum(va) / len(va), sum(vb) / len(vb)
    md, ci = mean_ci(d)
    p, nz = wilcoxon(d, TIE_TOL if metric in COUNT_RATES else 1e-12)
    return dict(n_pairs=len(keys), mean_a=ma, mean_b=mb, diff=md, diff_ci95=ci,
                rel_change_pct=(100.0 * (ma - mb) / mb) if abs(mb) > 1e-12 else None,
                wilcoxon_p=p, nonzero_pairs=nz)


def block(rows, title, summary, key):
    """Rules table + paired comparisons for one set of rows."""
    out = dict(rules={}, comparisons={})
    labels = [l for l in RULES if any(r["label"] == l for r in rows)]
    if not labels:
        return
    print("\n" + title)
    print("  %-13s %3s  %-17s %-17s %-17s %-15s %-15s %-17s %-15s" %
          ("rule", "n", "HO/UE-min", "UHO/UE-min", "fail/UE-min", "UHR", "ping-pong", "delivery", "SINR dB"))
    for l in labels:
        rr = [r for r in rows if r["label"] == l]
        st = {}
        cells = []
        for m in METRICS:
            mu, ci = mean_ci([num(r, m) for r in rr])
            st[m] = dict(mean=mu, ci95=ci)
            cells.append(fmt(mu, ci, 4 if m in ("delivery",) else 3))
        for m in EXTRA:
            mu, ci = mean_ci([num(r, m) for r in rr])
            st[m] = dict(mean=mu, ci95=ci)
        st["n"] = len(rr)
        st["config"] = rr[0]["config"]
        out["rules"][l] = st
        print("  %-13s %3d  %-17s %-17s %-17s %-15s %-15s %-17s %-15s" % tuple([l, len(rr)] + cells))
    # failure causes: totals over the runs of the rule (failures = T310 + late command +
    # failure during execution + RLC; "early" and "no HO pending" split the T310 expiries)
    print("  failure causes, total over runs (UE-minutes in brackets):")
    for l in labels:
        rr = [r for r in rows if r["label"] == l]
        tot = lambda k: sum(v for v in (num(r, k) for r in rr) if v == v)
        fc = dict(ue_min=tot("ue_min"), failures=tot("failures"), t310_expiry=tot("rlf_t310"),
                  late_command=tot("rlf_late_cmd"), during_handover=tot("rlf_during_ho"),
                  rlc_max_retx=tot("rlf_rlc"), t310_in_target_early=tot("early"),
                  t310_no_handover_pending=tot("rlf_no_pending"))
        out["rules"][l]["failure_causes_total"] = fc
        los = [num(r, "los_serving") for r in rr if "los_serving" in r and num(r, "los_serving") >= 0]
        print("    %-13s [%6.0f] failures %4d = T310 expiry %4d (early in target %d, no handover pending %d)"
              " + late command %4d + during handover %d + RLC %d%s"
              % (l, fc["ue_min"], fc["failures"], fc["t310_expiry"], fc["t310_in_target_early"],
                 fc["t310_no_handover_pending"], fc["late_command"], fc["during_handover"],
                 fc["rlc_max_retx"], ("; LOS to serving site %.1f %% of time" % (100 * sum(los) / len(los))) if los else ""))
    for a, b in PAIRS:
        if a in labels and b in labels:
            cm = {}
            for m in ("uho_pm", "fail_pm", "ho_pm", "uhr", "pp_ratio", "delivery", "sinr_db"):
                c = compare(rows, a, b, m)
                if c:
                    cm[m] = c
            if not cm:
                continue
            out["comparisons"]["%s_vs_%s" % (a, b)] = cm
            parts = []
            for m in ("uho_pm", "fail_pm", "ho_pm", "delivery"):
                c = cm.get(m)
                if c:
                    rc = ("%+.1f%%" % c["rel_change_pct"]) if c["rel_change_pct"] is not None else "n/a"
                    parts.append("%s %s (diff %s, p=%.3g)" % (m, rc, fmt(c["diff"], c["diff_ci95"]), c["wilcoxon_p"]))
            print("    %s vs %s [%d pairs]: %s" % (a, b, cm["uho_pm"]["n_pairs"], "; ".join(parts)))
    summary[key] = out


def main():
    # argument: nothing (base campaign), "urban" / "--scen urban", a campaign folder, or a results.csv
    args = [a for a in sys.argv[1:] if a != "--scen"]
    path = os.path.join(HERE, "results", "campaign", "results.csv")
    if args:
        a = args[0].split("=", 1)[-1]
        if a in ("urban", "base"):
            path = os.path.join(HERE, "results", "campaign_urban" if a == "urban" else "campaign", "results.csv")
        elif os.path.isdir(a):
            path = os.path.join(a, "results.csv")
        else:
            path = a
    if not os.path.exists(path):
        print("no results file yet: %s" % path)
        return
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by = defaultdict(int)
    for r in rows:
        by[r["phase"]] += 1
    print("results: %s" % path)
    print("rows: %d  (tuning %d, test %d, robustness %d)" % (len(rows), by["tune"], by["test"], by["rob"]))
    summary = dict(rows=len(rows), by_phase=dict(by))

    # ---- sanity: outcome counts add up to the attempts
    bad = [r["job_id"] for r in rows if int(float(r["sum_outcomes"])) != int(float(r["attempts"]))]
    print("outcome counts equal the number of attempts in %d of %d runs" % (len(rows) - len(bad), len(rows)))
    summary["runs_with_outcome_sum_mismatch"] = bad
    wall = [num(r, "wall_s") for r in rows]
    simt = [num(r, "simTime") for r in rows]
    if wall:
        print("wall time per run: mean %.0f s; simulated %.0f s in %.1f h of single-run wall time"
              % (sum(wall) / len(wall), sum(simt), sum(wall) / 3600.0))

    # ---- tuning
    tune = [r for r in rows if r["phase"] == "tune"]
    if tune:
        agg = defaultdict(lambda: dict(un=0.0, fail=0.0, att=0.0, uemin=0.0, n=0))
        for r in tune:
            a = agg[r["label"]]
            a["un"] += num(r, "unnecessary"); a["fail"] += num(r, "failures")
            a["att"] += num(r, "attempts"); a["uemin"] += num(r, "ue_min"); a["n"] += 1
        tuned_path = os.path.join(os.path.dirname(path), "tuned_ns3.json")
        sel = json.load(open(tuned_path, encoding="utf-8")) if os.path.exists(tuned_path) else {}
        chosen = {sel.get(k, {}).get("label") for k in ("A3", "ROAM")}
        print("\nTUNING (validation traces; * = selected, R = reference of the failure budget)")
        print("  %-28s %6s %10s %10s %10s" % ("configuration", "traces", "HO/UE-min", "UHO/UE-min", "fail/UE-min"))
        tt = {}
        for lab in sorted(agg, key=lambda l: (not l.startswith("A3"), agg[l]["un"] / max(agg[l]["uemin"], 1e-9))):
            a = agg[lab]
            u = max(a["uemin"], 1e-9)
            tt[lab] = dict(traces=a["n"], ho_pm=a["att"] / u, uho_pm=a["un"] / u, fail_pm=a["fail"] / u)
            mark = ("*" if lab in chosen else " ") + ("R" if lab == sel.get("_reference", "A3_h3_t300") else " ")
            print("  %-28s %6d %10.3f %10.3f %10.4f %s" % (lab, a["n"], a["att"] / u, a["un"] / u, a["fail"] / u, mark))
        summary["tuning"] = tt
        if sel:
            summary["selection"] = {k: sel[k] for k in sel if not k.endswith("_grid")}
            print("  failure budget %.4f per UE-minute; selected A3: %s; selected ROAM: %s"
                  % (sel["_budget_fail_pm"], sel["A3"]["label"], sel["ROAM"]["label"]))

    # ---- test
    test = [r for r in rows if r["phase"] == "test"]
    if test:
        cells = sorted({(int(float(r["isd"])), int(float(r["speed"]))) for r in test})
        summary["test"] = {}
        for isd, speed in cells:
            rr = [r for r in test if int(float(r["isd"])) == isd and int(float(r["speed"])) == speed]
            block(rr, "TEST  ISD %d m, speed %d m/s" % (isd, speed), summary["test"], "isd%d_v%d" % (isd, speed))
        block(test, "TEST  all cells pooled (pairs = cell x seed)", summary["test"], "pooled")

    rob = [r for r in rows if r["phase"] == "rob"]
    if rob:
        summary["robustness_fast_fading"] = {}
        block(rob, "ROBUSTNESS  fast fading on, ISD %s m, %s m/s" % (rob[0]["isd"], rob[0]["speed"]),
              summary["robustness_fast_fading"], "fading")

    outp = os.path.join(os.path.dirname(path), "ns3_summary.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print("\nwritten: %s" % outp)


if __name__ == "__main__":
    main()
