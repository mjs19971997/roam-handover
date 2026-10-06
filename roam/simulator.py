# -*- coding: utf-8 -*-
"""Protocol-aware, load-coupled, fully vectorised system-level handover simulator.

* all users advance together on a 100 ms grid, so cell load, interference and the
  shared outcome tables evolve causally in time (there is no "user order");
* L3-filtered RSRP measurements, RLF detection with Qout/T310, handover failure
  and re-establishment, handover interruption time;
* an explicit traffic-load model: per-service rate demand, per-cell PRB budget,
  GBR-first scheduling and load-coupled inter-cell interference (SINR);
* the *evaluation* label of a handover is outcome based and uses the
  counterfactual quality of the source cell; it contains no quantity that any
  policy optimises.  The *learning* label fed back to a policy uses only what
  the network can observe (dwell time, UE measurement reports, failure events).

A decision rule is any object with the interface of `roam.policies.Base`; the
simulator calls its hooks and never looks inside it.
"""
from dataclasses import dataclass
import time

import numpy as np

from .services import SERVICES

# ----------------------------------------------------------------------------
# service tables (index = position in SERVICES)
# ----------------------------------------------------------------------------
SVC_KEYS = [s.key for s in SERVICES]
SVC_TMIN = np.array([s.T_min for s in SERVICES])
SVC_THQ = np.array([s.theta_Q for s in SERVICES])
SVC_W = np.array([s.w_int for s in SERVICES])
SVC_GBR = np.array([s.resource != "Non-GBR" for s in SERVICES])
SVC_PDB = np.array([s.pdb_ms for s in SERVICES], dtype=float)
#                      voice  vcall  gaming stream web      [Mbit/s]
SVC_RATE = np.array([0.10, 2.00, 1.00, 5.00, 1.00])
SVC_SHARE = np.array([s.share for s in SERVICES])


@dataclass
class SimParams:
    """Simulation parameters (radio, link-failure model, load model, metric scaling)."""
    # --- time ---
    dt: float = 0.1            # simulation step [s]
    T_sim: float = 240.0       # run length [s]
    # --- radio ---
    shadow_sigma: float = 4.0  # log-normal shadowing std [dB]
    d_corr: float = 50.0       # Gudmundson decorrelation distance [m]
    xcorr: float = 0.5         # inter-site shadowing correlation (3GPP TR 38.901)
    shadow_mode: str = "spatial"   # "spatial": static 2-D field + small temporal part; "temporal": per-user process
    sigma_t: float = 1.5       # temporal (dynamic blockage) component in spatial mode [dB]
    tau_t: float = 1.0         # its correlation time [s]
    grid_res: float = 5.0      # resolution of the shadowing field [m]
    blk_frac: float = 0.25     # share of blockage-prone cells
    blk_mult: float = 1.5      # their shadowing-std multiplier
    l3_a: float = 0.30         # L3 filter weight per 100 ms sample
    noise_dbm: float = -122.0  # thermal noise per RE (30 kHz SCS, NF 7 dB)
    chi: float = 0.20          # inter-cell interference coupling (beam/sidelobe isolation, -7 dB)
    # --- link failure model (3GPP TR 36.839) ---
    Qout: float = -8.0         # [dB]
    T310: float = 1.0          # [s]
    T_reest: float = 1.0       # re-establishment outage after RLF/HOF [s]
    T_int: float = 0.05        # handover interruption time [s]
    T_pp: float = 1.0          # ping-pong window (minimum time-of-stay) [s]
    # --- load model ---
    W_hz: float = 38.16e6      # 106 PRB x 360 kHz (40 MHz carrier, 30 kHz SCS)
    se_max: float = 7.4        # spectral-efficiency cap [bit/s/Hz]
    hot_frac: float = 0.25     # share of hotspot cells
    bg_hot: tuple = (0.55, 0.85)   # background load of hotspot cells
    bg_norm: tuple = (0.05, 0.25)  # background load of the other cells
    rho_smooth: float = 0.5
    # --- path-alignment threshold, used only by the alternative metric UHR_legacy ---
    theta_delta: float = 0.10
    # --- metric scaling for the threshold-sensitivity study ---
    tmin_scale: float = 1.0
    thq_scale: float = 1.0
    # --- motion-prediction error injected for the sensitivity study ---
    head_err: float = 0.0      # heading error std [rad]
    speed_err: float = 0.0     # relative speed error std
    seed: int = 7


# ----------------------------------------------------------------------------
# environment
# ----------------------------------------------------------------------------
class RadioEnv:
    """Simulation environment: radio map + neighbour graph + (re-drawable) heterogeneity.

    `base` is a `roam.radiomap.RadioMap`.  The heterogeneity consists of the
    blockage-prone cells (larger shadowing std), the hotspot cells (higher
    background load) and, in spatial shadowing mode, the static shadowing field.
    """

    def __init__(self, base, P, k_neighbors=6, het_seed=11):
        self.name = base.name
        self.base = base
        self.cells = list(base.cells)
        self.M = len(self.cells)
        self.pos = np.asarray(base.cell_pos, dtype=float)
        self.A = np.asarray(base.A_arr, dtype=float)
        self.n = np.asarray(base.n_arr, dtype=float)
        self.xmin, self.xmax = float(base.xmin), float(base.xmax)
        self.ymin, self.ymax = float(base.ymin), float(base.ymax)
        self.route = getattr(base, "route", None)       # (L,2) polyline or None
        d = np.linalg.norm(self.pos[:, None] - self.pos[None], axis=2)
        k = min(k_neighbors, self.M - 1)
        self.nb = np.argsort(d, axis=1)[:, 1:k + 1]
        self.nbmask = np.zeros((self.M, self.M), dtype=bool)
        for c in range(self.M):
            self.nbmask[c, self.nb[c]] = True
        self.draw_heterogeneity(P, het_seed)

    def draw_heterogeneity(self, P, seed):
        """Draw the blockage-prone set, the hotspot set, the background loads and the field."""
        rng = np.random.default_rng(seed)
        M = self.M
        n_blk = max(1, int(round(P.blk_frac * M)))
        n_hot = max(1, int(round(P.hot_frac * M)))
        self.blk = np.zeros(M, dtype=bool)
        self.blk[rng.choice(M, n_blk, replace=False)] = True
        self.hot = np.zeros(M, dtype=bool)
        self.hot[rng.choice(M, n_hot, replace=False)] = True
        self.sig_mult = np.where(self.blk, P.blk_mult, 1.0)
        self.bg = np.where(self.hot, rng.uniform(*P.bg_hot, M), rng.uniform(*P.bg_norm, M))
        self.field = None
        if P.shadow_mode == "spatial":
            self._draw_field(P, rng)

    def _draw_field(self, P, rng):
        """Static, spatially correlated shadowing field per cell (1/e correlation at
        d_corr, inter-site correlation xcorr), sampled on a regular grid."""
        from scipy.ndimage import gaussian_filter
        res = P.grid_res
        if self.route is not None:                  # only a corridor around the route is ever visited
            x0, x1 = self.route[:, 0].min() - 60, self.route[:, 0].max() + 60
            y0, y1 = self.route[:, 1].min() - 60, self.route[:, 1].max() + 60
            res = max(res, np.sqrt((x1 - x0) * (y1 - y0) / 4e6))
        else:
            x0, x1, y0, y1 = self.xmin - 20, self.xmax + 20, self.ymin - 20, self.ymax + 20
        nx, ny = int((x1 - x0) / res) + 2, int((y1 - y0) / res) + 2
        sf = (P.d_corr / 2.0) / res                 # Gaussian kernel std -> correlation exp(-(d/d_corr)^2)

        def one():
            g = gaussian_filter(rng.standard_normal((ny, nx)).astype(np.float32), sf, mode="wrap")
            return g / g.std()
        common = one()
        ca, cb = np.sqrt(P.xcorr), np.sqrt(1 - P.xcorr)
        self.field = np.stack([(ca * common + cb * one()) * (P.shadow_sigma * self.sig_mult[k]) for k in range(self.M)]).astype(np.float32)
        self.fx0, self.fy0, self.fres, self.fnx, self.fny = x0, y0, res, nx, ny

    def shadow_at(self, x, y):
        """Bilinear lookup of the static field -> (U, M)."""
        gx = np.clip((x - self.fx0) / self.fres, 0, self.fnx - 1.001); gy = np.clip((y - self.fy0) / self.fres, 0, self.fny - 1.001)
        ix, iy = gx.astype(int), gy.astype(int); tx, ty = (gx - ix), (gy - iy)
        f = self.field
        v = (f[:, iy, ix] * (1 - tx) * (1 - ty) + f[:, iy, ix + 1] * tx * (1 - ty)
             + f[:, iy + 1, ix] * (1 - tx) * ty + f[:, iy + 1, ix + 1] * tx * ty)
        return v.T

    def map_rsrp(self, x, y):
        """Path-loss (radio-map) RSRP of every cell at points x,y -> (...,M)."""
        dx = np.asarray(x)[..., None] - self.pos[:, 0]
        dy = np.asarray(y)[..., None] - self.pos[:, 1]
        d2 = np.maximum(dx * dx + dy * dy, 1.0)
        return self.A - 5.0 * self.n * np.log10(d2)


# ----------------------------------------------------------------------------
# mobility (vectorised over users)
# ----------------------------------------------------------------------------
def gen_traj(env, prof, U, S, dt, rng):
    """Trajectories of U users over S steps for mobility profile `prof`.

    Returns x, y, v, th (position [m], speed [m/s], heading [rad]), each of shape
    (S, U).  If the environment carries a measured route, the users follow it."""
    m = 30.0
    x0, x1, y0, y1 = env.xmin + m, env.xmax - m, env.ymin + m, env.ymax - m
    X = np.empty((S, U)); Y = np.empty((S, U)); V = np.empty((S, U)); TH = np.empty((S, U))
    if env.route is not None:                       # trace-driven: follow the measured route
        R = env.route
        seg = np.hypot(np.diff(R[:, 0]), np.diff(R[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        L = cum[-1]
        s = rng.uniform(0, L, U)
        dirn = rng.choice([-1.0, 1.0], U)
        v = rng.uniform(prof.v_min, prof.v_max, U)
        off = rng.normal(0, 4.0, (U, 2))
        for k in range(S):
            px = np.interp(s, cum, R[:, 0]); py = np.interp(s, cum, R[:, 1])
            s2 = np.clip(s + dirn * 5.0, 0, L)
            qx = np.interp(s2, cum, R[:, 0]); qy = np.interp(s2, cum, R[:, 1])
            X[k] = px + off[:, 0]; Y[k] = py + off[:, 1]; V[k] = v
            TH[k] = np.arctan2(qy - py, qx - px)
            s = s + dirn * v * dt
            hit = (s <= 0) | (s >= L)
            dirn = np.where(hit, -dirn, dirn)
            s = np.clip(s, 0, L)
        return X, Y, V, TH
    if prof.model == "grid":                        # Manhattan-style street grid, block = 150 m
        blk = 150.0
        gx = np.arange(x0, x1 + 1e-6, blk); gy = np.arange(y0, y1 + 1e-6, blk)
        horiz = rng.random(U) < 0.5                  # on an east-west street?
        px = np.where(horiz, rng.uniform(x0, x1, U), rng.choice(gx, U))
        py = np.where(horiz, rng.choice(gy, U), rng.uniform(y0, y1, U))
        d = np.where(horiz, rng.choice([0, 2], U), rng.choice([1, 3], U))    # 0:E 1:N 2:W 3:S
        v = rng.uniform(prof.v_min, prof.v_max, U)
        lane = rng.normal(0, 2.0, U)                 # lateral offset inside the street
        DX = np.array([1.0, 0.0, -1.0, 0.0]); DY = np.array([0.0, 1.0, 0.0, -1.0])
        nxt = np.where(DX[d] != 0, np.where(DX[d] > 0, np.ceil((px - x0) / blk + 1e-9) * blk + x0, np.floor((px - x0) / blk - 1e-9) * blk + x0),
                       np.where(DY[d] > 0, np.ceil((py - y0) / blk + 1e-9) * blk + y0, np.floor((py - y0) / blk - 1e-9) * blk + y0))
        for k in range(S):
            X[k] = px + np.where(DX[d] == 0, lane, 0.0); Y[k] = py + np.where(DY[d] == 0, lane, 0.0)
            V[k] = v; TH[k] = np.arctan2(DY[d], DX[d])
            px = px + v * DX[d] * dt; py = py + v * DY[d] * dt
            pos = np.where(DX[d] != 0, px, py)
            hit = np.where((DX[d] + DY[d]) > 0, pos >= nxt, pos <= nxt)
            if hit.any():
                i = np.where(hit)[0]
                px[i] = np.where(DX[d[i]] != 0, nxt[i], px[i]); py[i] = np.where(DY[d[i]] != 0, nxt[i], py[i])
                u = rng.random(len(i))
                turn = np.where(u < 0.5, 0, np.where(u < 0.75, 1, 3))        # straight 50 %, left/right 25 % each
                nd = (d[i] + turn) % 4
                # stay inside the area: reverse/turn away at the boundary
                for _ in range(4):
                    tx_ = px[i] + DX[nd] * blk; ty_ = py[i] + DY[nd] * blk
                    bad = (tx_ < x0 - 1) | (tx_ > x1 + 1) | (ty_ < y0 - 1) | (ty_ > y1 + 1)
                    if not bad.any():
                        break
                    nd = np.where(bad, (nd + 1) % 4, nd)
                d[i] = nd
                nxt[i] = np.where(DX[nd] != 0, px[i] + DX[nd] * blk, py[i] + DY[nd] * blk)
                v[i] = np.clip(v[i] + rng.normal(0, 1.0, len(i)), prof.v_min, prof.v_max)
        return X, Y, V, TH
    if prof.model == "rwp":
        px = rng.uniform(x0, x1, U); py = rng.uniform(y0, y1, U)
        tx = rng.uniform(x0, x1, U); ty = rng.uniform(y0, y1, U)
        v = rng.uniform(prof.v_min, prof.v_max, U)
        for k in range(S):
            dx, dy = tx - px, ty - py
            dist = np.hypot(dx, dy)
            arr = dist < v * dt
            if arr.any():
                n = int(arr.sum())
                tx[arr] = rng.uniform(x0, x1, n); ty[arr] = rng.uniform(y0, y1, n)
                v[arr] = rng.uniform(prof.v_min, prof.v_max, n)
                dx, dy = tx - px, ty - py
            th = np.arctan2(dy, dx)
            X[k] = px; Y[k] = py; V[k] = v; TH[k] = th
            px = np.clip(px + v * np.cos(th) * dt, x0, x1)
            py = np.clip(py + v * np.sin(th) * dt, y0, y1)
        return X, Y, V, TH
    # linear track: highway lanes or one shared railway line
    Lx, span = x1 - x0, y1 - y0
    if prof.group:
        ytr = rng.uniform(y0 + 0.25 * span, y1 - 0.25 * span)
        py = ytr + rng.normal(0, 3.0, U)
        px = x0 + rng.uniform(0, min(0.06 * Lx, 250.0), U)
        v = np.full(U, rng.uniform(prof.v_min, prof.v_max))
        th = np.zeros(U)
    else:
        lanes = y0 + span * (np.arange(3) + 1) / 4.0
        py = lanes[np.arange(U) % 3] + rng.normal(0, 6.0, U)
        px = rng.uniform(x0, x1, U)
        v = rng.uniform(prof.v_min, prof.v_max, U)
        th = np.where(np.arange(U) % 2 == 0, 0.0, np.pi)
    for k in range(S):
        X[k] = px; Y[k] = np.clip(py, y0, y1); V[k] = v; TH[k] = th
        px = px + v * np.cos(th) * dt
        py = py + rng.normal(0, 0.1, U)
        hit = (px > x1) | (px < x0)                 # reverse at the boundary (no teleport)
        th = np.where(hit, np.pi - th, th)
        px = np.clip(px, x0, x1)
    return X, Y, V, TH


def assign_services(U, rng):
    """Random service index per user, drawn according to the population shares."""
    p = SVC_SHARE / SVC_SHARE.sum()
    return rng.choice(len(SERVICES), size=U, p=p)


# ----------------------------------------------------------------------------
# simulation
# ----------------------------------------------------------------------------
OUT_USEFUL, OUT_UNNEC, OUT_FAIL = 0, 1, 2     # observable outcome labels passed to on_outcome


def simulate(env, pol, traj, svc, P, seed=0, switch_at=None, curve_bin=None):
    """Run one decision rule `pol` on one scenario.  Returns a dict of metrics.

    env:       RadioEnv
    traj:      (x, y, v, th) arrays of shape (S, U), see gen_traj
    svc:       service index per user, see assign_services
    P:         SimParams
    seed:      seed of the shadowing / measurement-error random stream
    switch_at: if given, the hotspot/blockage sets are re-drawn at that time
               (non-stationarity experiment).
    curve_bin: if given [s], also returns time-binned HO / unnecessary / failed
               counts under the key "curve".
    """
    X, Y, V, TH = traj
    S, U = X.shape
    M = env.M
    dt = P.dt
    rng = np.random.default_rng(seed)
    ar = np.arange(U)
    tmin_u = SVC_TMIN[svc] * P.tmin_scale
    thq_u = SVC_THQ[svc] * P.thq_scale
    rate_u = SVC_RATE[svc] * 1e6
    gbr_u = SVC_GBR[svc]
    noise = 10 ** (P.noise_dbm / 10)

    sig = P.shadow_sigma * env.sig_mult
    bg = env.bg.copy()
    ca, cb = np.sqrt(P.xcorr), np.sqrt(1 - P.xcorr)

    def draw():                                    # common (per-user) + site-specific part
        return (ca * rng.normal(size=(U, 1)) + cb * rng.normal(size=(U, M))) * sig

    spatial = env.field is not None
    if spatial:
        sig_t = P.sigma_t * env.sig_mult
        r_t = np.exp(-dt / P.tau_t); c_t = np.sqrt(1 - r_t * r_t)
        sht = rng.normal(size=(U, M)) * sig_t
        sh = env.shadow_at(X[0], Y[0]) + sht
    else:
        sh = draw()
    rsrp = env.map_rsrp(X[0], Y[0]) + sh
    meas = rsrp.copy()
    serv = np.argmax(meas, axis=1)
    rho = bg.copy()

    n310 = np.zeros(U); reest = np.zeros(U)
    last_ho = np.full(U, -1e9); prev = np.full(U, -1)
    # pending event per user
    ea = np.zeros(U, dtype=bool); et0 = np.zeros(U); esrc = np.zeros(U, dtype=int)
    etg = np.zeros(U, dtype=int); es_t = np.zeros(U); es_s = np.zeros(U); en = np.zeros(U)
    ecf = np.zeros(U); ecff = np.zeros(U, dtype=bool)       # counterfactual source RLF (truth)
    em = np.zeros(U); emcf = np.zeros(U); emcff = np.zeros(U, dtype=bool)   # observable proxies
    epp = np.zeros(U, dtype=bool); efj = np.zeros(U); epre = np.zeros(U); er_t = np.zeros(U)

    C = dict(HO=0, cls=0, un=0, fail=0, pp=0, rlf=0, hof_late=0, cens=0,
             c_pp=0, c_short=0, c_gain=0, d_noguard=0, d_and=0, d_dwell=0, d_legacy=0,
             rescue=0, dwell_sum=0.0)
    svcC = np.zeros((len(SERVICES), 2))
    thr_sum = np.zeros(U); dem_sum = np.zeros(U); out_steps = np.zeros(U)
    sinr_sum = 0.0; rsrp_sum = 0.0; nstep = 0; int_time = 0.0
    load_sum = np.zeros(M); sat_steps = 0
    nb_bins = int(np.ceil(P.T_sim / curve_bin)) if curve_bin else 0
    curve = np.zeros((nb_bins, 3)) if curve_bin else None
    t_dec = 0.0

    pol.reset_run(U, env, P, traj)

    def finalize(idx, t, reason):
        """reason: 'ho' (left by a new handover), 'win' (window complete),
        'rlf' (radio-link failure in the target), 'end' (censored)."""
        if len(idx) == 0:
            return
        dwell = t - et0[idx]
        n = np.maximum(en[idx], 1)
        gain = (es_t[idx] - es_s[idx]) / n
        mgain = em[idx] / n
        short = dwell < tmin_u[idx] - 1e-9
        low = gain < thq_u[idx]
        failed = np.full(len(idx), reason == "rlf")
        if reason == "end":
            keep = ~short
            C["cens"] += int((~keep).sum())
            idx, dwell, gain, mgain, short, low, failed, n = (a[keep] for a in
                                                              (idx, dwell, gain, mgain, short, low, failed, n))
            if len(idx) == 0:
                return
        resc = ecff[idx]
        un = (~failed) & (~resc) & (short | low)
        C["cls"] += len(idx); C["un"] += int(un.sum()); C["fail"] += int(failed.sum())
        C["rescue"] += int((resc & ~failed & (short | low)).sum())
        C["dwell_sum"] += float(dwell.sum())
        pp = epp[idx] & un
        C["c_pp"] += int(pp.sum())
        C["c_short"] += int((un & short & ~pp).sum())
        C["c_gain"] += int((un & ~short & ~pp).sum())
        # alternative definitions (robustness of the ranking to the metric)
        ok = ~failed
        C["d_noguard"] += int((ok & (short | low)).sum())
        C["d_and"] += int((ok & ~resc & short & low).sum())
        C["d_dwell"] += int((ok & short).sum())
        gain_pre = er_t[idx] / n - epre[idx]
        C["d_legacy"] += int((short | (gain_pre < thq_u[idx]) | (efj[idx] < P.theta_delta) | epp[idx]).sum())
        np.add.at(svcC[:, 0], svc[idx], 1); np.add.at(svcC[:, 1], svc[idx], un)
        if curve is not None:
            b = np.minimum((et0[idx] / curve_bin).astype(int), nb_bins - 1)
            np.add.at(curve[:, 0], b, 1); np.add.at(curve[:, 1], b, un); np.add.at(curve[:, 2], b, failed)
        # label visible to the network (no ground-truth SINR, no load knowledge)
        un_obs = (~failed) & (~emcff[idx]) & (short | (mgain < thq_u[idx]))
        out = np.where(failed, OUT_FAIL, np.where(un_obs, OUT_UNNEC, OUT_USEFUL))
        pol.on_outcome(esrc[idx], etg[idx], out, idx, dwell, t)
        ea[idx] = False

    for k in range(S):
        t = k * dt
        if switch_at is not None and abs(t - switch_at) < dt / 2:
            env.draw_heterogeneity(P, seed=7919 + seed)
            sig = P.shadow_sigma * env.sig_mult
            bg = env.bg.copy()
            if spatial:
                sig_t = P.sigma_t * env.sig_mult
        x, y, v, th = X[k], Y[k], V[k], TH[k]
        if spatial:
            sht = r_t * sht + c_t * rng.normal(size=(U, M)) * sig_t
            sh = env.shadow_at(x, y) + sht
        else:
            r = np.exp(-v * dt / P.d_corr)
            sh = r[:, None] * sh + np.sqrt(1 - r * r)[:, None] * draw()
        rsrp = env.map_rsrp(x, y) + sh
        lin = 10 ** (rsrp / 10)
        tot = P.chi * (lin @ rho) + noise
        sinr_all = 10 * np.log10(lin / np.maximum(tot[:, None] - P.chi * rho[None, :] * lin, noise))
        meas = (1 - P.l3_a) * meas + P.l3_a * rsrp
        sinr_s = sinr_all[ar, serv]

        active = reest <= 0
        reest = np.maximum(reest - dt, 0)

        # ---- radio-link failure (Qout for T310) ----
        n310 = np.where(active & (sinr_s < P.Qout), n310 + dt, 0.0)
        rl = np.where(n310 >= P.T310)[0]
        if len(rl):
            C["rlf"] += len(rl)
            finalize(rl[ea[rl]], t, "rlf")
            lt = rl[~ea[rl]]                           # RLF with no recent handover: too late
            if len(lt):
                mm = np.where(env.nbmask[serv[lt]], meas[lt], -1e9)
                pol.on_late(serv[lt], np.argmax(mm, axis=1), lt, t)
            serv[rl] = np.argmax(meas[rl], axis=1)
            reest[rl] = P.T_reest; n310[rl] = 0; active[rl] = False
            pol.on_reset(rl)

        # ---- accumulate the pending events ----
        ia = np.where(ea)[0]
        if len(ia):
            s_src = sinr_all[ia, esrc[ia]]
            es_t[ia] += sinr_all[ia, etg[ia]]; es_s[ia] += s_src; en[ia] += 1
            er_t[ia] += rsrp[ia, etg[ia]]
            ecf[ia] = np.where(s_src < P.Qout, ecf[ia] + dt, 0.0)
            ecff[ia] |= ecf[ia] >= P.T310
            mm = meas[ia]
            ml = 10 ** (mm / 10)
            msrc = ml[np.arange(len(ia)), esrc[ia]]
            est = 10 * np.log10(msrc / np.maximum(P.chi * (ml.sum(1) - msrc), 1e-30))   # full-load estimate
            emcf[ia] = np.where(est < P.Qout, emcf[ia] + dt, 0.0)
            emcff[ia] |= emcf[ia] >= P.T310
            em[ia] += mm[np.arange(len(ia)), etg[ia]] - mm[np.arange(len(ia)), esrc[ia]]
            done = ia[(t - et0[ia]) >= tmin_u[ia] - 1e-9]
            finalize(done, t, "win")

        # ---- decision ----
        if P.head_err > 0 or P.speed_err > 0:
            th_e = th + rng.normal(0, P.head_err, U) if P.head_err > 0 else th
            v_e = v * (1 + rng.normal(0, P.speed_err, U)) if P.speed_err > 0 else v
        else:
            th_e, v_e = th, v
        ctx = dict(t=t, k=k, meas=meas, serv=serv, x=x, y=y, v=v_e, th=th_e,
                   last_ho=last_ho, svc=svc, rng=rng, active=active)
        tt = time.perf_counter()
        tgt = pol.decide(ctx)
        t_dec += time.perf_counter() - tt
        ho = np.where(active & (tgt >= 0) & (tgt != serv))[0]
        hoflag = np.zeros(U, dtype=bool)
        if len(ho):
            finalize(ho[ea[ho]], t, "ho")
            C["HO"] += len(ho)
            late = sinr_s[ho] < P.Qout                 # command cannot be delivered
            hl = ho[late]
            if len(hl):
                C["hof_late"] += len(hl); C["cls"] += len(hl); C["fail"] += len(hl)
                np.add.at(svcC[:, 0], svc[hl], 1)
                if curve is not None:
                    b = min(int(t / curve_bin), nb_bins - 1)
                    curve[b, 0] += len(hl); curve[b, 2] += len(hl)
                pol.on_late(serv[hl], tgt[hl], hl, t)
                serv[hl] = np.argmax(meas[hl], axis=1)
                reest[hl] = P.T_reest; n310[hl] = 0; active[hl] = False
                pol.on_reset(hl)
            hg = ho[~late]
            if len(hg):
                j = tgt[hg]
                pp = (prev[hg] == j) & ((t - last_ho[hg]) < P.T_pp)
                C["pp"] += int(pp.sum())
                ea[hg] = True; et0[hg] = t; esrc[hg] = serv[hg]; etg[hg] = j
                es_t[hg] = 0; es_s[hg] = 0; en[hg] = 0; ecf[hg] = 0; ecff[hg] = False
                em[hg] = 0; emcf[hg] = 0; emcff[hg] = False; epp[hg] = pp; er_t[hg] = 0
                epre[hg] = rsrp[hg, serv[hg]]
                efj[hg] = area_frac(env, x[hg], y[hg], v[hg], th[hg], 5.0, 0.6)[np.arange(len(hg)), j]
                prev[hg] = serv[hg]; serv[hg] = j; last_ho[hg] = t; n310[hg] = 0
                hoflag[hg] = True
                int_time += len(hg) * P.T_int

        # ---- load, scheduling, throughput ----
        sinr_s = sinr_all[ar, serv]
        conn = active & (sinr_s >= P.Qout)
        se = np.minimum(np.log2(1 + 10 ** (sinr_s / 10)), P.se_max)
        need = np.where(conn, rate_u / (P.W_hz * np.maximum(se, 1e-3)), 0.0)
        G = np.bincount(serv, weights=need * gbr_u, minlength=M)
        B = np.bincount(serv, weights=need * (~gbr_u), minlength=M)
        free = np.maximum(1 - bg, 0.0)
        gs = np.minimum(1.0, free / np.maximum(G, 1e-12))
        rem = np.maximum(free - G * gs, 0.0)
        bs = np.minimum(1.0, rem / np.maximum(B, 1e-12))
        scale = np.where(gbr_u, gs[serv], bs[serv])
        thr = np.where(conn, rate_u * scale, 0.0)
        thr = np.where(hoflag, thr * (1 - P.T_int / dt), thr)
        rho_new = np.minimum(1.0, bg + G * gs + B * bs)
        rho = P.rho_smooth * rho + (1 - P.rho_smooth) * rho_new
        thr_sum += thr; dem_sum += rate_u; out_steps += ~conn
        sinr_sum += float(sinr_s.sum())
        rsrp_sum += float(rsrp[ar, serv].sum()); nstep += 1
        load_sum += rho_new; sat_steps += int((bg + G + B > 1.0).sum())
        pol.after_step(ctx, sinr_s, hoflag)

    finalize(np.where(ea)[0], S * dt, "end")

    umin = U * S * dt / 60.0
    cls = max(C["cls"], 1)
    sat = thr_sum / np.maximum(dem_sum, 1e-9)
    res = {
        "policy": pol.name, "users": U,
        "HO": C["HO"], "classified": C["cls"], "unnecessary": C["un"], "failed": C["fail"],
        "HO_pm": C["HO"] / umin,                       # handovers per user per minute
        "UHO_pm": C["un"] / umin,                      # unnecessary handovers per user per minute
        "UHR": C["un"] / cls,
        "HOF_rate": C["fail"] / cls,
        "RLF_pm": C["rlf"] / umin,
        "fail_pm": (C["rlf"] + C["hof_late"]) / umin,   # mobility failures per user-minute
        "PP_rate": C["pp"] / max(C["HO"], 1),
        "outage_pct": 100 * out_steps.sum() / (U * S),
        "interrupt_pct": 100 * int_time / (U * S * dt),
        "thr_mbps": thr_sum.sum() / (U * S) / 1e6,
        "satisf": float(sat.mean()),
        "satisf_p5": float(np.percentile(sat, 5)),
        "sinr_db": sinr_sum / (U * S),
        "rsrp_dbm": rsrp_sum / (U * S),
        "sig_pm": 9 * C["HO"] / umin + 6 * (C["rlf"] + C["hof_late"]) / umin,
        "dwell_s": C["dwell_sum"] / cls,
        "mean_load": float((load_sum / S).mean()),
        "sat_cell_pct": 100 * sat_steps / (S * M),
        "c_pp": C["c_pp"], "c_short": C["c_short"], "c_gain": C["c_gain"],
        "UHR_noguard": C["d_noguard"] / cls, "UHR_and": C["d_and"] / cls,
        "UHR_dwell": C["d_dwell"] / cls, "UHR_legacy": C["d_legacy"] / cls,
        "rescue": C["rescue"], "censored": C["cens"],
        "dec_us": 1e6 * t_dec / (U * S),
    }
    for i, kk in enumerate(SVC_KEYS):
        res[f"UHR_{kk}"] = svcC[i, 1] / svcC[i, 0] if svcC[i, 0] else float("nan")
        res[f"HOn_{kk}"] = int(svcC[i, 0])
        res[f"sat_{kk}"] = float(sat[svc == i].mean()) if (svc == i).any() else float("nan")
    if curve is not None:
        res["curve"] = curve
    return res


# ----------------------------------------------------------------------------
# path-overlap (area fraction) of the short-term motion region
# ----------------------------------------------------------------------------
_RR = np.sqrt((np.arange(6) + 0.5) / 6.0)          # 6 radii (equal-area rings)
_AA = (np.arange(8) + 0.5) / 8.0 * 2 - 1           # 8 angles in (-1, 1)
_R, _A = (g.ravel() for g in np.meshgrid(_RR, _AA))


def area_frac(env, x, y, v, th, T_p, half_angle, r_min=10.0):
    """Share of the predicted-motion sector that lies in the best-server region
    of each cell.  Deterministic 48-point quadrature.  Returns (n, M)."""
    R = np.maximum(v * T_p, r_min)[:, None] * _R[None, :]
    ang = th[:, None] + half_angle * _A[None, :]
    best = np.argmax(env.map_rsrp(x[:, None] + R * np.cos(ang), y[:, None] + R * np.sin(ang)), axis=2)
    out = np.zeros((len(x), env.M))
    np.add.at(out, (np.repeat(np.arange(len(x)), best.shape[1]), best.ravel()), 1.0 / best.shape[1])
    return out
