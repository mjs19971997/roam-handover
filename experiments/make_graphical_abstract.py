# -*- coding: utf-8 -*-
"""Graphical abstract (Elsevier: 13 cm x 5 cm, readable at that size), vector PDF + PNG."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from plotstyle import savefig, style, INK, MUTE, BLUE, ORANGE, AQUA, YELLOW, RED

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = json.load(open(os.path.join(os.environ.get("ROAM_RESULTS", os.path.join(ROOT, "results")), "summary.json")))
PROF = ["pedestrian", "vehicular", "street", "highway", "train"]
PROFL = ["Pedestrian", "Open area", "Street grid", "Highway", "Train"]


def box(ax, x, y, w, h, text, fc, ec, fs=7.4, bold=False):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec=ec, lw=0.8, zorder=3))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, fontweight="bold" if bold else "normal", zorder=4, linespacing=1.25)


def main():
    fig = plt.figure(figsize=(13 / 2.54, 5 / 2.54))
    ax = fig.add_axes([0.005, 0.02, 0.56, 0.96]); ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 6)
    ax.text(5, 5.72, "ROAM: an A3 trigger with a margin per user and per neighbour", ha="center", va="center", fontsize=7.8, fontweight="bold", color=INK)
    box(ax, 1.75, 4.25, 3.1, 1.25, "Outcome memory\nuseful / unnecessary /\nearly / late, per place", "#fdeceb", RED, fs=6.8)
    box(ax, 5.0, 4.25, 3.1, 1.25, "Path overlap\nshare of the next\nseconds in each cell", "#e7f6f0", AQUA, fs=6.8)
    box(ax, 8.25, 4.25, 3.1, 1.25, "Service class\ninterruption\nsensitivity (5QI)", "#fdf3dc", YELLOW, fs=6.8)
    box(ax, 5.0, 2.25, 9.6, 0.95, "$m_{ij} = h_0 + \\eta_H H - \\eta_L L + \\eta_S w_s - \\eta_A\\gamma\\,\\Delta f$   [dB]", "#e6f0fb", BLUE, fs=8.2, bold=True)
    box(ax, 5.0, 0.7, 9.6, 0.9, "Hand over to $j$ if   RSRP$_j$ $-$ RSRP$_c$ $> m_{ij}$   for the time-to-trigger", "#f5f5f5", "#7a7a7a", fs=7.2)
    for x in (1.75, 5.0, 8.25):
        ax.add_patch(FancyArrowPatch((x, 3.6), (x if x == 5.0 else (2.6 if x < 5 else 7.4), 2.75), arrowstyle="-|>", mutation_scale=6, lw=0.8, color="#51606e", shrinkA=0, shrinkB=0))
    ax.add_patch(FancyArrowPatch((5.0, 1.76), (5.0, 1.17), arrowstyle="-|>", mutation_scale=6, lw=0.8, color="#51606e", shrinkA=0, shrinkB=0))

    bx = fig.add_axes([0.655, 0.23, 0.335, 0.60])
    x = np.arange(len(PROF)); w = 0.38
    a3 = [S["profiles"][p]["A3"]["UHO_pm"]["mean"] for p in PROF]; ro = [S["profiles"][p]["Proposed"]["UHO_pm"]["mean"] for p in PROF]
    bx.bar(x - w / 2, a3, w * 0.92, color=ORANGE, label="A3 (tuned)", zorder=3, linewidth=0)
    bx.bar(x + w / 2, ro, w * 0.92, color=BLUE, label="ROAM", zorder=3, linewidth=0)
    for i in range(len(PROF)):
        bx.text(x[i], a3[i] * 1.12, f"$-${100 * (1 - ro[i] / a3[i]):.0f}%", ha="center", va="bottom", fontsize=6.2, color=INK)
    bx.set_yscale("log"); bx.set_ylim(0.2, 22); bx.set_xticks(x); bx.set_xticklabels(PROFL, rotation=28, ha="right", rotation_mode="anchor", fontsize=6.4)
    bx.tick_params(axis="x", length=0); bx.tick_params(axis="y", labelsize=6.4)
    bx.set_ylabel("Unnecessary handovers\nper user-minute", fontsize=6.8)
    bx.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=6.6, columnspacing=1.0, handlelength=1.0, handletextpad=0.4)
    style(bx)
    savefig(fig, "graphical_abstract")


if __name__ == "__main__":
    main()
