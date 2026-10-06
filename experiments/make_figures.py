# -*- coding: utf-8 -*-
"""Result figures of the paper, built from results/summary.json (vector PDF + SVG + PNG)."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from plotstyle import (savefig, style, panel, W1, W15, W2, ORDER, LAB, COL, MK, INK, MUTE,
                       BLUE, ORANGE, AQUA, YELLOW, VIOLET, RED)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = json.load(open(os.path.join(os.environ.get("ROAM_RESULTS", os.path.join(ROOT, "results")), "summary.json")))
PROF = ["pedestrian", "vehicular", "street", "highway", "train"]
PROFL = ["Ped.", "Open", "Street", "Hwy.", "Train"]
g = lambda node, m: (node[m]["mean"], node[m]["ci"])
EK = dict(lw=0.5, capsize=1.2, capthick=0.5, ecolor="#222222")


def fig_pareto():
    """All tuned configurations: ROAM and A3 in colour, the other families in grey with distinct markers."""
    fig, ax = plt.subplots(figsize=(W1, 2.95))
    budget = S["tuned"]["_budget_fail_pm"]; FLOOR = 0.03
    for f in ORDER:
        rows = S["tune"][f]
        x = np.array([r["UHO_pm"] for r in rows]); y = np.maximum(np.array([r["fail_pm"] for r in rows]), FLOOR)
        main = f in ("Proposed", "A3")
        ax.scatter(x, y, s=11 if main else 8, marker=MK[f], color=COL[f] if main else "#9a9a9a", alpha=0.95 if main else 0.8,
                   edgecolor="white", linewidth=0.25, zorder=4 if main else 3, label=LAB[f])
        if main:                                          # lower-left frontier
            o = np.argsort(x); fx, fy, best = [], [], 1e9
            for i in o:
                if y[i] < best - 1e-12:
                    fx.append(x[i]); fy.append(y[i]); best = y[i]
            ax.plot(fx, fy, color=COL[f], lw=1.0, zorder=2)
        sel = [r for r in rows if r["selected"]][0]
        ax.scatter([sel["UHO_pm"]], [max(sel["fail_pm"], FLOOR)], s=42, marker="o", facecolor="none",
                   edgecolor=COL[f] if main else "#555555", linewidth=0.9, zorder=5)
    ax.axhline(budget, color=INK, ls=(0, (4, 2)), lw=0.7)
    ax.text(0.985, budget * 1.05, "failure budget", fontsize=7, ha="right", va="bottom", transform=ax.get_yaxis_transform())
    ax.text(0.985, FLOOR * 1.12, "PBPHS: below 0.03 (drawn at the floor)", fontsize=6.5, color=MUTE, ha="right", va="bottom",
            transform=ax.get_yaxis_transform())
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(FLOOR * 0.85, 2.6)
    ax.set_xlabel("Unnecessary handovers per user-minute"); ax.set_ylabel("Mobility failures per user-minute")
    h, l = ax.get_legend_handles_labels()
    h.append(Line2D([], [], marker="o", ls="", mfc="none", mec="#555555", ms=5.5, mew=0.9)); l.append("selected")
    ax.legend(h, l, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.01), columnspacing=1.0, handletextpad=0.3)
    style(ax, grid="both"); ax.grid(which="minor", lw=0.3, color="#ececec")
    savefig(fig, "fig_pareto")


def bars(ax, groups, glabels, metric, ylabel, node_of, methods=ORDER, log=False):
    w = 0.84 / len(methods); x = np.arange(len(groups))
    for k, m in enumerate(methods):
        v = [g(node_of(gr, m), metric) for gr in groups]
        ax.bar(x + (k - (len(methods) - 1) / 2) * w, [a for a, _ in v], w * 0.86, yerr=[b for _, b in v], color=COL[m],
               label=LAB[m], error_kw=EK, zorder=3, linewidth=0)
    ax.set_xticks(x); ax.set_xticklabels(glabels); ax.set_ylabel(ylabel); ax.tick_params(axis="x", length=0)
    if log:
        ax.set_yscale("log")
    style(ax)


def fig_profiles():
    fig, axes = plt.subplots(1, 3, figsize=(W2, 2.35), gridspec_kw=dict(wspace=0.3))
    node = lambda p, m: S["profiles"][p][m]
    bars(axes[0], PROF, PROFL, "UHO_pm", "Unnecessary HOs per user-minute", node, log=True)
    bars(axes[1], PROF, PROFL, "fail_pm", "Mobility failures per user-minute", node)
    bars(axes[2], PROF, PROFL, "satisf", "Delivered / demanded rate", node)
    for ax, t in zip(axes, "abc"):
        panel(ax, t); ax.tick_params(axis="x", labelsize=7)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=8, loc="lower center", bbox_to_anchor=(0.5, 0.97), columnspacing=1.1, handlelength=1.1, handletextpad=0.4)
    savefig(fig, "fig_profiles")


def fig_load():
    users = sorted(S["load"].keys(), key=int)
    meth = ["Proposed", "A3", "MP-Screen", "ToS-Skip", "Traj-Pred"]
    fig, axes = plt.subplots(1, 4, figsize=(W2, 1.95), gridspec_kw=dict(wspace=0.42))
    for ax, (metric, yl) in zip(axes, [("UHO_pm", "Unnecessary HOs per user-min"), ("fail_pm", "Failures per user-min"),
                                        ("satisf", "Delivered / demanded rate"), ("mean_load", "Mean cell load")]):
        for m in meth:
            v = [g(S["load"][u][m], metric) for u in users]
            ax.errorbar([int(u) for u in users], [a for a, _ in v], yerr=[b for _, b in v], color=COL[m], marker=MK[m],
                        capsize=1.5, capthick=0.5, elinewidth=0.5, label=LAB[m], mec="white", mew=0.3, zorder=3)
        ax.set_xlabel("Users"); ax.set_ylabel(yl); ax.set_xticks([int(u) for u in users]); style(ax)
    for ax, t in zip(axes, "abcd"):
        panel(ax, t)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=5, loc="lower center", bbox_to_anchor=(0.5, 0.97), columnspacing=1.4)
    savefig(fig, "fig_load")


def fig_service():
    sv = ["voice", "vcall", "gaming", "stream", "web"]; svl = ["Voice", "Video call", "Gaming", "Streaming", "Web"]
    meth = ["Proposed", "A3", "MP-Screen", "ToS-Skip", "Traj-Pred"]
    fig, ax = plt.subplots(figsize=(W1, 2.3))
    w = 0.84 / len(meth); x = np.arange(len(sv)); node = S["profiles"]["street"]
    for k, m in enumerate(meth):
        v = [g(node[m], f"UHR_{s}") for s in sv]
        ax.bar(x + (k - (len(meth) - 1) / 2) * w, [a for a, _ in v], w * 0.86, yerr=[b for _, b in v], color=COL[m], label=LAB[m],
               error_kw=EK, zorder=3, linewidth=0)
    ax.set_xticks(x); ax.set_xticklabels(svl); ax.tick_params(axis="x", length=0); ax.set_ylabel("Unnecessary-handover ratio")
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), columnspacing=1.0, handlelength=1.1, handletextpad=0.4); style(ax)
    savefig(fig, "fig_service")


def fig_causes():
    fig, axes = plt.subplots(1, 2, figsize=(W2, 2.3), gridspec_kw=dict(wspace=0.18))
    seg = [("c_pp", "Ping-pong", VIOLET), ("c_short", "Short stay (not ping-pong)", YELLOW), ("c_gain", "Full stay, gain below threshold", AQUA)]
    umin = 300 * 240 / 60.0
    for ax, pr, t, ttl in zip(axes, ["street", "highway"], "ab", ["Street grid", "Highway"]):
        node = S["profiles"][pr]; x = np.arange(len(ORDER)); bottom = np.zeros(len(ORDER))
        for key, lab, col in seg:
            v = np.array([node[m][key]["mean"] / umin for m in ORDER])
            ax.bar(x, v, 0.6, bottom=bottom, color=col, label=lab, zorder=3, edgecolor="white", linewidth=0.5)
            bottom += v
        for i, tot in enumerate(bottom):
            ax.text(i, tot, f"{tot:.2f}", ha="center", va="bottom", fontsize=6.6, color=INK)
        ax.set_xticks(x); ax.set_xticklabels([LAB[m] for m in ORDER], rotation=30, ha="right", rotation_mode="anchor")
        ax.tick_params(axis="x", length=0); ax.set_ylim(0, bottom.max() * 1.1); panel(ax, t, ttl); style(ax)
    axes[0].set_ylabel("Unnecessary HOs per user-minute")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.97), columnspacing=1.6)
    savefig(fig, "fig_causes")


def fig_curves():
    fig, axes = plt.subplots(1, 3, figsize=(W2, 2.3), gridspec_kw=dict(wspace=0.3))
    cl = {"warm start + online": (BLUE, "-", "o", "ROAM, warm start (default)"), "cold start, online": (AQUA, "--", "^", "ROAM, cold start"),
          "table fixed at its prior": (YELLOW, "-.", "D", "ROAM, table fixed at its prior"), "A3": (ORANGE, "-", "s", "A3 (tuned)")}
    kw = dict(capsize=1.3, capthick=0.5, elinewidth=0.45, mec="white", mew=0.3, ms=3.0, lw=1.0)
    for ax, pr, t, ttl in zip(axes[:2], ["street", "highway"], "ab", ["Street grid", "Highway"]):
        for k, (col, ls, mk, lab) in cl.items():
            cv = S["hht_curves"][pr][k]
            ax.errorbar(cv["t"], cv["uho"], yerr=cv["uho_ci"], color=col, ls=ls, marker=mk, label=lab, **kw)
        ax.set_xlabel("Time since start of test run [s]"); panel(ax, t, ttl); style(ax)
    axes[0].set_ylabel("Unnecessary HOs per user-minute")
    ax = axes[2]
    cn = {"tau_f = 600 s": (BLUE, "-", "o", r"ROAM, $\tau_f$ = 600 s (default)"), "no forgetting": (RED, "--", "v", "ROAM, no forgetting"),
          "tau_f = 150 s": (AQUA, ":", "^", r"ROAM, $\tau_f$ = 150 s"),
          "table fixed at its prior": (YELLOW, "-.", "D", "ROAM, table fixed at its prior"), "A3": (ORANGE, "-", "s", "A3 (tuned)")}
    for k, (col, ls, mk, lab) in cn.items():
        cv = S["nonstat_curves"]["highway"][k]
        ax.errorbar(cv["t"], cv["uho"], yerr=cv["uho_ci"], color=col, ls=ls, marker=mk, label=lab, **kw)
    ax.axvline(240, color=INK, lw=0.7, ls=(0, (4, 2)))
    ax.set_xlabel("Time since start of test run [s]"); panel(ax, "c", "Highway, environment redrawn at 240 s"); style(ax)
    h1, l1 = axes[1].get_legend_handles_labels(); h2, l2 = axes[2].get_legend_handles_labels()
    extra = [(h, l) for h, l in zip(h2, l2) if l not in l1 and "default" not in l]
    fig.legend(h1 + [h for h, _ in extra], l1 + [l for _, l in extra], ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.97), columnspacing=1.6)
    savefig(fig, "fig_curves")


if __name__ == "__main__":
    for w in (sys.argv[1:] or ["pareto", "profiles", "load", "service", "causes", "curves"]):
        globals()["fig_" + w]()
