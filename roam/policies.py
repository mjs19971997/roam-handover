# -*- coding: utf-8 -*-
"""Vectorised handover decision rules: ROAM and the baselines.

Every policy sees the same information: L3-filtered RSRP of the serving cell and
its neighbours, the UE position/velocity estimate, the service class, and the
outcome events the network can observe.  All of them act through the same
Event-A3 style machinery (entering condition + time-to-trigger timer) so that the
only thing that differs between policies is the decision logic itself.

The baselines are re-implementations "in the spirit of" the cited schemes on this
common interface; see the paper for the full references.
"""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from .simulator import SVC_W, SVC_TMIN, area_frac, OUT_FAIL

NEG = -1e9


# ----------------------------------------------------------------------------
# base layer of the framework: K-means + PCA + decision tree  ->  a_init
# ----------------------------------------------------------------------------
class BaseLayer:
    """Position/velocity profile -> preliminary target cell a_init (PBPHS-style).

    K-means groups the cells (k = round(sqrt(M))); the user profile
    [x, y, v, cos(theta), sin(theta), distance to each cluster centre] is
    standardised, reduced by PCA (95 % retained variance) and classified by a
    depth-12 decision tree whose label is the best-server cell of the radio map.
    """

    def __init__(self, env, seed=7, n_train=4000, depth=12, var=0.95):
        self.env = env
        rng = np.random.default_rng(seed)
        self.k = max(2, int(round(np.sqrt(env.M))))
        self.km = KMeans(n_clusters=self.k, n_init=5, random_state=seed).fit(env.pos)
        n_all = n_train + 1000
        if env.route is not None:
            i = rng.integers(0, len(env.route), n_all)
            x = env.route[i, 0] + rng.normal(0, 15, n_all); y = env.route[i, 1] + rng.normal(0, 15, n_all)
        else:
            x = rng.uniform(env.xmin, env.xmax, n_all); y = rng.uniform(env.ymin, env.ymax, n_all)
        v = rng.uniform(0.5, 60.0, n_all); th = rng.uniform(-np.pi, np.pi, n_all)
        F = self._feat(x, y, v, th)
        lab = np.argmax(env.map_rsrp(x, y), axis=1)
        self.sc = StandardScaler().fit(F[:n_train])
        self.pca = PCA(n_components=var, svd_solver="full").fit(self.sc.transform(F[:n_train]))
        Z = self.pca.transform(self.sc.transform(F))
        self.tree = DecisionTreeClassifier(max_depth=depth, random_state=seed).fit(Z[:n_train], lab[:n_train])
        self.acc = float((self.tree.predict(Z[n_train:]) == lab[n_train:]).mean())
        self.n_comp = int(self.pca.n_components_)
        self.n_feat = F.shape[1]; self.depth = depth; self.n_train = n_train

    def _feat(self, x, y, v, th):
        cc = self.km.cluster_centers_
        d = np.hypot(cc[None, :, 0] - x[:, None], cc[None, :, 1] - y[:, None])
        return np.concatenate([np.stack([x, y, v, np.cos(th), np.sin(th)], 1), d], 1)

    def predict(self, X, Y, V, TH):
        """a_init for every entry of the (equally shaped) position/speed/heading arrays."""
        sh = X.shape
        x, y, v, th = X.ravel(), Y.ravel(), V.ravel(), TH.ravel()
        out = np.empty(x.size, dtype=np.int16)
        for i in range(0, x.size, 100000):               # chunked: long runs do not fit in memory at once
            s = slice(i, i + 100000)
            F = self._feat(x[s], y[s], v[s], th[s])
            out[s] = self.tree.predict(self.pca.transform(self.sc.transform(F)))
        return out.astype(int).reshape(sh)


# ----------------------------------------------------------------------------
# route-level outcome table
# ----------------------------------------------------------------------------
class RouteTable:
    """Outcome memory per route: counts of mutually exclusive outcomes per directed route c->j.

    N[c, j, 0|1|2|3] = useful | unnecessary | failed after execution (too early /
    wrong cell) | too late (link lost in c before the handover to j completed).
    Counts are discounted with a time constant tau_f, so old evidence fades and a
    blocked route relaxes back to the prior (which lets it be tried again).
    """

    def __init__(self, M, alpha=0.6, beta=1.0, tau_f=None):
        self.N = np.zeros((M, M, 4)); self.alpha = alpha; self.beta = beta; self.tau_f = tau_f

    def risk(self):
        """H = alpha * P_un + (1 - alpha) * P_fail  (premature-handover risk)."""
        n = self.N.sum(2) + 4 * self.beta
        return (self.alpha * (self.N[..., 1] + self.beta) + (1 - self.alpha) * (self.N[..., 2] + self.beta)) / n

    def late(self):
        """L = P_late  (lateness evidence)."""
        return (self.N[..., 3] + self.beta) / (self.N.sum(2) + 4 * self.beta)

    def decay(self, dt):
        """Discount all counts by exp(-dt / tau_f)."""
        if self.tau_f:
            self.N *= np.exp(-dt / self.tau_f)

    def update(self, src, tgt, out):
        """Add one observation of outcome `out` to every route src -> tgt."""
        np.add.at(self.N, (src, tgt, out), 1.0)

    def n_routes(self):
        """Number of routes with at least one recorded outcome."""
        return int((self.N.sum(2) > 0).sum())


# ----------------------------------------------------------------------------
class LocationTable(RouteTable):
    """Location-aware extension: counts are additionally kept per (location bin, target
    cell); the bin estimate is shrunk towards the route-level estimate with kappa
    pseudo-observations, so a bin with no history behaves exactly like the route."""

    def __init__(self, M, env, res=40.0, kappa=3.0, **kw):
        super().__init__(M, **kw)
        self.res, self.kappa = res, kappa
        self.x0, self.y0 = env.xmin - 50.0, env.ymin - 50.0
        self.nx = int((env.xmax - env.xmin + 100.0) / res) + 1
        self.ny = int((env.ymax - env.ymin + 100.0) / res) + 1
        self.NL = np.zeros((self.nx * self.ny, M, 4), dtype=np.float32)

    def bins(self, x, y):
        """Index of the location bin (square of side `res`) of every position."""
        ix = np.clip(((x - self.x0) / self.res).astype(int), 0, self.nx - 1)
        iy = np.clip(((y - self.y0) / self.res).astype(int), 0, self.ny - 1)
        return iy * self.nx + ix

    def scores(self, serv, b):
        """(H, L) for every user (rows) and target cell (columns)."""
        nr = self.N[serv] + self.beta                         # (U, M, 4) route counts + prior
        pr = nr / nr.sum(2, keepdims=True)
        n = self.NL[b] + self.kappa * pr
        p = n / n.sum(2, keepdims=True)
        return self.alpha * p[..., 1] + (1 - self.alpha) * p[..., 2], p[..., 3]

    def decay(self, dt):
        if self.tau_f:                               # applied once per second (cheap, same result)
            self._acc = getattr(self, "_acc", 0.0) + dt
            if self._acc >= 1.0 - 1e-9:
                f = np.exp(-self._acc / self.tau_f); self.N *= f; self.NL *= f; self._acc = 0.0

    def update_loc(self, b, tgt, out):
        """Add one observation of outcome `out` to every (location bin, target) pair."""
        np.add.at(self.NL, (b, tgt, out), 1.0)


# ----------------------------------------------------------------------------
# decision rules
# ----------------------------------------------------------------------------
class Base:
    """Interface between the simulator and a decision rule.

    A rule implements decide(ctx) and may override the hooks below.  ctx is a dict
    with the keys t [s], k (step index), meas (U,M) L3-filtered RSRP [dBm],
    serv (U,) serving cell, x, y [m], v [m/s], th [rad] (motion estimate),
    last_ho (U,) time of the last handover, svc (U,) service index, rng (the
    run's random generator) and active (U,) False while a user re-establishes.
    decide returns an integer array (U,): the target cell, or -1 to stay.
    """
    name = "base"

    def reset_run(self, U, env, P, traj=None):
        """Called once before a run; allocates the per-user, per-neighbour TTT timers."""
        self.U, self.env, self.P = U, env, P
        self.ar = np.arange(U)
        self.timer = np.zeros((U, env.M))
        self.last_serv = np.full(U, -1)

    def decide(self, ctx):
        """Target cell per user, or -1 to stay."""
        raise NotImplementedError

    def on_outcome(self, src, tgt, out, uidx, dwell, t):
        """Observable outcome (OUT_USEFUL / OUT_UNNEC / OUT_FAIL) of executed handovers
        src -> tgt of users uidx, with their dwell time in the target."""

    def on_late(self, src, tgt, uidx, t):
        """Too-late events: the link of users uidx was lost in src (tgt = intended or
        strongest neighbour)."""

    def on_reset(self, idx):
        """Users idx went through a radio-link failure: clear their timers."""
        self.timer[idx] = 0

    def after_step(self, ctx, sinr_s, hoflag):
        """Called at the end of every step with the serving SINR and the flags of the
        users that executed a handover in this step."""

    def _gap(self, ctx):
        """Measured RSRP of every cell minus that of the serving cell -> (U, M)."""
        meas, serv = ctx["meas"], ctx["serv"]
        return meas - meas[self.ar, serv][:, None]

    def _a3(self, ctx, gap, margin, ttt, by_score=False):
        """Entering condition gap > margin held for ttt; returns target or -1."""
        serv = ctx["serv"]
        ch = serv != self.last_serv
        if ch.any():
            self.timer[ch] = 0
        self.last_serv = serv.copy()
        cond = self.env.nbmask[serv] & (gap > margin)
        self.timer = np.where(cond, self.timer + self.P.dt, 0.0)
        ready = self.timer >= ttt - 1e-9
        self.ready = ready
        score = np.where(ready, (gap - margin) if by_score else gap, NEG)
        tgt = np.argmax(score, axis=1)
        tgt[~ready.any(axis=1)] = -1
        return tgt


class A3(Base):
    """3GPP Event A3: neighbour better than serving by a hysteresis for TTT."""

    def __init__(self, hyst=3.0, ttt=0.3, name="A3"):
        self.hyst, self.ttt, self.name = hyst, ttt, name

    def decide(self, ctx):
        return self._a3(ctx, self._gap(ctx), self.hyst, self.ttt)


class ROAM(Base):
    """Event A3 whose margin adapts per user and per neighbour: outcome memory
    (route / location table), path overlap and service weight.

    margin_ij = h0 + eta_H*H - eta_L*L + eta_S*w_s - eta_A*gamma_i*(f_j - f_c) - eps*[j = a_init],
    clipped to [m_floor, m_cap]; H, L are the premature-handover risk and the
    lateness evidence of the table, f the path-overlap shares (area_frac) and
    gamma the confidence in the motion prediction.

    fw is the BaseLayer that supplies a_init.  The use_* switches turn single
    terms off (ablation); loc_res=None keeps the route-level table only;
    freeze stops the table from learning; persist keeps it across runs.
    The default name "Proposed" is the method label used in the result files.
    """

    def __init__(self, fw, h0=2.0, ttt=0.3, eta_H=6.0, eta_L=0.0, eta_A=4.0, eta_S=4.0, eps=0.5,
                 T_hold=1.0, alpha=0.6, beta=1.0, tau_f=600.0, T_p=5.0, half=0.6,
                 kappa=1.0, m_floor=0.0, m_cap=6.0, use_hht=True, use_area=True, use_svc=True,
                 use_init=True, use_hold=True, persist=False, freeze=False, name="Proposed",
                 loc_res=40.0, loc_kappa=3.0):
        self.fw = fw
        self.h0, self.ttt, self.eta_H, self.eta_A, self.eta_S, self.eps = h0, ttt, eta_H, eta_A, eta_S, eps
        self.T_hold, self.alpha, self.beta, self.tau_f = T_hold, alpha, beta, tau_f
        self.T_p, self.half, self.kappa, self.m_floor = T_p, half, kappa, m_floor
        self.m_cap = m_cap
        self.eta_L = eta_L
        self.loc_res, self.loc_kappa = loc_res, loc_kappa
        self.use_hht, self.use_area, self.use_svc = use_hht, use_area, use_svc
        self.use_init, self.use_hold = use_init, use_hold
        self.persist, self.freeze, self.name = persist, freeze, name
        self.hht = None

    def reset_run(self, U, env, P, traj=None):
        super().reset_run(U, env, P, traj)
        if self.hht is None or not self.persist:
            if self.loc_res:
                self.hht = LocationTable(env.M, env, res=self.loc_res, kappa=self.loc_kappa, alpha=self.alpha, beta=self.beta, tau_f=self.tau_f)
            else:
                self.hht = RouteTable(env.M, self.alpha, self.beta, self.tau_f)
        self.bin_now = np.zeros(U, dtype=int); self.bin_ev = np.zeros(U, dtype=int)
        self._HL = None
        self.a_init = self.fw.predict(*traj) if (self.use_init and traj is not None) else None
        self.hrate = np.zeros(U); self.th_prev = None
        self.f_c = np.zeros((U, env.M)); self.f_t = np.full(U, -1e9); self.refresh = 0.3

    def decide(self, ctx):
        env = self.env
        serv, svc, th = ctx["serv"], ctx["svc"], ctx["th"]
        gap = self._gap(ctx)
        # confidence in the motion prediction: drops after a turn, recovers within ~T_p
        if self.th_prev is not None:
            d = np.abs(np.angle(np.exp(1j * (th - self.th_prev))))
            self.hrate = 0.9 * self.hrate + 0.1 * d / self.P.dt
        self.th_prev = th.copy()
        gamma = 1.0 / (1.0 + self.kappa * self.hrate * self.T_p)

        margin = np.full(gap.shape, float(self.h0))
        low = self.h0
        if self.use_hht:
            if self.loc_res:
                self.bin_now = self.hht.bins(ctx["x"], ctx["y"])
                if ctx["k"] % 3 == 0 or getattr(self, "_HL", None) is None:     # refreshed every 300 ms
                    self._HL = self.hht.scores(serv, self.bin_now)
                Hs, Ls = self._HL
                margin += self.eta_H * Hs - self.eta_L * Ls
            else:
                margin += self.eta_H * self.hht.risk()[serv]
                if self.eta_L:
                    margin -= self.eta_L * self.hht.late()[serv]
        if self.use_svc:
            ws = self.eta_S * SVC_W[svc]
            margin += ws[:, None]
            low = low + ws
        if self.use_init and self.a_init is not None:
            margin[self.ar, self.a_init[ctx["k"]]] -= self.eps
            low = low - self.eps
        if self.use_area:
            gmax = np.where(env.nbmask[serv], gap, NEG).max(axis=1)
            need = np.where(gmax > np.maximum(low - 2 * self.eta_A * gamma, self.m_floor))[0]
            if len(need):
                # the overlap is refreshed at most every `refresh` seconds per user
                stale = need[(ctx["t"] - self.f_t[need]) >= self.refresh - 1e-9]
                if len(stale):
                    self.f_c[stale] = area_frac(env, ctx["x"][stale], ctx["y"][stale], ctx["v"][stale],
                                                th[stale], self.T_p, self.half)
                    self.f_t[stale] = ctx["t"]
                f = self.f_c[need]
                fc = f[np.arange(len(need)), serv[need]]
                lam = f - fc[:, None]                             # overlap of target j minus that of the serving cell
                margin[need] -= self.eta_A * gamma[need, None] * lam
        margin = np.clip(margin, self.m_floor, self.m_cap)
        tgt = self._a3(ctx, gap, margin, self.ttt, by_score=True)
        if self.use_hold:
            tgt[(ctx["t"] - ctx["last_ho"]) < self.T_hold] = -1
        return tgt

    def on_outcome(self, src, tgt, out, uidx, dwell, t):
        if self.use_hht and not self.freeze:
            self.hht.update(src, tgt, out)
            if self.loc_res:
                self.hht.update_loc(self.bin_ev[uidx], tgt, out)

    def on_late(self, src, tgt, uidx, t):
        if self.use_hht and not self.freeze:
            self.hht.update(src, tgt, 3)
            if self.loc_res:
                self.hht.update_loc(self.bin_now[uidx], tgt, 3)

    def after_step(self, ctx, sinr_s, hoflag):
        if self.use_hht and self.loc_res:
            self.bin_ev = np.where(hoflag, self.bin_now, self.bin_ev)     # where the executed handover was decided
        if self.use_hht and not self.freeze:
            self.hht.decay(self.P.dt)


class PBPHS(Base):
    """Profile-based predictive handover: follow the predicted cell a_init as
    soon as it is measurably better; otherwise fall back to the strongest
    neighbour with an extra bias.  No memory, no timer."""

    def __init__(self, fw, m=1.0, bias=1.5, name="PBPHS"):
        self.fw, self.m, self.bias, self.name = fw, m, bias, name

    def reset_run(self, U, env, P, traj=None):
        super().reset_run(U, env, P, traj)
        self.a_init = self.fw.predict(*traj)

    def decide(self, ctx):
        gap = self._gap(ctx)
        margin = np.full(gap.shape, float(self.m + self.bias))
        margin[self.ar, self.a_init[ctx["k"]]] = self.m
        return self._a3(ctx, gap, margin, 0.0, by_score=True)


class TrajPred(Base):
    """Trajectory-prediction handover in the spirit of LSTM-SVM schemes: the future
    position (horizon T_h) is predicted and the cell with the best predicted
    signal there is chosen, subject to a decision margin on the current gap.
    The predictor is the exact constant-velocity extrapolation, which a trained
    sequence model can at best match on these mobility models."""

    def __init__(self, T_h=3.0, g=1.0, name="Traj-Pred"):
        self.T_h, self.g, self.name = T_h, g, name

    def decide(self, ctx):
        env = self.env
        x, y, v, th, serv, meas = ctx["x"], ctx["y"], ctx["v"], ctx["th"], ctx["serv"], ctx["meas"]
        fut = env.map_rsrp(x + v * np.cos(th) * self.T_h, y + v * np.sin(th) * self.T_h)
        pred = fut + 0.5 * (meas - env.map_rsrp(x, y))
        pgap = pred - pred[self.ar, serv][:, None]
        gap = self._gap(ctx)
        ok = env.nbmask[serv] & (pgap > 0) & (gap > self.g)
        sc = np.where(ok, pgap, NEG)
        tgt = np.argmax(sc, axis=1)
        tgt[~ok.any(axis=1)] = -1
        return tgt


class ToSSkip(Base):
    """Mobility-prediction handover skipping: an A3-triggered
    handover is skipped when the predicted time-of-stay in the target is short,
    unless the serving link is already much weaker (rescue gap)."""

    def __init__(self, hyst=2.0, ttt=0.2, tau=3.0, T_h=10.0, g_rescue=6.0, name="ToS-Skip"):
        self.hyst, self.ttt, self.tau, self.T_h, self.g_rescue, self.name = hyst, ttt, tau, T_h, g_rescue, name

    def decide(self, ctx):
        env = self.env
        gap = self._gap(ctx)
        tgt = self._a3(ctx, gap, self.hyst, self.ttt)
        c = np.where(tgt >= 0)[0]
        if len(c):
            ts = np.arange(1, int(self.T_h) + 1, dtype=float)
            px = ctx["x"][c, None] + ctx["v"][c, None] * np.cos(ctx["th"][c, None]) * ts[None]
            py = ctx["y"][c, None] + ctx["v"][c, None] * np.sin(ctx["th"][c, None]) * ts[None]
            best = np.argmax(env.map_rsrp(px, py), axis=2)
            tos = (best == tgt[c, None]).sum(axis=1).astype(float)
            skip = (tos < self.tau) & (gap[c, tgt[c]] < self.g_rescue)
            tgt[c[skip]] = -1
        return tgt


class MPScreen(Base):
    """Mobility-prediction screening after Wang et al.: neighbours inside a
    screening distance D and a screening angle around the predicted direction of
    travel are "predicted" cells; a stronger cell outside that set is penalised by
    3 x (its level minus the better of the best predicted cell and the serving
    cell) before the usual hysteresis/TTT rule is applied.  The route classifier
    of the original scheme is replaced by the true heading, i.e. a perfect predictor."""

    def __init__(self, hyst=3.0, ttt=0.3, angle=45.0, D=300.0, name="MP-Screen"):
        self.hyst, self.ttt, self.angle, self.D, self.name = hyst, ttt, np.radians(angle), D, name

    def decide(self, ctx):
        env = self.env
        serv, meas = ctx["serv"], ctx["meas"]
        dx = env.pos[None, :, 0] - ctx["x"][:, None]; dy = env.pos[None, :, 1] - ctx["y"][:, None]
        bear = np.arctan2(dy, dx)
        dev = np.abs(np.angle(np.exp(1j * (bear - ctx["th"][:, None]))))
        nb = env.nbmask[serv]
        pred = nb & (dev <= self.angle) & (np.hypot(dx, dy) <= self.D)
        ms = meas[self.ar, serv]
        ref = np.maximum(np.where(pred, meas, NEG).max(axis=1), ms)[:, None]
        pen = np.where(nb & ~pred, 3.0 * np.maximum(meas - ref, 0.0), 0.0)
        gap = (meas - pen) - ms[:, None]
        return self._a3(ctx, gap, self.hyst, self.ttt)


class STCMAB(Base):
    """Space-time contextual bandit target selection in the spirit of Sun et al.:
    context = (serving cell, heading octant), arms = A3-eligible neighbours,
    reward = normalised time-of-stay of the resulting handover, UCB selection."""

    def __init__(self, hyst=2.0, ttt=0.2, cu=0.5, name="ST-CMAB"):
        self.hyst, self.ttt, self.cu, self.name = hyst, ttt, cu, name

    def reset_run(self, U, env, P, traj=None):
        super().reset_run(U, env, P, traj)
        if not (getattr(self, "persist", False) and hasattr(self, "Rs")):
            self.Rs = np.zeros((env.M, 8, env.M)); self.Rn = np.zeros((env.M, 8, env.M))
        self.oct_u = np.zeros(U, dtype=int)

    def decide(self, ctx):
        gap = self._gap(ctx)
        serv = ctx["serv"]
        self._a3(ctx, gap, self.hyst, self.ttt)
        oc = ((ctx["th"] + np.pi) / (2 * np.pi) * 8).astype(int) % 8
        n = self.Rn[serv, oc]
        mean = np.where(n > 0, self.Rs[serv, oc] / np.maximum(n, 1), 0.5)
        ucb = mean + self.cu * np.sqrt(np.log(self.Rn.sum() + 2.0) / (n + 1.0))
        sc = np.where(self.ready, ucb + 1e-3 * gap, NEG)
        tgt = np.argmax(sc, axis=1)
        tgt[~self.ready.any(axis=1)] = -1
        self.oct_u = np.where(tgt >= 0, oc, self.oct_u)
        return tgt

    def on_outcome(self, src, tgt, out, uidx, dwell, t):
        r = np.where(out == OUT_FAIL, 0.0, np.minimum(dwell / SVC_TMIN.max(), 1.0))
        np.add.at(self.Rs, (src, self.oct_u[uidx], tgt), r)
        np.add.at(self.Rn, (src, self.oct_u[uidx], tgt), 1.0)


class ClusterRL(Base):
    """Q-learning handover trigger in the spirit of clustering-RL schemes: state = (gap bin of the
    strongest neighbour, speed bin, recent-handover flag), action = stay / hand
    over to the strongest neighbour; one Q-table shared by all users."""

    def __init__(self, c_ho=1.0, lr=0.1, disc=0.9, eps=0.02, name="Cluster-RL"):
        self.c_ho, self.lr, self.disc, self.eps, self.name = c_ho, lr, disc, eps, name

    def reset_run(self, U, env, P, traj=None):
        super().reset_run(U, env, P, traj)
        if not (getattr(self, "persist", False) and hasattr(self, "Q")):
            self.Q = np.zeros((7, 5, 2, 2)); self.Q[..., 1] = -0.2
        self.s_prev = None

    def _state(self, ctx, gmax):
        gb = np.clip(np.floor(gmax / 2.0).astype(int) + 1, 0, 6)
        vb = np.digitize(ctx["v"], [3.0, 10.0, 20.0, 35.0])
        rb = ((ctx["t"] - ctx["last_ho"]) < 2.0).astype(int)
        return gb, vb, rb

    def decide(self, ctx):
        gap = np.where(self.env.nbmask[ctx["serv"]], self._gap(ctx), NEG)
        best = np.argmax(gap, axis=1); gmax = gap[self.ar, best]
        s = self._state(ctx, gmax)
        q = self.Q[s]
        a = (q[:, 1] > q[:, 0]).astype(int)
        ex = ctx["rng"].random(self.U) < self.eps
        a = np.where(ex, ctx["rng"].integers(0, 2, self.U), a)
        a = np.where(gmax > 0, a, 0)
        self.s_cur, self.a_cur = s, a
        return np.where(a == 1, best, -1)

    def after_step(self, ctx, sinr_s, hoflag):
        r = np.clip((sinr_s + 8.0) / 20.0, -0.5, 1.0) - self.c_ho * hoflag
        if self.s_prev is not None:
            s, a = self.s_prev
            target = self.r_prev + self.disc * self.Q[self.s_cur].max(axis=1)
            idx = s + (a,)
            delta = np.zeros_like(self.Q); cnt = np.zeros_like(self.Q)
            np.add.at(delta, idx, target - self.Q[idx]); np.add.at(cnt, idx, 1.0)
            self.Q += self.lr * delta / np.maximum(cnt, 1.0)
        self.s_prev = (self.s_cur, self.a_cur); self.r_prev = r
