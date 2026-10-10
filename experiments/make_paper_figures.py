# -*- coding: utf-8 -*-
"""Figures of the paper itself (IEEE Transactions on Mobile Computing layout), drawn at their final size.

    fig_i_scheme    Fig. 1: (a) the four outcomes of a handover (schematic), (b) overview of the proposed scheme
    fig_i_overlap   Fig. 2: the path-overlap idea
    fig_i_results   Fig. 3: (a) all tuned configurations (validation traces), (b), (c) the eight methods on the
                    held-out seeds in the five mobility profiles, mean and 95 % confidence interval
    fig_i_more      Fig. 4: unnecessary handovers by cause, effect of load, the outcome memory over time and against a constant offset
    fig_i_ns3       Fig. 5: one real pair of ns-3 runs on the urban grid (every logged handover of the measured
                    part, marked by outcome, for tuned A3 and for ROAM) and all 48 configurations on the test cells

IEEEtran, journal mode: the column is 252 pt wide and the text 516 pt.  All type inside the figures is 7 to 8 pt,
the size of the captions.  Sources: results/summary.json (system-level simulator), ns3/results (ns-3: report_study.json,
tuned_ns3.json, results.csv) and, for the map of Fig. 5, the raw per-attempt and per-failure files of the two runs in
ns3/fig5_runs (<job>_att.csv, <job>_rlf.csv).  The run shown in the map is chosen by a fixed rule (see pick_run); the
job identifiers and the counts quoted in the caption are written to figures/fig_i_ns3.json.

    python experiments/make_paper_figures.py [scheme] [overlap] [results] [more] [ns3]
"""
import csv, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Wedge, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
from scipy.spatial import Voronoi
from plotstyle import (savefig, style, panel, FIG8, ORDER, LAB, COL, MK, INK, MUTE,
                       BLUE, ORANGE, AQUA, YELLOW, VIOLET, RED, GREEN)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WC = 252 / 72.27                      # column width of IEEEtran [in]
WT = 516 / 72.27                      # text width [in]
MM = 1 / 25.4
LW = 0.8
plain = FuncFormatter(lambda v, _: ("%g" % v))


# ------------------------------------------------------------------ Fig. 1: scheme and path overlap
def _box(ax, x0, y0, x1, y1, text, fc="#f3f6fa", ec="#51606e", fs=7.6, lw=LW, ls="-", color=INK, **kw):
    ax.add_patch(FancyBboxPatch((x0 + 0.6, y0 + 0.6), x1 - x0 - 1.2, y1 - y0 - 1.2, boxstyle="round,pad=0.6,rounding_size=1.1",
                                fc=fc, ec=ec, lw=lw, ls=ls, zorder=3))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", fontsize=fs, color=color, zorder=4, linespacing=1.22, **kw)


def _arrow(ax, pts, color="#3f4b57", ls="-", lw=LW):
    """Polyline with an arrow head on its last segment."""
    if len(pts) > 2:
        ax.plot([p[0] for p in pts[:-1]], [p[1] for p in pts[:-1]], color=color, lw=lw, ls=ls, zorder=2, solid_capstyle="butt")
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=6.5, lw=lw, color=color, ls=ls, zorder=2,
                                 shrinkA=0, shrinkB=0))


SW, SH = 123.5, 47.8                                       # size of the block diagram [mm]


def _scheme(ax):
    """Block diagram in millimetres: the ROAM layer on top of the unchanged 3GPP procedure."""
    ax.set_xlim(0, SW); ax.set_ylim(0, SH); ax.set_aspect("equal"); ax.axis("off")
    # the two layers
    ax.add_patch(Rectangle((0.3, 15.8), 117.6, 28.0, fc="#f7f9fc", ec="#9aa7b4", lw=0.6, ls=(0, (3, 2)), zorder=1))
    ax.add_patch(Rectangle((0.3, 0.3), SW - 0.6, 11.7, fc="#f6f6f6", ec="#a5a5a5", lw=0.6, ls=(0, (3, 2)), zorder=1))
    ax.text(1.6, 42.1, "ROAM decision layer (network side)", fontsize=7.2, color="#3f4b57", ha="left", va="center", style="italic")
    ax.text(1.6, 13.8, "3GPP handover procedure, unchanged", fontsize=7.2, color="#4a4a4a", ha="left", va="center", style="italic")
    ROWS = ((33.2, 40.2), (25.2, 32.2), (17.2, 24.2))      # the three rows of the ROAM layer
    mid = [(a + b) / 2 for a, b in ROWS]
    # inputs
    _box(ax, 1.5, ROWS[1][0], 24.0, ROWS[0][1], "Position,\nspeed,\nheading")
    _box(ax, 1.5, ROWS[2][0], 24.0, ROWS[2][1], "Service class\n(5QI)")
    # the three terms of the margin: title in bold, quantity below
    for (y0, y1), title, qty, fc, ec in zip(ROWS, ("Outcome memory", "Path overlap", "Service weight"),
                                            (r"risk $H$,  lateness $L$", r"$\gamma_i\,\Delta f_j$", r"$w_s$"),
                                            ("#fdeceb", "#e7f6f0", "#fdf3dc"), (RED, AQUA, "#b98200")):
        _box(ax, 30.5, y0, 67.5, y1, "", fc=fc, ec=ec)
        ax.text(49.0, (y0 + y1) / 2 + 1.45, title, ha="center", va="center", fontsize=7.6, fontweight="bold", color=INK, zorder=4)
        ax.text(49.0, (y0 + y1) / 2 - 1.7, qty, ha="center", va="center", fontsize=7.6, color=INK, zorder=4)
    # margin
    _box(ax, 74.0, ROWS[2][0], 116.0, ROWS[0][1], "", fc="#e6f0fb", ec=BLUE, lw=1.0)
    ax.text(95.0, 37.2, "Margin per user $i$ and neighbour $j$", ha="center", va="center", fontsize=7.6, fontweight="bold", color=INK, zorder=4)
    ax.text(95.0, 28.9, r"$m_{ij}=h_0+\eta_H H-\eta_L L$" + "\n" + r"$\qquad\;+\,\eta_S w_s-\eta_A\gamma_i\,\Delta f_j$", ha="center", va="center", fontsize=8, color=INK, zorder=4, linespacing=1.45)
    ax.text(95.0, 20.3, r"limited to $[m_{min},\,m_{max}]$", ha="center", va="center", fontsize=7.4, color=INK, zorder=4)
    # standard procedure
    _box(ax, 1.5, 1.4, 26.0, 10.9, "Measurement\nreports " + r"$F_{ic}$, $F_{ij}$", fc="white", ec="#6a6a6a")
    _box(ax, 31.5, 1.4, 78.5, 10.9, "", fc="white", ec="#6a6a6a")
    ax.text(55.0, 7.75, "Standard Event A3 at the terminal", ha="center", va="center", fontsize=7.6, fontweight="bold", color=INK, zorder=4)
    ax.text(55.0, 4.45, r"$F_{ij}-F_{ic}>m_{ij}$ for $T_{TTT}$", ha="center", va="center", fontsize=7.6, color=INK, zorder=4)
    _box(ax, 84.0, 1.4, 122.0, 10.9, "", fc="white", ec="#6a6a6a")
    ax.text(103.0, 7.75, "Handover outcome", ha="center", va="center", fontsize=7.6, fontweight="bold", color=INK, zorder=4)
    ax.text(103.0, 4.45, "useful, unnecessary, early, late", ha="center", va="center", fontsize=7.2, color=INK, zorder=4)
    # arrows
    for y in (mid[0], mid[1]):
        _arrow(ax, [(24.0, y), (30.5, y)])
    _arrow(ax, [(24.0, mid[2]), (30.5, mid[2])])
    for y in mid:
        _arrow(ax, [(67.5, y), (74.0, y)])
    _arrow(ax, [(26.0, 6.15), (31.5, 6.15)]); _arrow(ax, [(78.5, 6.15), (84.0, 6.15)])
    _arrow(ax, [(76.5, ROWS[2][0]), (76.5, 10.9)], color=BLUE, lw=1.1)
    ax.text(78.0, 13.9, r"offset of Event A3:  $O_{cn}=h_0-m_{ij}$", fontsize=7.4, color="#1f5aa3", ha="left", va="center", zorder=4)
    # feedback of the outcome label
    fb = "#2e7d32"
    _arrow(ax, [(120.2, 10.9), (120.2, 45.9), (49.0, 45.9), (49.0, ROWS[0][1])], color=fb, ls=(0, (4, 2)), lw=0.9)
    ax.text(84.5, 45.9, r"outcome label, at most $T_{min}^{s}$ later; one memory for all users", fontsize=7.2, color=fb, ha="center", va="center", zorder=5,
            bbox=dict(fc="white", ec="none", pad=1.2))


def _overlap(ax):
    pts = np.array([[3.2, 4.2], [7.6, 6.3], [7.9, 1.9], [3.0, 8.3], [11.6, 4.4], [0.2, 1.0], [11.5, 8.8], [5.6, -1.6],
                    [-1.5, 5.5], [12.5, 0.2], [7.0, 10.8], [-1.0, 10.0], [14.5, 6.0]])
    vor = Voronoi(pts)
    ax.set_aspect("equal"); ax.axis("off"); ax.set_xlim(0.75, 10.75); ax.set_ylim(0.2, 9.1)
    cols = {0: ("#dbe9f8", BLUE), 1: ("#dcf3ea", AQUA), 2: ("#fbe1e0", RED)}
    for i in range(len(pts)):
        reg = vor.regions[vor.point_region[i]]
        if -1 in reg or not reg:
            continue
        fc, ec = cols.get(i, ("#f4f4f4", "#b5b5b5"))
        ax.add_patch(Polygon(vor.vertices[reg], fc=fc, ec=ec, lw=0.8, zorder=1))
    for i in range(5):
        ax.plot(*pts[i], marker="^", ms=5, color=cols.get(i, ("", "#9a9a9a"))[1], zorder=5, mec="white", mew=0.4)
    ux, uy = 4.5, 4.7
    th = np.degrees(np.arctan2(6.3 - uy, 7.6 - ux)) - 6
    ax.add_patch(Wedge((ux, uy), 4.2, th - 34, th + 34, fc=YELLOW, ec="#a87200", alpha=0.32, lw=0.7, hatch="////", zorder=2))
    ax.plot([ux], [uy], "o", ms=4, color=INK, zorder=6)
    ax.add_patch(FancyArrowPatch((ux, uy), (ux + 1.9 * np.cos(np.radians(th)), uy + 1.9 * np.sin(np.radians(th))),
                                 arrowstyle="-|>", mutation_scale=8, lw=1.1, color=INK, zorder=7, shrinkA=0, shrinkB=0))

    def lab(x, y, s, c):
        ax.text(x, y, s, ha="center", va="center", fontsize=7.4, color=INK, linespacing=1.22,
                bbox=dict(fc="white", ec=c, boxstyle="round,pad=0.22", lw=0.8), zorder=8)
    lab(2.75, 2.9, "serving cell $c$\n$f_c = 0.27$", BLUE)
    lab(8.75, 7.85, "neighbour $j_1$\n$f_{j_1} = 0.62$", AQUA)
    lab(8.65, 1.0, "neighbour $j_2$\n$f_{j_2} = 0.08$", RED)
    ax.text(3.95, 7.1, "predicted-motion sector\n" + r"radius $v\,T_p$, half-angle $\varphi$", ha="center", fontsize=7.2, color="#7a5300", linespacing=1.22)
    ax.text(4.5, 4.05, "user", fontsize=7.4, ha="center", color=INK)


def _outcomes(fig, x0, y0, w, h, Wmm, Hmm):
    """Schematic of the four outcome classes of a handover c -> j (Section 3.3): SINR of the two cells around the decision.
    Position and size in millimetres; the curves are illustrations, not data."""
    t = np.linspace(-3.0, 7.0, 400)
    QOUT, TW = -8.0, 4.5                                   # threshold of the failure model, observation window [s]
    gap_x, gap_y, top, bot = 2.2, 9.0, 6.2, 7.4
    pw = (w - gap_x) / 2; ph = (h - top - bot - gap_y) / 2
    sm = lambda u, k=1.6: 1 / (1 + np.exp(-k * u))        # smooth step

    def useful():
        return 7 - 13 * sm(t - 0.4, 0.9), -7 + 14 * sm(t + 0.6, 1.1), None, None
    def unnecessary():
        return 4.5 - 0.25 * t + 0.6 * np.sin(1.3 * t), -4 + 12.5 * np.exp(-((t - 0.5) ** 2) / 2.2), 2.4, None
    def early():
        return 6 - 12 * sm(t - 0.8, 0.9), -3 + 9 * np.exp(-((t + 0.1) ** 2) / 1.6) - 9.5 * sm(t - 1.6, 2.2), None, 3.0
    def late():
        return 7 - 21 * sm(t + 1.6, 1.3), -5 + 13 * sm(t + 1.8, 1.0), None, -0.05
    CASES = [("Useful", "stays and gains", useful), ("Unnecessary", "short stay or no gain", unnecessary),
             ("Early", "fails in the target", early), ("Late", "source link lost first", late)]
    for k, (name, what, fn) in enumerate(CASES):
        col, row = k % 2, k // 2
        ax = fig.add_axes([(x0 + col * (pw + gap_x)) / Wmm, (y0 + bot + (1 - row) * (ph + gap_y)) / Hmm, pw / Wmm, ph / Hmm])
        src, tgt, back, rlf = fn()
        late_case = name == "Late"
        if not late_case:
            ax.axvspan(0, back if back else (rlf if rlf else TW), color=YELLOW, alpha=0.16, lw=0, zorder=0)
        ax.axhline(QOUT, color=INK, lw=0.6, ls=(0, (4, 1.5, 1, 1.5)), zorder=1)
        end = rlf if (rlf is not None and not late_case) else 7.0
        m_before = t <= (rlf if late_case else 0.0)
        m_after = (t >= 0.0) & (t <= (back if back else end))
        # the serving link is drawn solid and heavy, the other cell thin and dashed
        ax.plot(t[t <= end], src[t <= end], color=BLUE, lw=0.8, ls=(0, (3, 1.5)), zorder=2)
        ax.plot(t[t <= end], tgt[t <= end], color=ORANGE, lw=0.8, ls=(0, (3, 1.5)), zorder=2)
        ax.plot(t[m_before], src[m_before], color=BLUE, lw=1.6, zorder=3)
        if not late_case:
            ax.plot(t[m_after], tgt[m_after], color=ORANGE, lw=1.6, zorder=3)
            ax.axvline(0, color=INK, lw=0.7, zorder=1)
        if back:
            m = t >= back
            ax.plot(t[m], src[m], color=BLUE, lw=1.6, zorder=3); ax.axvline(back, color=INK, lw=0.7, zorder=1)
        if rlf is not None:
            y = (src if late_case else tgt)[np.argmin(np.abs(t - rlf))]
            ax.plot([rlf], [y], marker="x", ms=5.5, mew=1.3, color=INK, zorder=5)
            ax.text(rlf + 0.45, y + 0.3, "failure", fontsize=7, ha="left", va="center", color=INK)
        ax.set_xlim(-3, 7); ax.set_ylim(-15.5, 12.5); ax.set_xticks([]); ax.set_yticks([])
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.text(0.0, 1.0 + 3.3 / ph, name, transform=ax.transAxes, fontsize=7.8, fontweight="bold", ha="left", va="bottom", color=INK)
        ax.text(0.0, 1.0 + 0.5 / ph, what, transform=ax.transAxes, fontsize=7.2, ha="left", va="bottom", color=INK)
        if k == 0:
            ax.text(-2.8, QOUT - 0.9, "$Q_{out}$", fontsize=7, ha="left", va="top", color=INK)
        if col == 0:
            ax.set_ylabel("SINR", labelpad=1.5, fontsize=7.4)
        ax.set_xlabel("time", labelpad=1.0, fontsize=7.4)
    h_ = [Line2D([], [], color=BLUE, lw=1.6), Line2D([], [], color=ORANGE, lw=1.6), Line2D([], [], color="#666666", lw=0.8, ls=(0, (3, 1.5))),
          Rectangle((0, 0), 1, 1, fc=YELLOW, alpha=0.3, lw=0)]
    l_ = ["source $c$", "target $j$", "not serving", "stay in $j$"]
    fig.legend(h_, l_, ncol=4, loc="lower left", bbox_to_anchor=(x0 / Wmm, y0 / Hmm), columnspacing=0.7, handletextpad=0.25, handlelength=1.2,
               borderaxespad=0.0, borderpad=0.0, labelspacing=0.25, fontsize=7.2)


def fig_scheme():
    Hmm = SH + 3.6                                        # figure height [mm]: the panels and their titles
    fig = plt.figure(figsize=(WT, Hmm * MM))
    Wmm = WT / MM
    wa = Wmm - SW - 3.0                                   # width of the outcome panel
    _outcomes(fig, 0.6, 0.0, wa - 0.6, SH, Wmm, Hmm)
    b = fig.add_axes([(wa + 3.0) / Wmm, 0, SW / Wmm, SH / Hmm])
    _scheme(b)
    fig.text(0.3 / Wmm, 1.0, "(a) Problem: the four outcomes of a handover", ha="left", va="top", fontsize=8.5)
    fig.text((wa + 3.0 + 0.3) / Wmm, 1.0, "(b) Proposed scheme: overview of ROAM", ha="left", va="top", fontsize=8.5)
    savefig(fig, "fig_i_scheme")


def fig_overlap():
    """Path overlap (Section 4.4), one column wide: the sector and the best-server regions, with what follows for the margin."""
    Hmm = 39.0
    fig = plt.figure(figsize=(WC, Hmm * MM))
    fig.patches.append(Rectangle((0, 0), 1, 1, transform=fig.transFigure, fc="none", ec="none"))     # keeps the full column width in the tight bounding box
    Wmm = WC / MM
    wg = Hmm * 10.0 / 8.9                                 # the sketch keeps its aspect ratio
    a = fig.add_axes([0, 0, wg / Wmm, 1.0])
    _overlap(a)
    x = (wg + 2.0) / Wmm
    kw = dict(ha="left", va="top", fontsize=7.6, color=INK, linespacing=1.3)
    fig.text(x, 0.98, "Overlap of cell $k$", fontweight="bold", **kw)
    fig.text(x, 0.87, r"$f_k=\dfrac{\mathrm{Area}(R_p\cap C_k)}{\mathrm{Area}(R_p)}$", **kw)
    fig.text(x, 0.61, "Alignment of a target", fontweight="bold", **kw)
    fig.text(x, 0.50, r"$\Delta f_j=f_j-f_c$", **kw)
    fig.text(x, 0.365, "$j_1$:  $+0.35$,\nmargin lowered", **kw)
    fig.text(x, 0.165, "$j_2$:  $-0.19$,\nmargin raised", **kw)
    savefig(fig, "fig_i_overlap")


# ------------------------------------------------------------------ Fig. 2: results in the system-level simulator
S = json.load(open(os.path.join(os.environ.get("ROAM_RESULTS", os.path.join(ROOT, "results")), "summary.json")))
PROF = ["pedestrian", "vehicular", "street", "highway", "train"]
PROFL = ["Ped.", "Open", "Street", "Hwy.", "Train"]


def _pareto(ax):
    budget = S["tuned"]["_budget_fail_pm"]; FLOOR = 0.03
    for f in ORDER[::-1]:
        rows = S["tune"][f]
        x = np.array([r["UHO_pm"] for r in rows]); y = np.maximum(np.array([r["fail_pm"] for r in rows]), FLOOR)
        main = f in ("Proposed", "A3")
        ax.scatter(x, y, s=12 if main else 7, marker=MK[f], color=COL[f], alpha=1.0 if main else 0.55,
                   edgecolor="white", linewidth=0.25, zorder=5 if main else 3)
        if main:                                          # lower-left front
            o = np.argsort(x); fx, fy, best = [], [], 1e9
            for i in o:
                if y[i] < best - 1e-12:
                    fx.append(x[i]); fy.append(y[i]); best = y[i]
            ax.plot(fx, fy, color=COL[f], lw=1.0, zorder=4)
        sel = [r for r in rows if r["selected"]][0]
        ax.scatter([sel["UHO_pm"]], [max(sel["fail_pm"], FLOOR)], s=40, marker="o", facecolor="none",
                   edgecolor=COL[f] if main else "#555555", linewidth=0.9 if main else 0.6, zorder=6)
    ax.axhline(budget, color=INK, ls=(0, (4, 2)), lw=0.7, zorder=2)
    ax.text(0.02, budget * 0.93, "failure budget", fontsize=7, ha="left", va="top", transform=ax.get_yaxis_transform())
    ax.text(0.985, FLOOR * 1.1, "PBPHS: below 0.03", fontsize=6.8, color=MUTE, ha="right", va="bottom", transform=ax.get_yaxis_transform())
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(FLOOR * 0.85, 2.6)
    ax.set_xlabel("Unnecessary HOs per user-minute"); ax.set_ylabel("Failures\nper user-minute", linespacing=1.1)
    ax.xaxis.set_major_formatter(plain); ax.yaxis.set_major_formatter(plain)
    ax.yaxis.set_major_locator(FixedLocator([0.03, 0.1, 0.3, 1])); ax.yaxis.set_minor_formatter(NullFormatter())
    style(ax, grid="both"); ax.grid(which="minor", lw=0.3, color="#ececec")


def _dots(ax, metric, ylabel, log=False, prof=None):
    """One marker per method and mobility profile: mean over the test seeds with its 95 % confidence interval."""
    prof = prof if prof is not None else list(range(len(PROF)))
    n = len(ORDER); w = 0.8 / n
    for g in range(len(prof)):
        if prof[g] % 2 == 1:
            ax.axvspan(g - 0.5, g + 0.5, color="#f3f3f3", lw=0, zorder=0)
    for k, m in enumerate(ORDER):
        v = [(S["profiles"][PROF[p]][m][metric]["mean"], S["profiles"][PROF[p]][m][metric]["ci"]) for p in prof]
        main = m in ("Proposed", "A3")
        ax.errorbar(np.arange(len(prof)) + (k - (n - 1) / 2) * w, [a for a, _ in v], yerr=[b for _, b in v], ls="none", marker=MK[m],
                    ms=4.2 if main else 3.2, color=COL[m], mec="white", mew=0.3, elinewidth=0.7, ecolor=COL[m], capsize=1.3, capthick=0.6,
                    zorder=5 if main else 4)
    ax.set_xticks(range(len(prof))); ax.set_xticklabels([PROFL[p] for p in prof]); ax.tick_params(axis="x", length=0); ax.set_xlim(-0.5, len(prof) - 0.5)
    if ylabel:
        ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale("log"); ax.yaxis.set_major_formatter(plain); ax.yaxis.set_minor_formatter(NullFormatter())
    style(ax)


def _half_up(x):
    """Decimal rounding, half away from zero, as in the text of the paper."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(repr(float(x))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fig_results():
    fig = plt.figure(figsize=(WT, 1.62))
    gs = fig.add_gridspec(1, 3, wspace=0.31, width_ratios=[0.9, 1, 1.04], left=0.064, right=0.998, bottom=0.185, top=0.815)
    a = fig.add_subplot(gs[0]); b = fig.add_subplot(gs[1])
    g2 = gs[2].subgridspec(1, 2, width_ratios=[4, 1.0], wspace=0.2)
    c = fig.add_subplot(g2[0]); c2 = fig.add_subplot(g2[1])
    _pareto(a); panel(a, "a", "Tuning: all 192 configurations")
    _dots(b, "UHO_pm", "Unnecessary HOs\nper user-minute", log=True); panel(b, "b", "Test: unnecessary handovers")
    b.yaxis.set_major_locator(FixedLocator([0.2, 0.5, 1, 2, 5, 10, 20])); b.set_ylim(0.135, None)
    for g, p in enumerate(PROF):                           # reduction by ROAM against tuned A3, as quoted in the text
        r = 100 * (1 - S["profiles"][p]["Proposed"]["UHO_pm"]["mean"] / S["profiles"][p]["A3"]["UHO_pm"]["mean"])
        b.text(g, 0.03, u"−%d%%" % _half_up(r), fontsize=7, color="#1f5aa3", ha="center", va="bottom", transform=b.get_xaxis_transform())
    # failures: the high-speed train has its own scale, because its rates and intervals are several times those of the other profiles
    _dots(c, "fail_pm", "Failures\nper user-minute", prof=[0, 1, 2, 3]); panel(c, "c", "Test: mobility failures")
    _dots(c2, "fail_pm", "", prof=[4])
    c.set_ylim(0, None); c2.set_ylim(0, None)
    h = [Line2D([], [], marker=MK[m], ls="", color=COL[m], ms=4.2, mec="white", mew=0.3) for m in ORDER]
    l = [LAB[m] for m in ORDER]
    h.append(Line2D([], [], marker="o", ls="", mfc="none", mec="#555555", ms=5.2, mew=0.8)); l.append("selected")
    fig.legend(h, l, ncol=9, loc="upper center", bbox_to_anchor=(0.525, 1.0), columnspacing=1.0, handletextpad=0.2, borderaxespad=0.0, borderpad=0.0)
    savefig(fig, "fig_i_results")


def fig_more():
    """Fig. 4 of the paper: what is removed, the effect of load, and what the outcome memory adds (system-level simulator)."""
    fig = plt.figure(figsize=(WT, 1.5))
    gs = fig.add_gridspec(1, 4, wspace=0.36, width_ratios=[0.8, 0.85, 1.3, 1.1], left=0.062, right=0.998, bottom=0.215, top=0.87)
    a, b, c, d = (fig.add_subplot(g) for g in gs)
    ekw = dict(capsize=1.4, capthick=0.5, elinewidth=0.6, mec="white", mew=0.3, ms=3.6, lw=1.1)
    # (a) unnecessary handovers by cause, tuned A3 and ROAM
    seg = [("c_pp", "ping-pong", VIOLET, "////"), ("c_short", "short stay", YELLOW, ""), ("c_gain", "no gain", AQUA, "....")]
    umin = 300 * 240 / 60.0
    xs, labs = [], []
    for g, p in enumerate(("street", "highway")):
        for k, m in enumerate(("A3", "Proposed")):
            x = g * 2.5 + k; xs.append(x); labs.append("A3" if m == "A3" else "ROAM"); bottom = 0.0
            for key, lab, col, hatch in seg:
                v = S["profiles"][p][m][key]["mean"] / umin
                a.bar(x, v, 0.78, bottom=bottom, color=col, hatch=hatch, edgecolor="white", linewidth=0.4, zorder=3, label=lab if (g, k) == (0, 0) else None)
                bottom += v
        a.text(g * 2.5 + 0.5, -0.135, ("Street", "Highway")[g], transform=a.get_xaxis_transform(), ha="center", va="top", fontsize=7.5)
    a.set_xticks(xs); a.set_xticklabels(labs, fontsize=7); a.tick_params(axis="x", length=0, pad=1.5)
    a.set_ylabel("Unnecessary HOs\nper user-minute", linespacing=1.1); style(a)
    a.legend(loc="upper left", borderaxespad=0.1, handlelength=1.0, handletextpad=0.3, labelspacing=0.2, fontsize=7)
    panel(a, "a", "By cause")
    # (b) load
    users = sorted(S["load"].keys(), key=int)
    for m in ("A3", "Proposed"):
        v = [(S["load"][u][m]["UHO_pm"]["mean"], S["load"][u][m]["UHO_pm"]["ci"]) for u in users]
        b.errorbar([int(u) for u in users], [x for x, _ in v], yerr=[y for _, y in v], color=COL[m], marker=MK[m], label="A3 (tuned)" if m == "A3" else "ROAM", **ekw)
    b.set_xlabel("Users", labelpad=1.5); b.set_xticks([int(u) for u in users]); b.set_ylim(0, None); style(b)
    b.legend(loc="lower right", borderaxespad=0.2, handlelength=1.6, handletextpad=0.3, labelspacing=0.2, fontsize=7)
    panel(b, "b", "Load (street grid)")
    # (c) time course on the highway, environment redrawn at 240 s
    cn = {"A3": (ORANGE, "-", "s", "A3 (tuned)"), "table fixed at its prior": ("#c8960c", (0, (4, 1.5)), "D", "ROAM, constant offset"),
          "tau_f = 600 s": (BLUE, "-", "o", "ROAM, learned table")}
    for k, (col, ls, mk, lab) in cn.items():
        cv = S["nonstat_curves"]["highway"][k]
        c.errorbar(cv["t"], cv["uho"], yerr=cv["uho_ci"], color=col, ls=ls, marker=mk, label=lab, **dict(ekw, ms=3.0))
    c.axvline(240, color=INK, lw=0.7, ls=(0, (4, 2)), zorder=1)
    c.text(250, 0.03, "environment redrawn", transform=c.get_xaxis_transform(), fontsize=7, ha="left", va="bottom", color=INK)
    c.set_xlabel("Time [s]", labelpad=1.5); c.set_ylim(0, 8.8); c.set_yticks([0, 2, 4, 6]); style(c)
    c.legend(loc="upper left", borderaxespad=0.1, handlelength=2.0, handletextpad=0.3, labelspacing=0.15, fontsize=7)
    panel(c, "c", "Memory over time (highway)")
    # (d) learned table against the constant offset that an empty table returns
    cond = [("Street", S["hht"]["street"], "warm start + online"), ("Hwy.", S["hht"]["highway"], "warm start + online"),
            ("Street", S["tempo"]["street"], "ROAM"), ("Hwy.", S["tempo"]["highway"], "ROAM")]
    for g, (lab, node, key) in enumerate(cond):
        x = g + (0.35 if g >= 2 else 0.0)
        for k, (kk, col, hatch, l2) in enumerate(((key, BLUE, "", "learned table"), ("table fixed at its prior", "#c8960c", "////", "constant offset"))):
            n = node[kk]["UHO_pm"]
            d.bar(x + (k - 0.5) * 0.4, n["mean"], 0.38, yerr=n["ci"], color=col, hatch=hatch, edgecolor="white", linewidth=0.4, zorder=3,
                  error_kw=dict(lw=0.6, capsize=1.3, capthick=0.5, ecolor="#222222"), label=l2 if g == 0 else None)
    d.set_xticks([0, 1, 2.35, 3.35]); d.set_xticklabels([x[0] for x in cond], fontsize=7); d.tick_params(axis="x", length=0, pad=1.5)
    d.text(0.5, -0.135, "static field", transform=d.get_xaxis_transform(), ha="center", va="top", fontsize=7.5)
    d.text(2.85, -0.135, "per-user shadowing", transform=d.get_xaxis_transform(), ha="center", va="top", fontsize=7.5)
    d.set_ylim(0, 3.15)
    style(d); d.legend(loc="upper right", borderaxespad=0.1, handlelength=1.0, handletextpad=0.3, labelspacing=0.2, fontsize=7)
    panel(d, "d", "Memory or constant")
    for ax in (b, c, d):
        ax.set_ylabel("")
    savefig(fig, "fig_i_more")


# ------------------------------------------------------------------ ns-3
NS = os.path.join(ROOT, "ns3", "results")
RAW = os.path.join(ROOT, "ns3", "fig5_runs")           # raw files of the two runs of the map
J = json.load(open(os.path.join(NS, "report_study.json"), encoding="utf-8"))
GX, GY, STREET = 433.0, 250.0, 20.0                        # road grid and street width of the urban scenario [m]
MAP_CELL = (200, 16)                                       # design cell shown: inter-site distance [m], speed [m/s]


def _rows(folder):
    return list(csv.DictReader(open(os.path.join(NS, folder, "results.csv"), encoding="utf-8")))


def pick_run():
    """The seed of the design cell MAP_CELL whose pair of runs (tuned A3, ROAM) is closest to the means of that cell:
    smallest sum of squared standardised deviations of the four rates (unnecessary handovers and failures of both rules)."""
    d, v = MAP_CELL
    rows = [r for r in _rows("campaign_urban") if r["phase"] == "test" and r["label"] in ("A3_tuned", "ROAM") and int(r["isd"]) == d and int(r["speed"]) == v]
    seeds = sorted({int(r["rngRun"]) for r in rows})
    val = {s: [] for s in seeds}
    for lab in ("A3_tuned", "ROAM"):
        for k in ("uho_pm", "fail_pm"):
            x = {int(r["rngRun"]): float(r[k]) for r in rows if r["label"] == lab}
            mu, sd = np.mean(list(x.values())), np.std(list(x.values()), ddof=1)
            for s in seeds:
                val[s].append(((x[s] - mu) / sd) ** 2)
    best = min(seeds, key=lambda s: (sum(val[s]), s))
    return best, {r["label"]: r for r in rows if int(r["rngRun"]) == best}, len(seeds)


def sites(isd):
    """Site positions as in ns3/scenario/ho-scenario.cc: hexagonal plan, each site moved to the nearest point of a street centre line."""
    plan = [(0.0, 0.0)] + [(isd * np.cos(k * np.pi / 3), isd * np.sin(k * np.pi / 3)) for k in range(6)]
    out = []
    for (px, py) in plan:
        best, q = 1e300, (px, py)
        for k in (-1, 0, 1):
            cx = min(max(px, -GX), GX); dd = np.hypot(px - cx, py - k * GY)
            if dd < best - 1e-9:
                best, q = dd, (cx, k * GY)
        for k in (-1, 0, 1):
            cy = min(max(py, -GY), GY); dd = np.hypot(px - k * GX, py - cy)
            if dd < best - 1e-9:
                best, q = dd, (k * GX, cy)
        out.append(q)
    return out


def _events(job):
    """Every handover attempt and every radio-link failure of the measured part of one run, from the raw files."""
    base = os.path.join(RAW, job)
    att = [a for a in csv.DictReader(open(base + "_att.csv", encoding="utf-8")) if a["in_window"] == "1"]
    rlf = [a for a in csv.DictReader(open(base + "_rlf.csv", encoding="utf-8")) if a["in_window"] == "1" and a["handled"] != "late_attempt"]
    return att, rlf


OUTC = [("useful", "useful", "o", "#8c8c8c"), ("unnecessary", "unnecessary", "o", RED), ("early", "early", "D", VIOLET)]
SIDE = {"useful": +1.0, "unnecessary": -1.0, "early": -1.0}
OFF = 17.0                                                 # sideways displacement of the markers from the centre line [m]


def _map(ax, job, isd):
    ax.set_aspect("equal"); ax.axis("off")
    pad = 34.0
    ax.set_xlim(-GX - pad, GX + pad); ax.set_ylim(-GY - pad, GY + pad)
    ax.add_patch(Rectangle((-GX - STREET / 2, -GY - STREET / 2), 2 * GX + STREET, 2 * GY + STREET, fc="white", ec="#b0b0b0", lw=0.4, zorder=0))
    for bx in (-1, 0):
        for by in (-1, 0):
            ax.add_patch(Rectangle((bx * GX + STREET / 2, by * GY + STREET / 2), GX - STREET, GY - STREET, fc="#e3e3e3", ec="#a8a8a8", lw=0.4, zorder=1))
    att, rlf = _events(job)
    cnt = {}
    for key, _, mk, col in OUTC:
        P = [(float(a["x"]), float(a["y"])) for a in att if a["outcome_eval"] == key]
        cnt[key] = len(P)
        if not P:
            continue
        P = np.array(P)
        ew = np.isclose(np.abs(P[:, 1]), GY) | np.isclose(P[:, 1], 0.0)          # on an east-west street: displace north or south
        ns_ = ~ew
        dx = np.where(ns_, -SIDE[key] * OFF, 0.0); dy = np.where(ew, SIDE[key] * OFF, 0.0)
        hollow = key == "useful"
        big = key == "early"
        ax.scatter(P[:, 0] + dx, P[:, 1] + dy, s=9 if big else 4.6, marker=mk, facecolor="white" if hollow else col, edgecolor=col, linewidth=0.4,
                   alpha=0.9, zorder=5 if big else 3 if hollow else 4)
    late = [(float(a["x"]), float(a["y"])) for a in att if a["outcome_eval"] == "late"]
    cens = [(float(a["x"]), float(a["y"])) for a in att if a["outcome_eval"] == "censored"]
    t310 = [(float(a["x"]), float(a["y"])) for a in rlf]
    cnt["late"] = len(late); cnt["t310"] = len(t310); cnt["censored"] = len(cens)
    cnt["attempts"] = len(att)
    assert cnt["attempts"] == cnt["useful"] + cnt["unnecessary"] + cnt["early"] + cnt["late"] + cnt["censored"], cnt
    outer = lambda a: abs(abs(float(a["x"])) - GX) < 1e-6                     # on one of the two outer north-south streets (no site)
    cnt["outer_attempts"] = sum(1 for a in att if outer(a))
    cnt["outer_unnecessary"] = sum(1 for a in att if outer(a) and a["outcome_eval"] == "unnecessary")
    cnt["outer_failures"] = sum(1 for a in att if outer(a) and a["outcome_eval"] == "late") + sum(1 for a in rlf if outer(a))
    if cens:                                               # outcome window cut by the end of the run: on the centre line
        L = np.array(cens); ax.scatter(L[:, 0], L[:, 1], s=2.2, marker="s", color="#555555", linewidth=0, zorder=4)
    if late:
        L = np.array(late); ax.scatter(L[:, 0], L[:, 1], s=24, marker="x", color=INK, linewidth=1.0, zorder=7)
    if t310:
        L = np.array(t310); ax.scatter(L[:, 0], L[:, 1], s=30, marker="+", color=INK, linewidth=1.0, zorder=7)
    for (x, y) in sites(isd):
        ax.plot([x], [y], marker="^", ms=5.2, color=BLUE, mec="white", mew=0.5, zorder=6)
    # scale bar in the lower-left building block
    bx0, by0 = -GX + STREET / 2 + 22.0, -GY + STREET / 2 + 20.0
    ax.plot([bx0, bx0 + 200.0], [by0, by0], color=INK, lw=0.9, zorder=2, solid_capstyle="butt")
    for xx in (bx0, bx0 + 200.0):
        ax.plot([xx, xx], [by0 - 7.0, by0 + 7.0], color=INK, lw=0.7, zorder=2)
    ax.text(bx0 + 100.0, by0 + 12.0, "200 m", fontsize=7, ha="center", va="bottom", color=INK, zorder=2)
    return cnt


def _front(ax):
    """ns-3, urban grid: the 24 A3 and 24 ROAM configurations on the test cells; same axes as Fig. 2(a)."""
    fr = J["frontier"]["urban"]; cfg = fr["configs"]; floor = 0.004
    t = json.load(open(os.path.join(NS, "campaign_urban", "tuned_ns3.json"), encoding="utf-8"))
    for fam, key in (("ROAM", "Proposed"), ("A3", "A3")):
        labs = [l for l in cfg if l.startswith(fam + "_")]
        ax.scatter([cfg[l]["uho_pm"] for l in labs], [max(cfg[l]["fail_pm"], floor) for l in labs], s=12, marker=MK[key], color=COL[key],
                   edgecolor="white", linewidth=0.25, zorder=4, label=fam)
        front = fr["pareto_" + fam]
        ax.plot([cfg[l]["uho_pm"] for l in front], [max(cfg[l]["fail_pm"], floor) for l in front], color=COL[key], lw=1.0, zorder=2)
        s = cfg[t[fam]["label"]]
        ax.scatter([s["uho_pm"]], [max(s["fail_pm"], floor)], s=40, marker="o", facecolor="none", edgecolor=COL[key], linewidth=0.9, zorder=5)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Unnecessary HOs per UE-minute"); ax.set_ylabel("Failures per UE-minute", labelpad=1.5)
    style(ax, grid="both"); ax.grid(which="minor", lw=0.3, color="#ececec")
    ax.xaxis.set_major_locator(FixedLocator([0.5, 1, 2, 5])); ax.xaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_formatter(plain); ax.yaxis.set_major_formatter(plain)
    h, l = ax.get_legend_handles_labels()
    h.append(Line2D([], [], marker="o", ls="", mfc="none", mec="#555555", ms=5.2, mew=0.8)); l.append("selected")
    ax.legend(h, l, loc="lower left", borderaxespad=0.25, handletextpad=0.2, labelspacing=0.3)


def fig_ns3():
    seed, runs, nseed = pick_run()
    isd = MAP_CELL[0]
    Wmm = WT / MM
    mw = 60.5; mh = mw * (2 * GY + 68.0) / (2 * GX + 68.0)                  # width and height of one map [mm]
    Hmm = mh + 4.2 + 4.6                                                    # title line above, legend line below
    fig = plt.figure(figsize=(WT, Hmm * MM))
    info = {"cell": {"isd": isd, "speed": MAP_CELL[1]}, "seed": seed, "seeds_in_cell": nseed, "offset_m": OFF, "runs": {}}
    for k, (lab, name) in enumerate((("A3_tuned", "tuned A3"), ("ROAM", "ROAM"))):
        ax = fig.add_axes([k * (mw + 1.0) / Wmm, 4.6 / Hmm, mw / Wmm, mh / Hmm])
        r = runs[lab]
        cnt = _map(ax, r["job_id"], isd)
        fig.text((k * (mw + 1.0) + 0.3) / Wmm, 1.0, "(%s) One run, %s" % ("ab"[k], name), ha="left", va="top", fontsize=8.5)
        for key, col in (("attempts", "attempts"), ("useful", "useful"), ("unnecessary", "unnecessary"), ("early", "early"), ("late", "late"), ("censored", "censored")):
            assert cnt[key] == int(r[col]), (lab, key, cnt[key], r[col])              # the raw files agree with results.csv
        assert cnt["late"] + cnt["t310"] + cnt["early"] == int(r["failures"]) or cnt["late"] + cnt["t310"] == int(r["failures"]), (lab, cnt, r["failures"])
        info["runs"][lab] = dict(job_id=r["job_id"], ue_min=float(r["ue_min"]), failures=int(r["failures"]), uho_pm=float(r["uho_pm"]), fail_pm=float(r["fail_pm"]), **cnt)
    h = [Line2D([], [], marker="o", ls="", mfc="white", mec="#8c8c8c", ms=3.4, mew=0.6),
         Line2D([], [], marker="o", ls="", mfc=RED, mec=RED, ms=3.4, mew=0.6),
         Line2D([], [], marker="D", ls="", mfc=VIOLET, mec=VIOLET, ms=3.6, mew=0.4),
         Line2D([], [], marker="x", ls="", color=INK, ms=4.6, mew=1.0),
         Line2D([], [], marker="+", ls="", color=INK, ms=5.4, mew=1.0),
         Line2D([], [], marker="^", ls="", color=BLUE, mec="white", mew=0.5, ms=5.2),
         Rectangle((0, 0), 1, 1, fc="#e3e3e3", ec="#a8a8a8", lw=0.4)]
    l = ["useful", "unnecessary", "early", "late command", r"$T_{310}$ expiry", "site", "building"]
    fig.legend(h, l, ncol=7, loc="lower left", bbox_to_anchor=(0.0, 0.0), columnspacing=1.0, handletextpad=0.2, borderaxespad=0.0, borderpad=0.0, handlelength=1.2)
    x0 = (2 * mw + 1.0 + 11.5) / Wmm
    ax = fig.add_axes([x0, 9.0 / Hmm, 1.0 - x0 - 0.4 / Wmm, (Hmm - 9.0 - 4.2) / Hmm])
    _front(ax)
    fig.text((2 * mw + 1.0 + 2.5) / Wmm, 1.0, "(c) All 48 configurations", ha="left", va="top", fontsize=8.5)
    savefig(fig, "fig_i_ns3")
    json.dump(info, open(os.path.join(FIG8, "fig_i_ns3.json"), "w", encoding="utf-8"), indent=1)
    print("map run: seed", seed, info["runs"])


if __name__ == "__main__":
    for w in (sys.argv[1:] or ["scheme", "overlap", "results", "more", "ns3"]):
        globals()["fig_" + w]()
