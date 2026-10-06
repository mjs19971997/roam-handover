# -*- coding: utf-8 -*-
"""Statistics of the test experiments: results/exp_<block>.csv -> results/summary.json.

For every (scenario, method, metric): mean over seeds and the half-width of the 95 %
Student-t confidence interval.  For the principal comparisons (Proposed vs. each
baseline, paired by seed because all methods share trajectories, services and
shadowing seeds): mean paired difference with 95 % CI, paired t-test and Wilcoxon
signed-rank p-values, Cohen's d_z, and the relative change.  Blocks whose result
file is missing are skipped.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from scipy import stats
from common import OUT

MET = ["HO_pm", "UHO_pm", "UHR", "HOF_rate", "RLF_pm", "fail_pm", "PP_rate", "outage_pct", "interrupt_pct",
       "thr_mbps", "satisf", "satisf_p5", "sinr_db", "rsrp_dbm", "sig_pm", "dwell_s", "mean_load", "sat_cell_pct",
       "UHR_noguard", "UHR_and", "UHR_dwell", "UHR_legacy", "dec_us", "c_pp", "c_short", "c_gain",
       "unnecessary", "classified", "HO", "failed", "rescue", "censored", "hht_routes",
       "UHR_voice", "UHR_vcall", "UHR_gaming", "UHR_stream", "UHR_web",
       "sat_voice", "sat_vcall", "sat_gaming", "sat_stream", "sat_web"]


def ms(x):
    """Mean, 95 % CI half-width and count of the non-NaN values."""
    x = np.asarray(x, dtype=float); x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return dict(mean=None, ci=None, n=0)
    ci = float(stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    return dict(mean=float(x.mean()), ci=ci, n=n)


def agg(df, keys):
    """Nested dict keys -> metric -> ms() of every metric in MET."""
    out = {}
    for k, sub in df.groupby(keys, sort=False):
        k = k if isinstance(k, tuple) else (k,)
        node = out
        for kk in k[:-1]:
            node = node.setdefault(str(kk), {})
        node[str(k[-1])] = {m: ms(sub[m]) for m in MET if m in sub.columns}
    return out


def paired(df, keys, ref="Proposed", metrics=("UHO_pm", "UHR", "fail_pm", "HO_pm", "outage_pct", "thr_mbps", "satisf", "sinr_db", "sig_pm")):
    """Seed-paired comparison of the method `ref` against every other method per group."""
    out = {}
    for k, sub in (df.groupby(keys, sort=False) if keys else [((), df)]):
        k = k if isinstance(k, tuple) else (k,)
        node = out
        for kk in k:
            node = node.setdefault(str(kk), {})
        p = sub[sub.method == ref].set_index("seed")
        for meth, o in sub.groupby("method", sort=False):
            if meth == ref:
                continue
            o = o.set_index("seed")
            idx = p.index.intersection(o.index)
            node[meth] = {}
            for m in metrics:
                a, b = p.loc[idx, m].values.astype(float), o.loc[idx, m].values.astype(float)
                d = a - b
                n = len(d)
                sd = d.std(ddof=1) if n > 1 else 0.0
                try:
                    pw = float(stats.wilcoxon(a, b).pvalue) if np.any(d != 0) else 1.0
                except Exception:
                    pw = None
                pt = float(stats.ttest_rel(a, b).pvalue) if sd > 0 else None
                node[meth][m] = dict(diff=float(d.mean()), ci=float(stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n)) if n > 1 else 0.0,
                                     p_t=pt, p_w=pw, dz=float(d.mean() / sd) if sd > 0 else None,
                                     rel=float(100 * d.mean() / b.mean()) if b.mean() != 0 else None, n=n)
    return out


def curves(df, bin_s):
    """Time-binned rates (per user-minute) per (profile, method), averaged over seeds."""
    out = {}
    cols = sorted([c for c in df.columns if c.startswith("cv_ho_")], key=lambda c: int(c.split("_")[-1]))
    nb = len(cols)
    for meth, sub in df.groupby(["profile", "method"], sort=False):
        U = sub.users.iloc[0]
        umin = U * bin_s / 60.0
        ho = np.array([[r[f"cv_ho_{i}"] for i in range(nb)] for _, r in sub.iterrows()], dtype=float)
        un = np.array([[r[f"cv_un_{i}"] for i in range(nb)] for _, r in sub.iterrows()], dtype=float)
        fl = np.array([[r[f"cv_fl_{i}"] for i in range(nb)] for _, r in sub.iterrows()], dtype=float)
        n = len(sub)
        se = lambda a: (stats.t.ppf(0.975, n - 1) * a.std(0, ddof=1) / np.sqrt(n)).tolist() if n > 1 else [0] * nb
        out.setdefault(meth[0], {})[meth[1]] = dict(
            t=[(i + 0.5) * bin_s for i in range(nb)],
            uho=(un / umin).mean(0).tolist(), uho_ci=se(un / umin),
            ho=(ho / umin).mean(0).tolist(), fail=(fl / umin).mean(0).tolist(),
            uhr=(un.sum(0) / np.maximum(ho.sum(0), 1)).tolist())
    return out


def main():
    """Aggregate every available block and write summary.json."""
    S = {}
    rd = lambda b: pd.read_csv(os.path.join(OUT, f"exp_{b}.csv")) if os.path.exists(os.path.join(OUT, f"exp_{b}.csv")) else None
    with open(os.path.join(OUT, "tuned.json")) as fh:
        S["tuned"] = json.load(fh)

    d = rd("profiles")
    if d is not None:
        S["profiles"] = agg(d, ["profile", "method"]); S["profiles_tests"] = paired(d, ["profile"])
        S["pooled_tests"] = paired(d.assign(seed=d.profile + "_" + d.seed.astype(str)), [])
    URB = "street"
    d2 = rd("load")
    if d2 is not None and d is not None:
        L = pd.concat([d[(d.profile == URB) & (d.seed <= 6)], d2])
        S["load"] = agg(L, ["users_n", "method"]); S["load_tests"] = paired(L, ["users_n"])
    d3 = rd("density")
    if d3 is not None and d is not None:
        D = pd.concat([d3, d[(d.profile == URB) & (d.seed <= 6)]])
        S["density"] = agg(D, ["env", "method"]); S["density_tests"] = paired(D, ["env"])
    d4 = rd("real")
    if d4 is not None:
        S["real"] = agg(d4, ["env", "method"]); S["real_tests"] = paired(d4, ["env"])
    d5 = rd("ablation")
    if d5 is not None:
        S["ablation"] = agg(d5, ["profile", "method"])
        S["ablation_tests"] = paired(d5, ["profile"], ref="(f) full method", metrics=("UHO_pm", "UHR", "fail_pm", "HO_pm"))
    d6 = rd("hht")
    if d6 is not None:
        S["hht"] = agg(d6, ["profile", "method"]); S["hht_curves"] = curves(d6, 20.0)
        S["hht_tests"] = paired(d6, ["profile"], ref="warm start + online", metrics=("UHO_pm", "UHR", "fail_pm", "HO_pm"))
    d7 = rd("nonstat")
    if d7 is not None:
        S["nonstat"] = agg(d7, ["profile", "method"]); S["nonstat_curves"] = curves(d7, 40.0)
    d8 = rd("sens")
    if d8 is not None:
        S["sens"] = agg(d8, ["variant"])
    d9 = rd("thresh")
    if d9 is not None:
        S["thresh"] = agg(d9, ["variant", "method"])
    d10 = rd("posthoc")
    if d10 is not None:
        S["posthoc"] = agg(d10, ["profile", "method"])
    d11 = rd("tempo")
    if d11 is not None:
        S["tempo"] = agg(d11, ["profile", "method"])
        S["tempo_tests"] = paired(d11, ["profile"], ref="ROAM", metrics=("UHO_pm", "UHR", "fail_pm", "HO_pm", "satisf"))
    t = os.path.join(OUT, "tune_summary.csv")
    if os.path.exists(t):
        g = pd.read_csv(t)
        S["tune"] = {f: sub[["UHO_pm", "fail_pm", "HO_pm", "selected", "feasible", "kw"]].to_dict("records") for f, sub in g.groupby("family")}
    with open(os.path.join(OUT, "summary.json"), "w") as fh:
        json.dump(S, fh, indent=0)
    print("wrote summary.json; blocks:", [k for k in S])


if __name__ == "__main__":
    main()
