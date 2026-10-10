# -*- coding: utf-8 -*-
"""Figures of the ns-3 validation, built from results/report_study.json and the tuned_ns3.json of the core stages.

    fig_ns3_fronts  supplemental file: all 24 A3 and 24 ROAM configurations on the test cells with both fronts,
                    urban grid and open area
    fig_ns3_front   the urban panel alone (one column)

    python ns3/make_ns3_figures.py [front] [fronts]        -> figures/fig_ns3_*.pdf (also .svg and .png)

Fig. 5 of the paper (the map of one pair of runs and the urban configurations) is drawn by
experiments/make_paper_figures.py ns3.
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experiments"))
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
from plotstyle import savefig, style, panel, W1, W2, COL, MK, INK, MUTE

HERE = os.path.dirname(os.path.abspath(__file__))
NS = os.path.join(HERE, "results")
J = json.load(open(os.path.join(NS, "report_study.json"), encoding="utf-8"))
FAM = [("ROAM", "Proposed", "ROAM"), ("A3", "A3", "A3")]


def tuned(scen):
    folder = {"urban": "campaign_urban", "base": "campaign"}[scen]
    t = json.load(open(os.path.join(NS, folder, "tuned_ns3.json"), encoding="utf-8"))
    return {"ROAM": t["ROAM"]["label"], "A3": t["A3"]["label"]}


def draw(ax, scen, floor, legend=True):
    """x: unnecessary handovers per UE-minute, y: failures per UE-minute (values below `floor` are drawn at the floor).
    The axes are those of the tuning figure of the system-level simulator (Fig. 3(a) of the paper, fig_pareto)."""
    fr = J["frontier"][scen]
    cfg, sel = fr["configs"], tuned(scen)
    for fam, key, lab in FAM:
        labs = [l for l in cfg if l.startswith(fam + "_")]
        y = np.maximum(np.array([cfg[l]["fail_pm"] for l in labs]), floor)
        x = np.array([cfg[l]["uho_pm"] for l in labs])
        ax.scatter(x, y, s=11, marker=MK[key], color=COL[key], alpha=0.95, edgecolor="white", linewidth=0.25, zorder=4, label=lab)
        front = fr["pareto_" + fam]
        ax.plot([cfg[l]["uho_pm"] for l in front], [max(cfg[l]["fail_pm"], floor) for l in front], color=COL[key], lw=1.0, zorder=2)
        s = cfg[sel[fam]]
        ax.scatter([s["uho_pm"]], [max(s["fail_pm"], floor)], s=42, marker="o", facecolor="none", edgecolor=COL[key], linewidth=0.9, zorder=5)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_ylabel("Failures per UE-minute"); ax.set_xlabel("Unnecessary HOs per UE-minute")
    style(ax, grid="both"); ax.grid(which="minor", lw=0.3, color="#ececec")
    plain = FuncFormatter(lambda v, _: ("%g" % v))
    lo, hi = ax.get_xlim()
    ax.xaxis.set_major_locator(FixedLocator([t for t in (0.2, 0.5, 1, 2, 5, 10) if lo <= t <= hi]))
    ax.xaxis.set_minor_formatter(NullFormatter()); ax.yaxis.set_major_formatter(plain); ax.xaxis.set_major_formatter(plain)
    if legend:
        h, l = ax.get_legend_handles_labels()
        h.append(Line2D([], [], marker="o", ls="", mfc="none", mec="#555555", ms=5.5, mew=0.9)); l.append("selected setting")
        ax.legend(h, l, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.01), columnspacing=1.0, handletextpad=0.3)


def fig_front():
    fig, ax = plt.subplots(figsize=(W1, 1.65))
    draw(ax, "urban", 0.004)
    savefig(fig, "fig_ns3_front")


def fig_fronts():
    fig, axes = plt.subplots(1, 2, figsize=(W2, 2.5), gridspec_kw=dict(wspace=0.22))
    draw(axes[0], "urban", 0.004, legend=False); panel(axes[0], "a", "Urban grid")
    floor = 0.0006
    draw(axes[1], "base", floor, legend=False); panel(axes[1], "b", "Open area")
    axes[1].text(0.02, floor * 1.12, "no failure\n(drawn here)", fontsize=7, color=MUTE, ha="left", va="bottom", transform=axes[1].get_yaxis_transform(), linespacing=1.1)
    h, l = axes[0].get_legend_handles_labels()
    h.append(Line2D([], [], marker="o", ls="", mfc="none", mec="#555555", ms=5.5, mew=0.9)); l.append("selected setting")
    fig.legend(h, l, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.97), columnspacing=1.2, handletextpad=0.3)
    savefig(fig, "fig_ns3_fronts")


if __name__ == "__main__":
    for w in (sys.argv[1:] or ["front", "fronts"]):
        globals()["fig_" + w]()
