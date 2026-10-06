# -*- coding: utf-8 -*-
"""Concept figures of the paper (vector): framework, history table, path overlap, outcome timeline."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, FancyArrowPatch, FancyBboxPatch, Polygon
from scipy.spatial import Voronoi
from plotstyle import savefig, W1, W15, W2, INK, MUTE, BLUE, ORANGE, AQUA, YELLOW, VIOLET, RED, GREEN

LW = 0.8


def box(ax, x, y, w, h, text, fc="#f3f6fa", ec="#51606e", fs=7.6, bold=False):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.10",
                                fc=fc, ec=ec, lw=LW, zorder=3))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, fontweight="bold" if bold else "normal",
            zorder=4, linespacing=1.25)


def arrow(ax, p, q, color="#51606e", ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=7, lw=LW, color=color, ls=ls, zorder=2,
                                 shrinkA=0, shrinkB=0))


def fig_framework():
    fig, ax = plt.subplots(figsize=(W15, 3.75)); ax.axis("off"); ax.set_xlim(0, 12); ax.set_ylim(-0.45, 8.2)
    box(ax, 2.0, 7.6, 3.5, 0.9, "L3-filtered RSRP\nserving cell and neighbours", fs=7.2)
    box(ax, 6.05, 7.6, 3.9, 0.9, "Position, speed, heading\n(terminal or network estimate)", fs=7.2)
    box(ax, 10.2, 7.6, 3.0, 0.9, "Service class (5QI)", fs=7.2)
    box(ax, 6.0, 5.95, 3.4, 0.9, "Base layer: K-means, PCA,\ndecision tree  $\\rightarrow$  $a_{init}$", fc="#f1eefb", ec=VIOLET)
    box(ax, 2.2, 4.25, 2.7, 1.0, "History table\n$H$,  $L$", fc="#fdeceb", ec=RED, bold=True, fs=8)
    box(ax, 6.0, 4.25, 3.4, 1.0, "Path overlap\n$\\gamma\\,\\Delta f(j)$", fc="#e7f6f0", ec=AQUA, bold=True, fs=8)
    box(ax, 10.1, 4.25, 3.2, 1.0, "Interruption\nsensitivity  $w_s$", fc="#fdf3dc", ec=YELLOW, bold=True, fs=8)
    box(ax, 6.0, 2.5, 9.9, 0.95,
        "Per-neighbour margin    $m_{ij} = h_0 + \\eta_H H - \\eta_L L + \\eta_S w_s - \\eta_A\\gamma\\,\\Delta f - \\varepsilon_j$",
        fc="#e6f0fb", ec=BLUE, bold=True, fs=8.2)
    box(ax, 3.4, 0.9, 4.7, 0.9, "A3-type trigger: gap $> m_{ij}$ for TTT,\nhold timer  $\\rightarrow$  stay / hand over")
    box(ax, 9.45, 0.9, 4.9, 0.9, "Observed outcome (at most $T_{min}^s$ later):\nuseful / unnecessary / early / late", fc="#f5f5f5", ec="#7a7a7a")
    arrow(ax, (6.0, 7.15), (6.0, 6.42)); arrow(ax, (6.0, 5.5), (6.0, 4.77))
    arrow(ax, (10.2, 7.15), (10.2, 4.77)); arrow(ax, (2.2, 3.75), (2.7, 3.0)); arrow(ax, (6.0, 3.75), (6.0, 3.0))
    arrow(ax, (10.1, 3.75), (9.4, 3.0)); arrow(ax, (4.6, 2.02), (3.8, 1.37)); arrow(ax, (5.77, 0.9), (6.98, 0.9))
    ax.plot([0.5, 0.5], [7.15, 0.9], color="#51606e", lw=LW, zorder=2); arrow(ax, (0.5, 0.9), (1.03, 0.9))
    ax.plot([9.45, 9.45, 0.15, 0.15], [0.45, 0.12, 0.12, 4.25], color=GREEN, lw=LW, ls=(0, (4, 2)), zorder=2)
    arrow(ax, (0.15, 4.25), (0.83, 4.25), color=GREEN)
    ax.text(4.9, -0.2, "outcome feedback (causal, delayed)", color=GREEN, fontsize=7.4, ha="center")
    savefig(fig, "fig_framework")


def fig_hht():
    fig, ax = plt.subplots(figsize=(W15, 2.25)); ax.axis("off"); ax.set_xlim(0.2, 13.0); ax.set_ylim(1.55, 8.1)
    routes = [r"$c\rightarrow 2$", r"$c\rightarrow 5$", r"$c\rightarrow 7$", r"$c\rightarrow 9$", r"$c\rightarrow 11$"]
    Nu = [34.1, 9.3, 17.0, 5.2, 21.6]; Nn = [3.8, 16.4, 5.1, 7.9, 4.0]; Ne = [0.9, 4.7, 1.2, 3.6, 0.8]; Nl = [0.4, 0.6, 5.3, 0.3, 0.5]
    al, be = 0.6, 1.0
    tot = [a + b + c + d + 4 * be for a, b, c, d in zip(Nu, Nn, Ne, Nl)]
    H = [(al * (n + be) + (1 - al) * (e + be)) / t for n, e, t in zip(Nn, Ne, tot)]
    L = [(l + be) / t for l, t in zip(Nl, tot)]
    hd = ["Route", r"$N_{use}$", r"$N_{un}$", r"$N_{early}$", r"$N_{late}$", r"Risk $H$", r"Lateness $L$"]
    xc = [1.2, 3.0, 4.6, 6.2, 7.8, 9.7, 11.9]; wc = [1.7, 1.4, 1.4, 1.4, 1.4, 1.9, 2.0]
    y0, rh = 7.5, 1.05
    ax.plot([0.3, 12.95], [y0 + 0.5, y0 + 0.5], color=INK, lw=0.9); ax.plot([0.3, 12.95], [y0 - 0.5, y0 - 0.5], color=INK, lw=0.5)
    for x, h in zip(xc, hd):
        ax.text(x, y0, h, ha="center", va="center", fontsize=8, fontweight="bold", color=INK)
    red = plt.cm.Reds; blu = plt.cm.Blues
    for i, rt in enumerate(routes):
        yy = y0 - (i + 1) * rh
        vals = [rt, f"{Nu[i]:.1f}", f"{Nn[i]:.1f}", f"{Ne[i]:.1f}", f"{Nl[i]:.1f}", f"{H[i]:.2f}", f"{L[i]:.2f}"]
        for j, (x, w, v) in enumerate(zip(xc, wc, vals)):
            if j == 5:
                f = (H[i] - min(H)) / (max(H) - min(H)); fc = red(0.08 + 0.5 * f)
                ax.add_patch(FancyBboxPatch((x - w / 2 + 0.12, yy - 0.38), w - 0.24, 0.76, boxstyle="round,pad=0,rounding_size=0.08", fc=fc, ec="none"))
            elif j == 6:
                f = (L[i] - min(L)) / (max(L) - min(L)); fc = blu(0.08 + 0.5 * f)
                ax.add_patch(FancyBboxPatch((x - w / 2 + 0.12, yy - 0.38), w - 0.24, 0.76, boxstyle="round,pad=0,rounding_size=0.08", fc=fc, ec="none"))
            ax.text(x, yy, v, ha="center", va="center", fontsize=8, color=INK)
    yb = y0 - 5 * rh - 0.52
    ax.plot([0.3, 12.95], [yb, yb], color=INK, lw=0.9)
    savefig(fig, "fig_hht")


def fig_overlap():
    pts = np.array([[3.2, 4.2], [7.6, 6.3], [7.9, 1.9], [3.0, 8.3], [11.6, 4.4], [0.2, 1.0], [11.5, 8.8], [5.6, -1.6],
                    [-1.5, 5.5], [12.5, 0.2], [7.0, 10.8], [-1.0, 10.0], [14.5, 6.0]])
    vor = Voronoi(pts)
    fig, ax = plt.subplots(figsize=(W1, W1 * 0.80)); ax.set_aspect("equal"); ax.axis("off")
    ax.set_xlim(0.2, 11.2); ax.set_ylim(0.2, 9.1)
    cols = {0: ("#dbe9f8", BLUE), 1: ("#dcf3ea", AQUA), 2: ("#fbe1e0", RED)}
    for i in range(len(pts)):
        reg = vor.regions[vor.point_region[i]]
        if -1 in reg or not reg:
            continue
        fc, ec = cols.get(i, ("#f4f4f4", "#b5b5b5"))
        ax.add_patch(Polygon(vor.vertices[reg], fc=fc, ec=ec, lw=0.8, zorder=1))
    for i in range(5):
        ax.plot(*pts[i], marker="^", ms=5.5, color=cols.get(i, ("", "#9a9a9a"))[1], zorder=5, mec="white", mew=0.4)
    ux, uy = 4.5, 4.7
    th = np.degrees(np.arctan2(6.3 - uy, 7.6 - ux)) - 6
    ax.add_patch(Wedge((ux, uy), 4.2, th - 34, th + 34, fc=YELLOW, ec="#a87200", alpha=0.32, lw=0.7, hatch="////", zorder=2))
    ax.plot([ux], [uy], "o", ms=4.5, color=INK, zorder=6)
    ax.add_patch(FancyArrowPatch((ux, uy), (ux + 1.9 * np.cos(np.radians(th)), uy + 1.9 * np.sin(np.radians(th))),
                                 arrowstyle="-|>", mutation_scale=9, lw=1.2, color=INK, zorder=7, shrinkA=0, shrinkB=0))

    def lab(x, y, s, c):
        ax.text(x, y, s, ha="center", va="center", fontsize=7.4, color=INK, linespacing=1.25,
                bbox=dict(fc="white", ec=c, boxstyle="round,pad=0.25", lw=0.8), zorder=8)
    lab(2.45, 3.0, "serving cell $c$\n$f_c = 0.27$", BLUE)
    lab(9.05, 7.75, "neighbour $j_1$\n$f_{j_1} = 0.62$", AQUA)
    lab(8.95, 1.05, "neighbour $j_2$\n$f_{j_2} = 0.08$", RED)
    ax.text(3.9, 7.15, "predicted-motion sector $R_p(t)$\nradius $v\\,T_p$, half-angle $\\varphi$", ha="center", fontsize=7.2, color="#7a5300", linespacing=1.25)
    ax.text(4.5, 4.12, "user", fontsize=7.4, ha="center", color=INK)
    savefig(fig, "fig_overlap")


def fig_timeline():
    fig, ax = plt.subplots(figsize=(W15, 2.75))
    t = np.linspace(-3, 9, 600)
    src = 6.5 - 1.25 * t + 1.3 * np.sin(0.9 * t + 0.4)
    tgt = 2.0 + 0.55 * t + 1.6 * np.sin(1.3 * t + 1.0) * np.exp(-0.08 * (t + 3))
    ax.axvspan(0, 6, color=YELLOW, alpha=0.12, lw=0)
    ax.plot(t[t <= 0], src[t <= 0], color=BLUE, lw=1.5, label="source cell $c$ (serving before $t_0$)")
    ax.plot(t[t >= 0], src[t >= 0], color=BLUE, lw=1.2, ls=(0, (4, 2)), label="source cell $c$ after $t_0$: counterfactual, measured as a neighbour")
    ax.plot(t[t <= 0], tgt[t <= 0], color=ORANGE, lw=1.2, ls=(0, (1, 1.5)))
    ax.plot(t[t >= 0], tgt[t >= 0], color=ORANGE, lw=1.5, label="target cell $j$ (serving after $t_0$)")
    ax.axhline(-8, color=INK, lw=0.7, ls=(0, (5, 2, 1, 2))); ax.text(-2.9, -7.3, "$Q_{out}$", color=INK, fontsize=8)
    ax.axvline(0, color=INK, lw=0.8)
    ax.annotate("", xy=(6, 11.6), xytext=(0, 11.6), arrowprops=dict(arrowstyle="<->", color="#7a5300", lw=0.8, shrinkA=0, shrinkB=0))
    ax.text(3, 12.2, "observation window, at most $T_{min}^s$", ha="center", va="bottom", color="#7a5300", fontsize=7.6)
    ax.text(-0.15, 16.6, "decision at $t_0$: only past\nmeasurements, $H$, $L$, $\\Delta f$", ha="right", va="top", fontsize=7.4, color=INK, linespacing=1.25)
    ax.text(6.15, 16.6, "outcome known at $t_0+T_{min}^s$\n(or when the user leaves $j$):\ndwell time, $\\Delta Q$, failure", ha="left", va="top", fontsize=7.4, color=INK, linespacing=1.25)
    m = (t >= 0) & (t <= 6)
    ax.fill_between(t[m], src[m], tgt[m], where=tgt[m] > src[m], color=ORANGE, alpha=0.18, lw=0)
    ax.text(7.55, 0.9, "$\\Delta Q$: mean gap\nover the window", fontsize=7.4, color=INK, ha="center", linespacing=1.25)
    ax.set_xlim(-3, 9); ax.set_ylim(-17.5, 17.5)
    ax.set_xlabel("Time relative to the handover [s]"); ax.set_ylabel("SINR [dB]")
    ax.legend(loc="lower left", fontsize=7, handlelength=2.6, borderaxespad=0.4, frameon=True, facecolor="white", edgecolor="none", framealpha=0.92)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    savefig(fig, "fig_timeline")


if __name__ == "__main__":
    fig_framework(); fig_hht(); fig_overlap(); fig_timeline()
