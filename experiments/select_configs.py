# -*- coding: utf-8 -*-
"""Pick one configuration per method family from the equal-budget tuning grid.

Rule (identical for every family, fixed before looking at the test seeds):
  among the configurations whose mobility-failure rate on the validation traces
  does not exceed that of the 3GPP-style reference A3 (3 dB, TTT 0.3 s), take the
  one with the fewest unnecessary handovers per user-minute; if no configuration
  meets the failure budget, take the one with the lowest failure rate.
Input:  results/tune.csv (and results/tune_extra.csv if present)
Output: results/tuned.json and results/tune_summary.csv
"""
import ast, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from common import OUT

# method family (the label used in the result files) -> class in roam.policies; "Proposed" is ROAM
CLS = {"A3": "A3", "Proposed": "ROAM", "PBPHS": "PBPHS", "Traj-Pred": "TrajPred",
       "ToS-Skip": "ToSSkip", "MP-Screen": "MPScreen", "ST-CMAB": "STCMAB", "Cluster-RL": "ClusterRL"}


def main():
    """Apply the selection rule and write tuned.json / tune_summary.csv."""
    d = pd.concat([pd.read_csv(os.path.join(OUT, f)) for f in ("tune.csv", "tune_extra.csv") if os.path.exists(os.path.join(OUT, f))])
    g = (d.groupby(["family", "cfg", "kw"])[["UHO_pm", "fail_pm", "HO_pm", "UHR", "outage_pct", "satisf", "thr_mbps"]]
         .mean().reset_index())
    ref = g[(g.family == "A3") & (g.kw == repr(dict(hyst=3, ttt=0.3)))]
    budget = float(ref.fail_pm.iloc[0])
    g["feasible"] = g.fail_pm <= budget + 1e-12
    sel = {}
    g["selected"] = False
    for fam, sub in g.groupby("family"):
        ok = sub[sub.feasible]
        row = ok.sort_values("UHO_pm").iloc[0] if len(ok) else sub.sort_values("fail_pm").iloc[0]
        sel[fam] = dict(cls=CLS[fam], kw=ast.literal_eval(row.kw), met_budget=bool(len(ok)),
                        val_UHO_pm=float(row.UHO_pm), val_fail_pm=float(row.fail_pm))
        g.loc[(g.family == fam) & (g.cfg == row.cfg), "selected"] = True
    sel["_budget_fail_pm"] = budget
    with open(os.path.join(OUT, "tuned.json"), "w") as fh:
        json.dump(sel, fh, indent=1)
    g.to_csv(os.path.join(OUT, "tune_summary.csv"), index=False)
    pd.set_option("display.width", 200)
    print("failure budget (A3 3 dB / TTT 0.3 s):", round(budget, 3))
    print(g[g.selected][["family", "kw", "UHO_pm", "fail_pm", "HO_pm", "feasible"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
