# -*- coding: utf-8 -*-
"""Consolidated analysis of the ROAM-versus-A3 study (all stages that have results).

    python analyze_study.py [--root <folder with the stage folders>]      (default: results)

Writes report_study.txt and report_study.json next to the stage folders, and a per-stage
report.txt / ns3_summary.json in every campaign-like folder (analyze_ns3.py). Standard library only.

Sections: 1 core (per scenario), 2 comparison at equal failure rate and Pareto fronts (frontier
runs), 3 loaded network, 4 sensitivities, 5 per-class service metrics.
Primary endpoints (PLAN.md): unnecessary handovers and failures per UE-minute, ROAM against
the tuned A3, paired by seed (and cell), core stages. Everything else is exploratory.
"""
import csv
import io
import json
import os
import sys
from collections import defaultdict
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze_ns3 as A

ROOT = os.path.join(HERE, "results")
for _i, _a in enumerate(sys.argv):          # --root <dir>: analyse a copy of the stage folders elsewhere
    if _a == "--root" and _i + 1 < len(sys.argv):
        ROOT = os.path.abspath(sys.argv[_i + 1])
CORE = [("urban", "campaign_urban"), ("base", "campaign")]
FRONT = [("urban", "s3_frontier_urban"), ("base", "s3_frontier_base")]
LOAD = [("urban, traffic mixed", "s4_mixed_urban"), ("base, traffic mixed", "s4_mixed_base"),
        ("urban, traffic full", "s4_full_urban")]
SENS = [("urban", "s5_sens_urban"), ("base", "s5_sens_base")]
SVC = ["voice", "vcall", "gaming", "stream", "web"]
OUT = []


def P(s=""):
    OUT.append(s)
    print(s)


def rows_of(folder):
    p = os.path.join(ROOT, folder, "results.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(r, k):
    return A.num(r, k)


def key(r):
    return (r["isd"], r["speed"], r["rngRun"])


def paired(rows, a, b, metric):
    c = A.compare(rows, a, b, metric)
    if not c:
        return None, "n/a"
    rc = ("%+.1f%%" % c["rel_change_pct"]) if c["rel_change_pct"] is not None else "n/a"
    return c, "%.3f vs %.3f (%s, diff %s, Wilcoxon p=%.2g, %d pairs)" % (
        c["mean_a"], c["mean_b"], rc, A.fmt(c["diff"], c["diff_ci95"]), c["wilcoxon_p"], c["n_pairs"])


def per_stage_reports(folders):
    for folder in folders:
        p = os.path.join(ROOT, folder, "results.csv")
        if not os.path.exists(p):
            continue
        buf = io.StringIO()
        old = sys.argv
        try:
            sys.argv = ["analyze_ns3.py", p]
            with redirect_stdout(buf):
                A.main()
        except Exception as e:                      # a per-stage report must not stop the rest
            buf.write("\nreport failed: %r\n" % (e,))
        finally:
            sys.argv = old
        with open(os.path.join(ROOT, folder, "report.txt"), "w", encoding="utf-8") as f:
            f.write(buf.getvalue())


def core_section(js):
    P("1. CORE: tuned A3 against ROAM and its ablations (primary endpoints: UHO and failures per UE-minute)")
    for scen, folder in CORE:
        rows = [r for r in rows_of(folder) if r["phase"] == "test"]
        if not rows:
            P("  %s: no test rows yet" % scen)
            continue
        tp = os.path.join(ROOT, folder, "tuned_ns3.json")
        sel = json.load(open(tp, encoding="utf-8")) if os.path.exists(tp) else {}
        seeds = sorted({int(float(r["rngRun"])) for r in rows})
        P("  %s  (%d test rows, seeds %d-%d; frozen: A3 %s, ROAM %s; failure budget of the tuning %.3f)"
          % (scen, len(rows), seeds[0], seeds[-1], sel.get("A3", {}).get("label", "?"),
             sel.get("ROAM", {}).get("label", "?"), sel.get("_budget_fail_pm", float("nan"))))
        d = js.setdefault("core", {}).setdefault(scen, {})
        P("    %-13s %4s %-16s %-16s %-16s %-14s" % ("rule", "n", "UHO/UE-min", "fail/UE-min", "HO/UE-min", "delivery"))
        for lab in A.RULES:
            rr = [r for r in rows if r["label"] == lab]
            if not rr:
                continue
            st = {m: A.mean_ci([num(r, m) for r in rr]) for m in ("uho_pm", "fail_pm", "ho_pm", "delivery")}
            d.setdefault("rules", {})[lab] = {m: dict(mean=v[0], ci95=v[1]) for m, v in st.items()}
            P("    %-13s %4d %-16s %-16s %-16s %-14s" % (lab, len(rr), A.fmt(*st["uho_pm"]), A.fmt(*st["fail_pm"]),
                                                         A.fmt(*st["ho_pm"]), A.fmt(*st["delivery"], p=4)))
        for a, b in A.PAIRS[:4]:
            for m in ("uho_pm", "fail_pm"):
                c, txt = paired(rows, a, b, m)
                if c:
                    d.setdefault("pooled", {})["%s_vs_%s_%s" % (a, b, m)] = c
                    P("    %-12s vs %-8s %-8s %s" % (a, b, m, txt))
        new = [r for r in rows if int(float(r["rngRun"])) > 10]
        if scen == "urban" and new:
            P("    seeds 11-20 only (run after the plan was written; seeds 1-10 were known before):")
            for m in ("uho_pm", "fail_pm"):
                c, txt = paired(new, "ROAM", "A3_tuned", m)
                if c:
                    d.setdefault("seeds_11_20", {})["ROAM_vs_A3_tuned_" + m] = c
                    P("    ROAM         vs A3_tuned %-8s %s" % (m, txt))
        P("    by cell, ROAM vs A3_tuned:")
        for isd, v in sorted({(int(float(r["isd"])), int(float(r["speed"]))) for r in rows}):
            rr = [r for r in rows if int(float(r["isd"])) == isd and int(float(r["speed"])) == v]
            c1, t1 = paired(rr, "ROAM", "A3_tuned", "uho_pm")
            c2, t2 = paired(rr, "ROAM", "A3_tuned", "fail_pm")
            d.setdefault("cells", {})["isd%d_v%d" % (isd, v)] = dict(uho_pm=c1, fail_pm=c2)
            P("      ISD %3d m %2d m/s  UHO %s" % (isd, v, t1))
            P("      %19s fail %s" % ("", t2))
        rob = [r for r in rows_of(folder) if r["phase"] == "rob"]
        if rob:
            for m in ("uho_pm", "fail_pm"):
                c, txt = paired(rob, "ROAM", "A3_tuned", m)
                d.setdefault("fast_fading_subset", {})[m] = c
                P("    fast-fading subset  %-8s %s" % (m, txt))
    P()


def config_table(rows):
    """Per configuration: totals over all cells and seeds, and per-(cell, seed) values."""
    t = {}
    for r in rows:
        a = t.setdefault(r["label"], dict(un=0.0, fail=0.0, att=0.0, uemin=0.0, n=0, per={}))
        a["un"] += num(r, "unnecessary"); a["fail"] += num(r, "failures")
        a["att"] += num(r, "attempts"); a["uemin"] += num(r, "ue_min"); a["n"] += 1
        a["per"][key(r)] = (num(r, "uho_pm"), num(r, "fail_pm"))
    for a in t.values():
        u = max(a["uemin"], 1e-9)
        a["uho_pm"], a["fail_pm"], a["ho_pm"] = a["un"] / u, a["fail"] / u, a["att"] / u
    return t


def pareto(t, labels):
    front = []
    for l in labels:
        if not any((t[o]["fail_pm"] <= t[l]["fail_pm"] and t[o]["uho_pm"] <= t[l]["uho_pm"]) and
                   (t[o]["fail_pm"] < t[l]["fail_pm"] or t[o]["uho_pm"] < t[l]["uho_pm"]) for o in labels):
            front.append(l)
    return sorted(front, key=lambda l: (t[l]["fail_pm"], t[l]["uho_pm"]))


def pair_cfg(t, a, b, idx):
    ks = sorted(set(t[a]["per"]) & set(t[b]["per"]))
    d = [t[a]["per"][k][idx] - t[b]["per"][k][idx] for k in ks]
    m, ci = A.mean_ci(d)
    p, _ = A.wilcoxon(d, A.TIE_TOL)          # idx 0, 1: unnecessary handovers and failures per UE-minute (count rates)
    return dict(n_pairs=len(ks), diff=m, diff_ci95=ci, wilcoxon_p=p)


def frontier_section(js):
    P("2. EQUAL FAILURE RATE AND PARETO FRONTS (every tuning configuration run on the test cells)")
    P("   Rates are totals over all cells and seeds divided by the UE-minutes. Picking the best")
    P("   configuration of a family on these same runs favours that family (no held-out data).")
    for scen, folder in FRONT:
        rows = rows_of(folder)
        if not rows:
            P("  %s: no frontier rows yet" % scen)
            continue
        t = config_table(rows)
        a3 = [l for l in t if l.startswith("A3_")]
        ro = [l for l in t if l.startswith("ROAM_")]
        d = js.setdefault("frontier", {}).setdefault(scen, {})
        d["configs"] = {l: {k: t[l][k] for k in ("uho_pm", "fail_pm", "ho_pm", "n")} for l in t}
        core = dict(CORE)[scen]
        tp = os.path.join(ROOT, core, "tuned_ns3.json")
        sel = json.load(open(tp, encoding="utf-8")) if os.path.exists(tp) else {}
        fa, fr = sel.get("A3", {}).get("label"), sel.get("ROAM", {}).get("label")
        P("  %s  (%d rows, %d A3 and %d ROAM configurations, %d runs each at most)"
          % (scen, len(rows), len(a3), len(ro), max(v["n"] for v in t.values())))
        for name, own, other, frozen in (("ROAM", ro, a3, fr), ("A3", a3, ro, fa)):
            if frozen not in t or not other:
                continue
            f0 = t[frozen]
            ok = [l for l in other if t[l]["fail_pm"] <= f0["fail_pm"] + 1e-12]
            oname = "A3" if name == "ROAM" else "ROAM"
            P("    frozen %s %s: UHO %.3f, failures %.3f per UE-minute" % (name, frozen, f0["uho_pm"], f0["fail_pm"]))
            if not ok:
                P("      no %s configuration has a failure rate this low" % oname)
                d["frozen_%s_vs_best_other" % name] = None
                continue
            best = min(ok, key=lambda l: t[l]["uho_pm"])
            b = t[best]
            pu, pf = pair_cfg(t, frozen, best, 0), pair_cfg(t, frozen, best, 1)
            d["frozen_%s_vs_best_other" % name] = dict(frozen=frozen, other=best, other_uho_pm=b["uho_pm"],
                                                       other_fail_pm=b["fail_pm"], uho=pu, fail=pf,
                                                       n_other_within=len(ok))
            P("      best %s with failures not above it (%d candidates): %s, UHO %.3f, failures %.3f"
              % (oname, len(ok), best, b["uho_pm"], b["fail_pm"]))
            P("      %s minus that %s: UHO %s (p=%.2g), failures %s (p=%.2g), %d pairs"
              % (name, oname, A.fmt(pu["diff"], pu["diff_ci95"]), pu["wilcoxon_p"],
                 A.fmt(pf["diff"], pf["diff_ci95"]), pf["wilcoxon_p"], pu["n_pairs"]))
        P("    lowest UHO per UE-minute among configurations within a failure budget:")
        budgets = [0.0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.50]
        d["budget_table"] = {}
        for bgt in budgets:
            cell = {}
            for name, fam in (("A3", a3), ("ROAM", ro)):
                ok = [l for l in fam if t[l]["fail_pm"] <= bgt + 1e-12]
                cell[name] = min(ok, key=lambda l: t[l]["uho_pm"]) if ok else None
            d["budget_table"]["%.2f" % bgt] = {k: (dict(label=v, uho_pm=t[v]["uho_pm"], fail_pm=t[v]["fail_pm"])
                                                   if v else None) for k, v in cell.items()}
            P("      failures <= %.2f:  A3 %s   ROAM %s" % (
                bgt, *[("%s (UHO %.3f, fail %.3f)" % (v, t[v]["uho_pm"], t[v]["fail_pm"])) if v else "none"
                       for v in (cell["A3"], cell["ROAM"])]))
        for name, fam, other in (("A3", a3, ro), ("ROAM", ro, a3)):
            fr_ = pareto(t, fam)
            d["pareto_" + name] = fr_
            P("    Pareto front of %s (failures, UHO):" % name)
            for l in fr_:
                dom = [o for o in other if t[o]["fail_pm"] <= t[l]["fail_pm"] and t[o]["uho_pm"] <= t[l]["uho_pm"]
                       and (t[o]["fail_pm"] < t[l]["fail_pm"] or t[o]["uho_pm"] < t[l]["uho_pm"])]
                P("      %-28s fail %.3f  UHO %.3f  HO %.2f   %s" % (
                    l, t[l]["fail_pm"], t[l]["uho_pm"], t[l]["ho_pm"],
                    "dominated by %d configuration(s) of the other family" % len(dom) if dom else "not dominated by the other family"))
    P()


def load_section(js):
    P("3. LOADED NETWORK (own tuning and test per traffic mode)")
    for name, folder in LOAD:
        rows = [r for r in rows_of(folder) if r["phase"] == "test"]
        if not rows:
            P("  %s: no test rows yet" % name)
            continue
        tp = os.path.join(ROOT, folder, "tuned_ns3.json")
        if not os.path.exists(tp):                  # the overload test uses the settings frozen under mixed traffic
            tp = os.path.join(ROOT, folder.replace("_full_", "_mixed_"), "tuned_ns3.json")
        sel = json.load(open(tp, encoding="utf-8")) if os.path.exists(tp) else {}
        d = js.setdefault("load", {}).setdefault(folder, {})
        occ = A.mean_ci([num(r, "occ_slots") for r in rows])
        prb = A.mean_ci([num(r, "occ_prb") for r in rows])
        d["occ_slots"], d["occ_prb"] = occ[0], prb[0]
        P("  %s  (%d rows; frozen A3 %s, ROAM %s; budget %.3f; cell-slots with a scheduled UE %.1f %%, "
          "data-region resources used %.1f %%)" % (name, len(rows), sel.get("A3", {}).get("label", "?"),
                                                   sel.get("ROAM", {}).get("label", "?"),
                                                   sel.get("_budget_fail_pm", float("nan")), 100 * occ[0], 100 * prb[0]))
        for lab in A.RULES:
            rr = [r for r in rows if r["label"] == lab]
            if rr:
                st = {m: A.mean_ci([num(r, m) for r in rr]) for m in ("uho_pm", "fail_pm", "ho_pm", "delivery", "outage_s_pm")}
                d.setdefault("rules", {})[lab] = {m: dict(mean=v[0], ci95=v[1]) for m, v in st.items()}
                P("    %-13s n=%3d UHO %-15s fail %-15s HO %-15s delivery %-15s outage s/UE-min %s"
                  % (lab, len(rr), A.fmt(*st["uho_pm"]), A.fmt(*st["fail_pm"]), A.fmt(*st["ho_pm"]),
                     A.fmt(*st["delivery"], p=4), A.fmt(*st["outage_s_pm"])))
        for a, b in A.PAIRS[:3]:
            for m in ("uho_pm", "fail_pm"):
                c, txt = paired(rows, a, b, m)
                if c:
                    d.setdefault("pooled", {})["%s_vs_%s_%s" % (a, b, m)] = c
                    P("    %-12s vs %-8s %-8s %s" % (a, b, m, txt))
    P()


def sens_section(js):
    P("4. SENSITIVITIES (frozen settings of the core campaign of each scenario; ROAM vs A3_tuned)")
    for scen, folder in SENS:
        rows = rows_of(folder)
        if not rows:
            P("  %s: no rows yet" % scen)
            continue
        d = js.setdefault("sensitivity", {}).setdefault(scen, {})
        P("  %s" % scen)
        for cond in sorted({r.get("cond", "") for r in rows}):
            rr = [r for r in rows if r.get("cond", "") == cond]
            c1, t1 = paired(rr, "ROAM", "A3_tuned", "uho_pm")
            c2, t2 = paired(rr, "ROAM", "A3_tuned", "fail_pm")
            d[cond] = dict(uho_pm=c1, fail_pm=c2)
            P("    %-10s UHO  %s" % (cond, t1))
            P("    %-10s fail %s" % ("", t2))
            if cond.startswith("long"):
                for a in ("ROAM_overlap", "ROAM_history"):
                    for m in ("uho_pm", "fail_pm"):
                        c, txt = paired(rr, "ROAM", a, m)
                        d[cond]["ROAM_vs_%s_%s" % (a, m)] = c
                        P("    %-10s ROAM vs %-12s %-8s %s" % ("", a, m, txt))
    P()


def service_section(js):
    P("5. PER-CLASS SERVICE METRICS (downlink stream of each UE; mean over runs)")
    P("   delivery ratio | mean delay ms | 95th-percentile delay ms | gaps > 100 ms and > 500 ms per UE-minute")
    P("   (with light traffic the packet interval is 100 ms, so only the 500 ms figure is meaningful there)")
    for name, folder in [(s + ", light traffic", f) for s, f in CORE] + LOAD:
        rows = [r for r in rows_of(folder) if r["phase"] == "test" and r.get("deliv_voice", "") != ""]
        if not rows:
            continue
        d = js.setdefault("service", {}).setdefault(folder, {})
        P("  %s" % name)
        for lab in ("A3_tuned", "ROAM"):
            rr = [r for r in rows if r["label"] == lab]
            if not rr:
                continue
            P("    %s (%d runs; outage %.2f s per UE-minute)" % (lab, len(rr), A.mean_ci([num(r, "outage_s_pm") for r in rr])[0]))
            for k in SVC:
                v = [A.mean_ci([num(r, "%s_%s" % (m, k)) for r in rr])[0]
                     for m in ("deliv", "delay_ms", "delay95_ms", "stall100_pm", "stall500_pm")]
                d.setdefault(lab, {})[k] = dict(zip(("delivery", "delay_ms", "delay95_ms", "stall100_pm", "stall500_pm"), v))
                P("      %-7s %.4f | %7.1f | %7.1f | %7.2f  %6.2f" % (k, *v))
    P()


def main():
    js = {}
    P("ROAM against tuned Event A3 in ns-3 (nr): consolidated report")
    P("root: %s" % os.path.relpath(ROOT, HERE).replace(os.sep, "/"))
    P()
    core_section(js)
    frontier_section(js)
    load_section(js)
    sens_section(js)
    service_section(js)
    with open(os.path.join(ROOT, "report_study.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    with open(os.path.join(ROOT, "report_study.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, indent=1)
    devnull = io.StringIO()
    with redirect_stdout(devnull):
        pass
    per_stage_reports([f for _, f in CORE + FRONT + LOAD + SENS])
    print("written: %s" % os.path.join(ROOT, "report_study.txt"))


if __name__ == "__main__":
    main()
