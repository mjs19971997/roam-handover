// ho-scenario.cc
//
// ROAM versus Event A3 on ns-3.48 + 5G-LENA nr v5.1.
//
// Environments (--scen): base = 7 omni gNBs (centre + first hexagonal ring) in an open area,
// UEs on straight legs inside a disc; urban = the 3GPP TR 37.885 street grid with building
// blocks, sites on the streets, vehicles following the streets. One carrier, TR 36.839
// radio-link and handover failure model, downlink UDP traffic (--traffic).
//
// Rules (--rule):
//   a3    stock ns3::NrA3RsrpHandoverAlgorithm with --hyst / --ttt.
//   roam  ROAM in the form of the paper's Proposition 1: the standard Event A3 stays
//         configured once (hysteresis h0, offset 0, TTT), and a controller rewrites every
//         UE's per-neighbour Cell Individual Offset just before each measurement evaluation
//         so that the effective A3 margin is
//             m_ij = clip(h0 + etaH*H(b,c,j) - etaL*L(b,c,j) + etaS*w_s
//                         - etaA*gamma_i*(f_j - f_c), 0, mCap),        Ocn_j = h0 - m_ij.
//         The gNB side is ns3::RoamA3Algorithm: identical to the stock A3 algorithm except
//         that among the reported (triggered) cells it selects argmax(RSRP_j + Ocn_j), i.e.
//         the paper's argmax(F_j - F_c - m_ij). With all offsets zero it is the stock rule.
//   Not implemented on purpose: the base-layer bonus eps and the hold timer (the paper's
//   ablation shows both are dispensable).
//
// Every handover attempt is classified online (late / early / unnecessary / useful) from
// traces only; the classification feeds the history table and the statistics.
//
// Output: <outDir>/<tag>.json (one flat JSON object of metrics); with --events=1 also
// <tag>_att.csv (one row per handover attempt) and <tag>_rlf.csv; with --measCsv=1 the
// 200 ms RSRP reports in <tag>_meas.csv.

#include "ns3/applications-module.h"
#include "ns3/buildings-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/isotropic-antenna-model.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/propagation-module.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("HoScenario");

namespace
{
// ---------------------------------------------------------------------------
// service classes (the paper's table of service classes)
// ---------------------------------------------------------------------------
struct Svc
{
    const char* key;
    double tMin;  // minimum useful dwell [s]
    double thQ;   // minimum sustained gain [dB]
    double w;     // interruption weight w_s
    uint32_t n20; // number of UEs out of 20 (shares 20/20/15/30/15 %)
};
const std::array<Svc, 5> SVC = {{{"voice", 4.0, 0.7, 0.35, 4},
                                 {"vcall", 6.0, 1.0, 0.55, 4},
                                 {"gaming", 7.0, 1.2, 0.70, 3},
                                 {"stream", 3.0, 1.5, 0.20, 6},
                                 {"web", 2.0, 0.4, 0.10, 3}}};

enum Outcome
{
    OUT_USEFUL = 0,
    OUT_UNNEC = 1,
    OUT_EARLY = 2,
    OUT_LATE = 3,
    OUT_CENS = 4
};
const char* OUT_NAME[5] = {"useful", "unnecessary", "early", "late", "censored"};

// ---------------------------------------------------------------------------
// parameters shared by the callbacks
// ---------------------------------------------------------------------------
struct Params
{
    std::string rule = "a3";
    double h0 = 2.0, etaH = 14.0, etaL = 8.0, etaA = 8.0, etaS = 4.0, mCap = 9.0;
    double alpha = 0.6, beta = 1.0, tauF = 600.0, kappaL = 3.0, binRes = 40.0;
    double tP = 5.0, halfAngle = 0.6, rMin = 10.0, kappa = 1.0;
    double qOut = -8.0, t310 = 1.0, tPp = 1.0;
    double discard = 60.0;
    double noiseDbm = -127.2;
    uint32_t nGnb = 7;
    bool roam = false;
} P;

// ---------------------------------------------------------------------------
// history table: four outcome counts per route and per (location bin, target)
// ---------------------------------------------------------------------------
class Hht
{
  public:
    void Init(uint32_t nCell, double halfExtent, double res)
    {
        m_n = nCell + 1;
        m_res = res;
        m_x0 = -halfExtent;
        m_y0 = -halfExtent;
        m_nx = static_cast<int>(2.0 * halfExtent / res) + 1;
        m_ny = m_nx;
        m_route.assign(m_n * m_n * 4, 0.0);
        m_loc.assign(static_cast<size_t>(m_nx) * m_ny * m_n * 4, 0.0);
    }

    int Bin(double x, double y) const
    {
        int ix = std::clamp(static_cast<int>((x - m_x0) / m_res), 0, m_nx - 1);
        int iy = std::clamp(static_cast<int>((y - m_y0) / m_res), 0, m_ny - 1);
        return iy * m_nx + ix;
    }

    /// (H, L) for serving cell c, location bin b, target j.
    void Scores(uint16_t c, int b, uint16_t j, double& h, double& l) const
    {
        const double* r = &m_route[(c * m_n + j) * 4];
        const double rs = r[0] + r[1] + r[2] + r[3] + 4.0 * P.beta;
        const double* nl = &m_loc[(static_cast<size_t>(b) * m_n + j) * 4];
        double p[4];
        double s = 0.0;
        for (int x = 0; x < 4; ++x)
        {
            p[x] = nl[x] + P.kappaL * (r[x] + P.beta) / rs;
            s += p[x];
        }
        h = (P.alpha * p[1] + (1.0 - P.alpha) * p[2]) / s;
        l = p[3] / s;
    }

    void Update(uint16_t c, uint16_t j, int b, int out)
    {
        m_route[(c * m_n + j) * 4 + out] += 1.0;
        m_loc[(static_cast<size_t>(b) * m_n + j) * 4 + out] += 1.0;
        m_updates++;
    }

    void Decay(double dt)
    {
        const double f = std::exp(-dt / P.tauF);
        for (auto& v : m_route)
        {
            v *= f;
        }
        for (auto& v : m_loc)
        {
            v *= f;
        }
    }

    double RouteMass() const
    {
        double s = 0;
        for (auto v : m_route)
        {
            s += v;
        }
        return s;
    }

    uint64_t m_updates{0};

  private:
    uint32_t m_n{0};
    double m_res{40.0}, m_x0{0}, m_y0{0};
    int m_nx{0}, m_ny{0};
    std::vector<double> m_route;
    std::vector<double> m_loc;
} g_hht;

// ---------------------------------------------------------------------------
// path-loss-only radio map: best-server cell at a point, from the configured ns-3 model
// ---------------------------------------------------------------------------
struct RadioMap
{
    Ptr<PropagationLossModel> loss;
    std::vector<Ptr<MobilityModel>> gnb; // index 1..nGnb
    Ptr<MobilityModel> probe;
    std::vector<Vector> gnbPos;
    double ueHeight{1.5};

    uint16_t Best(double x, double y) const
    {
        probe->SetPosition(Vector(x, y, ueHeight));
        uint16_t best = 1;
        double bv = -1e300;
        for (uint16_t k = 1; k < gnb.size(); ++k)
        {
            const double rx = loss->CalcRxPower(0.0, gnb[k], probe);
            if (rx > bv)
            {
                bv = rx;
                best = k;
            }
        }
        return best;
    }

    uint16_t Nearest(double x, double y) const
    {
        uint16_t best = 1;
        double bd = 1e300;
        for (uint16_t k = 1; k < gnbPos.size(); ++k)
        {
            const double d = std::hypot(x - gnbPos[k].x, y - gnbPos[k].y);
            if (d < bd)
            {
                bd = d;
                best = k;
            }
        }
        return best;
    }
} g_map;

/// path overlap: share of the predicted-motion sector lying in the best-server
/// region of each cell; 48-point quadrature (6 equal-area rings x 8 angles).
void
AreaFrac(double x, double y, double v, double th, std::vector<double>& f)
{
    std::fill(f.begin(), f.end(), 0.0);
    const double rad = std::max(v * P.tP, P.rMin);
    for (int a = 0; a < 8; ++a)
    {
        const double ang = th + P.halfAngle * (((a + 0.5) / 8.0) * 2.0 - 1.0);
        const double ca = std::cos(ang);
        const double sa = std::sin(ang);
        for (int r = 0; r < 6; ++r)
        {
            const double rr = rad * std::sqrt((r + 0.5) / 6.0);
            f[g_map.Best(x + rr * ca, y + rr * sa)] += 1.0 / 48.0;
        }
    }
}

// ---------------------------------------------------------------------------
// per-UE state
// ---------------------------------------------------------------------------
struct UeState
{
    uint32_t idx{0};
    uint64_t imsi{0};
    int svc{0};
    Ptr<Node> node;
    Ptr<NrUeRrc> rrc;
    // measurements
    std::vector<double> l1;    // latest L1 RSRP per cell [dBm], NaN if absent in the report
    std::vector<double> l3;    // own replica of the layer-3 filtered RSRP [dBm]
    std::vector<double> rowBuf;
    bool rowPending{false};
    // motion confidence
    bool haveTh{false};
    double thPrev{0.0}, tTh{0.0}, omega{0.0}, gamma{1.0};
    int binNow{0};
    std::vector<double> margin; // last margins written (for the event log)
    // handover attempt in flight (command sent, not yet completed)
    bool inflight{false};
    double tCmd{0.0};
    uint16_t src{0}, tgt{0};
    int binDec{0};
    double xDec{0}, yDec{0}, mDec{NAN};
    // executed handover whose observation window is open
    bool pending{false};
    double t0{0.0}, pTCmd{0.0};
    uint16_t pSrc{0}, pTgt{0};
    int pBin{0};
    double pX{0}, pY{0}, pM{NAN};
    uint32_t n{0};
    double sumEval{0}, sumObs{0}, cfEval{0}, cfObs{0};
    bool rescEval{false}, rescObs{false}, pp{false};
    // ping-pong bookkeeping
    uint16_t prevCell{0};
    double lastHo{-1e9};
};

std::vector<UeState> g_ue;
std::map<uint64_t, uint32_t> g_imsiToUe;

// counters of the measurement window (attempts whose command time is >= discard)
struct Counters
{
    uint64_t attempts{0}, executed{0};
    uint64_t out[5] = {0, 0, 0, 0, 0}; // by evaluation label
    uint64_t obs[4] = {0, 0, 0, 0};    // by observable label (what the table is fed)
    uint64_t lateCmd{0}, lateExec{0}, lateOther{0};
    uint64_t rescue{0}, cShort{0}, cGain{0}, pp{0}, ppUn{0};
    uint64_t rlfT310{0}, rlfLateCmd{0}, rlfDuringHo{0}, rlfRlc{0}, rlfOther{0};
    uint64_t rlfNoPending{0}, unresolved{0};
    uint64_t txPkts{0}, rxPkts{0};
    // service metrics per class (downlink stream of each UE; uplink only counted)
    uint64_t cTx[5] = {0, 0, 0, 0, 0}, cRx[5] = {0, 0, 0, 0, 0};
    uint64_t cUlTx[5] = {0, 0, 0, 0, 0}, cUlRx[5] = {0, 0, 0, 0, 0};
    double cDelaySum[5] = {0, 0, 0, 0, 0};
    uint64_t cGap100[5] = {0, 0, 0, 0, 0}, cGap500[5] = {0, 0, 0, 0, 0};
    std::vector<uint32_t> cDelayHist[5]; // 1 ms bins, last bin = 5 s and more
    double outageS{0}; // time not RRC-connected, summed over the UEs, inside the window
    // cell activity: slots with at least one scheduled UE, and resource use of the data region
    uint64_t slotN{0}, slotActive{0};
    double regUsed{0}, regAvail{0};
    uint64_t losServ{0}, losN{0}; // urban only: 200 ms samples with a line of sight to the serving site
    double sinrSum{0};
    uint64_t sinrN{0};
    double marginSum{0}, hSum{0}, lSum{0}, gammaSum{0}, dfSum{0};
    uint64_t marginN{0};
    double dwellSum{0};
    uint64_t svcN[5] = {0, 0, 0, 0, 0}, svcUn[5] = {0, 0, 0, 0, 0};
    // whole run (including the discarded prefix), for information
    uint64_t allAttempts{0}, allRlf{0};
} C;

std::ofstream g_attCsv;
std::ofstream g_rlfCsv;
std::ofstream g_measCsv;

double
Now()
{
    return Simulator::Now().GetSeconds();
}

bool
InWindow(double t)
{
    return t >= P.discard - 1e-9;
}

/// SINR [dB] of cell k from a vector of per-cell RSRP [dBm], all other cells interfering.
double
GeoSinr(const std::vector<double>& rsrp, uint16_t k)
{
    if (k == 0 || k >= rsrp.size() || std::isnan(rsrp[k]))
    {
        return -100.0;
    }
    double intf = std::pow(10.0, P.noiseDbm / 10.0);
    for (uint16_t l = 1; l < rsrp.size(); ++l)
    {
        if (l != k && !std::isnan(rsrp[l]))
        {
            intf += std::pow(10.0, rsrp[l] / 10.0);
        }
    }
    return rsrp[k] - 10.0 * std::log10(intf);
}

void
WriteAtt(const UeState& s,
         double tCmd,
         uint16_t src,
         uint16_t tgt,
         double tExec,
         const char* reason,
         double dwell,
         uint32_t n,
         double gEval,
         double gObs,
         bool rescEval,
         bool rescObs,
         int outEval,
         int outObs,
         bool pp,
         double x,
         double y,
         double m)
{
    if (!g_attCsv.is_open())
    {
        return;
    }
    g_attCsv << std::fixed << std::setprecision(4) << tCmd << "," << s.idx << "," << s.imsi << ","
             << SVC[s.svc].key << "," << src << "," << tgt << "," << tExec << "," << Now() << ","
             << reason << "," << std::setprecision(3) << dwell << "," << n << "," << gEval << ","
             << gObs << "," << rescEval << "," << rescObs << "," << OUT_NAME[outEval] << ","
             << (outObs >= 0 ? OUT_NAME[outObs] : "") << "," << pp << "," << std::setprecision(1)
             << x << "," << y << "," << std::setprecision(2) << m << ","
             << (InWindow(tCmd) ? 1 : 0) << "\n";
}

/// Close the observation window of an executed handover. reason: "ho" (left by a new
/// handover attempt), "win" (window complete), "rlf" (radio link failure in the target),
/// "end" (censored by the end of the run).
void
Finalize(UeState& s, const char* reason)
{
    if (!s.pending)
    {
        return;
    }
    s.pending = false;
    const std::string r(reason);
    const Svc& sv = SVC[s.svc];
    const double dwell = Now() - s.t0;
    const double nn = std::max<uint32_t>(s.n, 1);
    const double gEval = s.sumEval / nn;
    const double gObs = s.sumObs / nn;
    const bool isShort = dwell < sv.tMin - 1e-9;
    const bool low = gEval < sv.thQ;
    const bool failed = (r == "rlf");
    const bool win = InWindow(s.pTCmd);

    if (r == "end")
    {
        if (win)
        {
            C.out[OUT_CENS]++;
        }
        WriteAtt(s, s.pTCmd, s.pSrc, s.pTgt, s.t0, reason, dwell, s.n, gEval, gObs, s.rescEval,
                 s.rescObs, OUT_CENS, -1, s.pp, s.pX, s.pY, s.pM);
        return;
    }

    const bool un = !failed && !s.rescEval && (isShort || low);
    const int outEval = failed ? OUT_EARLY : (un ? OUT_UNNEC : OUT_USEFUL);
    const bool unObs = !failed && !s.rescObs && (isShort || gObs < sv.thQ);
    const int outObs = failed ? OUT_EARLY : (unObs ? OUT_UNNEC : OUT_USEFUL);

    // the table is fed with the observable label, from the first second of the run
    g_hht.Update(s.pSrc, s.pTgt, s.pBin, outObs);

    if (win)
    {
        C.out[outEval]++;
        C.obs[outObs]++;
        C.dwellSum += dwell;
        C.svcN[s.svc]++;
        if (un)
        {
            C.svcUn[s.svc]++;
            if (s.pp)
            {
                C.ppUn++;
            }
            else if (isShort)
            {
                C.cShort++;
            }
            else
            {
                C.cGain++;
            }
        }
        if (!failed && s.rescEval && (isShort || low))
        {
            C.rescue++;
        }
    }
    WriteAtt(s, s.pTCmd, s.pSrc, s.pTgt, s.t0, reason, dwell, s.n, gEval, gObs, s.rescEval,
             s.rescObs, outEval, outObs, s.pp, s.pX, s.pY, s.pM);
}

/// A handover attempt that did not complete, or a link lost with no handover pending.
void
RecordLate(UeState& s, uint16_t src, uint16_t tgt, bool isAttempt, double tCmd, const char* why)
{
    if (src == 0 || tgt == 0 || src == tgt)
    {
        return;
    }
    Vector p = s.node->GetObject<MobilityModel>()->GetPosition();
    g_hht.Update(src, tgt, g_hht.Bin(p.x, p.y), OUT_LATE);
    if (isAttempt)
    {
        if (InWindow(tCmd))
        {
            C.out[OUT_LATE]++;
            C.obs[OUT_LATE]++;
            C.svcN[s.svc]++;
        }
        WriteAtt(s, tCmd, src, tgt, NAN, why, 0.0, 0, NAN, NAN, false, false, OUT_LATE, OUT_LATE,
                 false, p.x, p.y, s.mDec);
    }
}

// ---------------------------------------------------------------------------
// controller: write the per-neighbour CIOs of one UE (called right before the UE RRC
// evaluates its measurement events, i.e. once per measurement period)
// ---------------------------------------------------------------------------
void
ControllerTick(UeState& s)
{
    Ptr<MobilityModel> mm = s.node->GetObject<MobilityModel>();
    const Vector pos = mm->GetPosition();
    const Vector vel = mm->GetVelocity();
    const double v = std::hypot(vel.x, vel.y);
    const double now = Now();
    double th = s.thPrev;
    if (v > 1e-6)
    {
        th = std::atan2(vel.y, vel.x);
    }
    if (s.haveTh && now > s.tTh)
    {
        // Omega <- 0.9*Omega + 0.1*|dtheta|/dt on a 100 ms grid (paper Eq. gamma); for another
        // step length the same exponential average is 0.9^(dt/0.1).
        double d = std::fabs(std::remainder(th - s.thPrev, 2.0 * M_PI));
        const double dt = now - s.tTh;
        const double lam = std::pow(0.9, dt / 0.1);
        s.omega = lam * s.omega + (1.0 - lam) * d / dt;
    }
    s.haveTh = true;
    s.thPrev = th;
    s.tTh = now;
    s.gamma = 1.0 / (1.0 + P.kappa * s.omega * P.tP);
    s.binNow = g_hht.Bin(pos.x, pos.y);

    if (!P.roam)
    {
        return;
    }
    const uint16_t c = s.rrc->GetCellId();
    if (c == 0 || c > P.nGnb)
    {
        return;
    }
    static std::vector<double> f;
    f.assign(P.nGnb + 1, 0.0);
    if (P.etaA != 0.0)
    {
        AreaFrac(pos.x, pos.y, v, th, f);
    }
    for (uint16_t j = 1; j <= P.nGnb; ++j)
    {
        if (j == c)
        {
            s.rrc->SetCellIndividualOffset(j, 0.0); // Ocp of the serving cell stays 0
            s.margin[j] = NAN;
            continue;
        }
        double h = 0.0;
        double l = 0.0;
        g_hht.Scores(c, s.binNow, j, h, l);
        const double df = f[j] - f[c];
        double m = P.h0 + P.etaH * h - P.etaL * l + P.etaS * SVC[s.svc].w - P.etaA * s.gamma * df;
        m = std::clamp(m, 0.0, P.mCap);
        s.margin[j] = m;
        s.rrc->SetCellIndividualOffset(j, P.h0 - m);
        if (InWindow(now))
        {
            C.marginSum += m;
            C.hSum += h;
            C.lSum += l;
            C.dfSum += df;
            C.marginN++;
        }
    }
    if (InWindow(now))
    {
        C.gammaSum += s.gamma;
    }
}

// ---------------------------------------------------------------------------
// measurement handling
// ---------------------------------------------------------------------------
void
ProcessReport(uint32_t u)
{
    UeState& s = g_ue[u];
    s.rowPending = false;
    const double now = Now();
    for (uint16_t k = 1; k <= P.nGnb; ++k)
    {
        s.l1[k] = s.rowBuf[k];
        if (!std::isnan(s.rowBuf[k]))
        {
            // layer-3 filter, k = 4 (a = 0.5), as configured in the UEs
            s.l3[k] = std::isnan(s.l3[k]) ? s.rowBuf[k] : 0.5 * s.l3[k] + 0.5 * s.rowBuf[k];
        }
        if (g_measCsv.is_open() && !std::isnan(s.rowBuf[k]))
        {
            g_measCsv << std::fixed << std::setprecision(3) << now << "," << u << "," << k << ","
                      << std::setprecision(2) << s.rowBuf[k] << "," << s.l3[k] << ","
                      << (s.rrc->GetCellId() == k ? 1 : 0) << "\n";
        }
    }
    const uint16_t serv = s.rrc->GetCellId();
    if (InWindow(now) && serv >= 1 && serv <= P.nGnb && !std::isnan(s.l1[serv]))
    {
        C.sinrSum += GeoSinr(s.l1, serv);
        if (BuildingList::GetNBuildings() > 0)
        {
            const Vector up = s.node->GetObject<MobilityModel>()->GetPosition();
            bool blocked = false;
            for (auto b = BuildingList::Begin(); b != BuildingList::End(); ++b)
            {
                blocked = blocked || (*b)->IsIntersect(g_map.gnbPos[serv], up);
            }
            C.losN++;
            C.losServ += blocked ? 0 : 1;
        }
        C.sinrN++;
    }
    if (s.pending && now > s.t0)
    {
        const double dt = 0.2;
        const double sT = GeoSinr(s.l1, s.pTgt);
        const double sS = GeoSinr(s.l1, s.pSrc);
        s.sumEval += sT - sS;
        s.cfEval = (sS < P.qOut) ? s.cfEval + dt : 0.0;
        s.rescEval = s.rescEval || (s.cfEval >= P.t310 - 1e-9);
        const double fT = std::isnan(s.l3[s.pTgt]) ? -157.0 : s.l3[s.pTgt];
        const double fS = std::isnan(s.l3[s.pSrc]) ? -157.0 : s.l3[s.pSrc];
        s.sumObs += fT - fS;
        const double oS = GeoSinr(s.l3, s.pSrc);
        s.cfObs = (oS < P.qOut) ? s.cfObs + dt : 0.0;
        s.rescObs = s.rescObs || (s.cfObs >= P.t310 - 1e-9);
        s.n++;
        if (now - s.t0 >= SVC[s.svc].tMin - 1e-9)
        {
            Finalize(s, "win");
        }
    }
}

void
UeMeasurement(uint32_t u,
              uint16_t rnti,
              uint16_t cellId,
              double rsrp,
              double rsrq,
              bool isServing,
              uint8_t ccId)
{
    UeState& s = g_ue[u];
    if (!s.rowPending)
    {
        // first row of this measurement period: the UE RRC evaluates its events right after
        // the rows have been delivered, so the offsets are refreshed here
        s.rowPending = true;
        std::fill(s.rowBuf.begin(), s.rowBuf.end(), NAN);
        ControllerTick(s);
        Simulator::ScheduleNow(&ProcessReport, u);
    }
    if (cellId >= 1 && cellId <= P.nGnb)
    {
        s.rowBuf[cellId] = rsrp;
    }
}

// ---------------------------------------------------------------------------
// handover and failure traces
// ---------------------------------------------------------------------------
void
GnbHandoverStart(uint64_t imsi, uint16_t cellId, uint16_t rnti, uint16_t targetCellId)
{
    auto it = g_imsiToUe.find(imsi);
    if (it == g_imsiToUe.end())
    {
        return;
    }
    UeState& s = g_ue[it->second];
    const double now = Now();
    C.allAttempts++;
    if (s.inflight)
    {
        if (InWindow(s.tCmd))
        {
            C.unresolved++;
        }
        s.inflight = false;
    }
    Finalize(s, "ho"); // the user leaves the previous target by a new handover
    Vector p = s.node->GetObject<MobilityModel>()->GetPosition();
    s.inflight = true;
    s.tCmd = now;
    s.src = cellId;
    s.tgt = targetCellId;
    s.binDec = g_hht.Bin(p.x, p.y);
    s.xDec = p.x;
    s.yDec = p.y;
    s.mDec = (P.roam && targetCellId < s.margin.size()) ? s.margin[targetCellId] : NAN;
    if (InWindow(now))
    {
        C.attempts++;
    }
}

void
UeHandoverEndOk(uint64_t imsi, uint16_t cellId, uint16_t rnti)
{
    UeState& s = g_ue[g_imsiToUe[imsi]];
    const double now = Now();
    if (!s.inflight)
    {
        return; // not expected
    }
    s.inflight = false;
    s.pending = true;
    s.t0 = now;
    s.pTCmd = s.tCmd;
    s.pSrc = s.src;
    s.pTgt = cellId;
    s.pBin = s.binDec;
    s.pX = s.xDec;
    s.pY = s.yDec;
    s.pM = s.mDec;
    s.n = 0;
    s.sumEval = s.sumObs = s.cfEval = s.cfObs = 0.0;
    s.rescEval = s.rescObs = false;
    s.pp = (s.prevCell == cellId) && ((now - s.lastHo) < P.tPp);
    s.prevCell = s.src;
    s.lastHo = now;
    if (InWindow(s.tCmd))
    {
        C.executed++;
        if (s.pp)
        {
            C.pp++;
        }
    }
}

void
UeRadioLinkFailureCause(uint64_t imsi,
                        uint16_t cellId,
                        uint16_t rnti,
                        uint16_t oldState,
                        std::string cause,
                        int64_t t310ElapsedMs,
                        int64_t msSinceLastHoSuccess)
{
    UeState& s = g_ue[g_imsiToUe[imsi]];
    const double now = Now();
    const bool win = InWindow(now);
    C.allRlf++;
    Vector p = s.node->GetObject<MobilityModel>()->GetPosition();
    std::string handled = "ignored";

    const bool radio = (cause == "T310_EXPIRY" || cause == "HO_COMMAND_LATE" ||
                        cause == "DURING_HANDOVER" || cause == "RLC_MAX_RETX");
    if (win)
    {
        if (cause == "T310_EXPIRY")
        {
            C.rlfT310++;
        }
        else if (cause == "HO_COMMAND_LATE")
        {
            C.rlfLateCmd++;
        }
        else if (cause == "DURING_HANDOVER")
        {
            C.rlfDuringHo++;
        }
        else if (cause == "RLC_MAX_RETX")
        {
            C.rlfRlc++;
        }
        else
        {
            C.rlfOther++;
        }
    }
    if (radio)
    {
        if (s.inflight)
        {
            // the command could not be delivered, or the execution failed: late
            s.inflight = false;
            if (InWindow(s.tCmd))
            {
                if (cause == "HO_COMMAND_LATE")
                {
                    C.lateCmd++;
                }
                else if (cause == "DURING_HANDOVER")
                {
                    C.lateExec++;
                }
                else
                {
                    C.lateOther++;
                }
            }
            RecordLate(s, s.src, s.tgt, true, s.tCmd, cause.c_str());
            handled = "late_attempt";
        }
        else if (s.pending)
        {
            Finalize(s, "rlf"); // too early / wrong cell
            handled = "early";
        }
        else
        {
            // link lost with no handover pending: late, towards the strongest neighbour
            uint16_t best = 0;
            double bv = -1e300;
            for (uint16_t k = 1; k <= P.nGnb; ++k)
            {
                if (k != cellId && !std::isnan(s.l3[k]) && s.l3[k] > bv)
                {
                    bv = s.l3[k];
                    best = k;
                }
            }
            if (win)
            {
                C.rlfNoPending++;
            }
            RecordLate(s, cellId, best, false, now, cause.c_str());
            handled = "late_no_attempt";
        }
    }
    if (g_rlfCsv.is_open())
    {
        g_rlfCsv << std::fixed << std::setprecision(4) << now << "," << s.idx << "," << imsi << ","
                 << cellId << "," << cause << "," << oldState << "," << t310ElapsedMs << ","
                 << msSinceLastHoSuccess << "," << handled << "," << std::setprecision(1) << p.x
                 << "," << p.y << "," << (win ? 1 : 0) << "\n";
    }
}

void
HhtDecayTick()
{
    g_hht.Decay(1.0);
    Simulator::Schedule(Seconds(1.0), &HhtDecayTick);
}

std::vector<double> g_lastRx; // per UE: time of the last received downlink packet

void
TxTrace(uint32_t u, Ptr<const Packet> p)
{
    if (InWindow(Now()))
    {
        C.txPkts++;
        C.cTx[g_ue[u].svc]++;
    }
}

void
RxTrace(uint32_t u, Ptr<const Packet> p, const Address& a)
{
    // packets sent before the window and received inside it are a negligible edge effect
    const double now = Now();
    if (InWindow(now))
    {
        const int k = g_ue[u].svc;
        C.rxPkts++;
        C.cRx[k]++;
        SeqTsHeader h;
        if (p->GetSize() >= h.GetSerializedSize())
        {
            p->PeekHeader(h);
            const double d = now - h.GetTs().GetSeconds();
            C.cDelaySum[k] += d;
            const size_t bin = std::min<size_t>(static_cast<size_t>(std::max(d, 0.0) * 1000.0), 5000);
            C.cDelayHist[k][bin]++;
        }
        if (InWindow(g_lastRx[u]) && g_lastRx[u] > 0.0)
        {
            const double gap = now - g_lastRx[u];
            C.cGap100[k] += gap > 0.1 ? 1 : 0;
            C.cGap500[k] += gap > 0.5 ? 1 : 0;
        }
    }
    g_lastRx[u] = now;
}

void
UlTxTrace(uint32_t u, Ptr<const Packet> p)
{
    if (InWindow(Now()))
    {
        C.cUlTx[g_ue[u].svc]++;
    }
}

void
UlRxTrace(uint32_t u, Ptr<const Packet> p, const Address& a)
{
    if (InWindow(Now()))
    {
        C.cUlRx[g_ue[u].svc]++;
    }
}

// time outside RRC connected (states other than CONNECTED_NORMALLY and CONNECTED_HANDOVER)
std::vector<double> g_discSince; // per UE: start of the current not-connected period, -1 if connected

void
UeRrcState(uint32_t u,
           uint64_t imsi,
           uint16_t cellId,
           uint16_t rnti,
           NrUeRrc::State oldState,
           NrUeRrc::State newState)
{
    const bool conn = (newState == NrUeRrc::CONNECTED_NORMALLY || newState == NrUeRrc::CONNECTED_HANDOVER);
    const double now = Now();
    if (conn && g_discSince[u] >= 0.0)
    {
        C.outageS += std::max(0.0, now - std::max(g_discSince[u], P.discard));
        g_discSince[u] = -1.0;
    }
    else if (!conn && g_discSince[u] < 0.0)
    {
        g_discSince[u] = now;
    }
}

void
SlotData(const SfnSf& sfn,
         uint32_t scheduledUe,
         uint32_t usedReg,
         uint32_t usedSym,
         uint32_t availableRb,
         uint32_t availableSym,
         uint16_t bwpId,
         uint16_t cellId)
{
    if (InWindow(Now()))
    {
        C.slotN++;
        C.slotActive += scheduledUe > 0 ? 1 : 0;
        C.regUsed += usedReg;
        C.regAvail += static_cast<double>(availableRb) * availableSym;
    }
}

void
Progress(double step, std::chrono::steady_clock::time_point t0)
{
    double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::cout << "[progress] sim=" << Now() << " s wall=" << std::fixed << std::setprecision(1)
              << wall << " s attempts=" << C.allAttempts << " rlf=" << C.allRlf
              << " table=" << g_hht.m_updates << std::endl;
    Simulator::Schedule(Seconds(step), &Progress, step, t0);
}
} // namespace

// ---------------------------------------------------------------------------
// gNB side of ROAM: stock Event A3 handling, target = argmax(RSRP_j + Ocn_j)
// ---------------------------------------------------------------------------
namespace ns3
{

class RoamA3Algorithm : public NrHandoverAlgorithm
{
  public:
    RoamA3Algorithm()
    {
        m_sapProvider = new MemberNrHandoverManagementSapProvider<RoamA3Algorithm>(this);
    }

    ~RoamA3Algorithm() override = default;

    static TypeId GetTypeId()
    {
        static TypeId tid =
            TypeId("ns3::RoamA3Algorithm")
                .SetParent<NrHandoverAlgorithm>()
                .SetGroupName("Nr")
                .AddConstructor<RoamA3Algorithm>()
                .AddAttribute("Hysteresis",
                              "A3 hysteresis h0 in dB (0..15, 0.5 dB steps)",
                              DoubleValue(2.0),
                              MakeDoubleAccessor(&RoamA3Algorithm::m_hysteresisDb),
                              MakeDoubleChecker<double>(0.0, 15.0))
                .AddAttribute("TimeToTrigger",
                              "A3 time-to-trigger",
                              TimeValue(MilliSeconds(300)),
                              MakeTimeAccessor(&RoamA3Algorithm::m_timeToTrigger),
                              MakeTimeChecker());
        return tid;
    }

    void SetNrHandoverManagementSapUser(NrHandoverManagementSapUser* s) override
    {
        m_sapUser = s;
    }

    NrHandoverManagementSapProvider* GetNrHandoverManagementSapProvider() override
    {
        return m_sapProvider;
    }

    void SetGnbRrc(Ptr<NrGnbRrc> rrc)
    {
        m_rrc = rrc;
    }

    friend class MemberNrHandoverManagementSapProvider<RoamA3Algorithm>;

  protected:
    void DoInitialize() override
    {
        // exactly the report configuration of NrA3RsrpHandoverAlgorithm
        NrRrcSap::ReportConfigEutra rc;
        rc.eventId = NrRrcSap::ReportConfigEutra::EVENT_A3;
        rc.a3Offset = 0;
        rc.hysteresis = nr::EutranMeasurementMapping::ActualHysteresis2IeValue(m_hysteresisDb);
        rc.timeToTrigger = m_timeToTrigger.GetMilliSeconds();
        rc.reportOnLeave = false;
        rc.triggerQuantity = NrRrcSap::ReportConfigEutra::RSRP;
        rc.reportInterval = NrRrcSap::ReportConfigEutra::MS1024;
        m_measIds = m_sapUser->AddUeMeasReportConfigForHandover(rc);
        NrHandoverAlgorithm::DoInitialize();
    }

    void DoDispose() override
    {
        delete m_sapProvider;
        m_sapProvider = nullptr;
        m_rrc = nullptr;
        NrHandoverAlgorithm::DoDispose();
    }

    void DoReportUeMeas(uint16_t rnti, NrRrcSap::MeasResults measResults) override
    {
        if (std::find(m_measIds.begin(), m_measIds.end(), measResults.measId) == m_measIds.end())
        {
            return;
        }
        if (!measResults.haveMeasResultNeighCells || measResults.measResultListEutra.empty())
        {
            return;
        }
        // the offsets this network wrote into the UE (zero for every cell if none)
        Ptr<NrUeRrc> ueRrc;
        if (m_rrc && m_rrc->HasUeManager(rnti))
        {
            auto it = g_imsiToUe.find(m_rrc->GetUeManager(rnti)->GetImsi());
            if (it != g_imsiToUe.end())
            {
                ueRrc = g_ue[it->second].rrc;
            }
        }
        uint16_t bestCell = 0;
        double bestScore = 0.0;
        bool have = false;
        for (const auto& n : measResults.measResultListEutra)
        {
            if (!n.haveRsrpResult || n.rsrpResult == 0)
            {
                continue;
            }
            const double ocn = ueRrc ? ueRrc->GetCellIndividualOffset(n.physCellId) : 0.0;
            const double score = static_cast<double>(n.rsrpResult) + ocn;
            if (!have || score > bestScore)
            {
                have = true;
                bestScore = score;
                bestCell = n.physCellId;
            }
        }
        if (bestCell > 0)
        {
            m_sapUser->TriggerHandover(rnti, bestCell);
        }
    }

  private:
    NrHandoverManagementSapUser* m_sapUser{nullptr};
    NrHandoverManagementSapProvider* m_sapProvider{nullptr};
    std::vector<uint8_t> m_measIds;
    double m_hysteresisDb{2.0};
    Time m_timeToTrigger{MilliSeconds(300)};
    Ptr<NrGnbRrc> m_rrc;
};

NS_OBJECT_ENSURE_REGISTERED(RoamA3Algorithm);

} // namespace ns3

// ---------------------------------------------------------------------------
int
main(int argc, char* argv[])
{
    uint32_t nUe = 20;
    double isd = 400.0;
    double discRadius = 0.0;
    double speed = 16.0;
    double simTime = 180.0;
    double hyst = 3.0;  // rule a3
    double tttMs = 300.0;
    std::string scenario = "UMa";
    std::string condition = "NLOS";
    bool shadowing = true;
    bool fading = false;
    double fadingUpdateMs = 0.0; // ThreeGppChannelModel::UpdatePeriod; 0 = 1 m of travel
    double frequency = 3.5e9;
    double bandwidth = 10e6;
    uint32_t numerology = 0;
    double gnbTxPower = 40.0;
    double gnbHeight = 25.0;
    double ueHeight = 1.5;
    bool idealRrc = true;
    bool tr36839 = true;
    double qIn = -6.0;
    double t310Ms = 1000.0;
    uint32_t n310 = 1;
    uint32_t n311 = 1;
    double prepDelayMs = 50.0; // TR 36.839 handover preparation delay
    double udpIntervalMs = 100.0;
    uint32_t udpPacketSize = 200;
    bool events = false;
    bool measCsv = false;
    uint32_t rngRun = 1;
    std::string outDir = ".";
    std::string tag = "run";
    double progressStep = 0.0;

    CommandLine cmd(__FILE__);
    cmd.AddValue("rule", "a3 | roam", P.rule);
    cmd.AddValue("hyst", "A3 hysteresis for rule a3 (dB)", hyst);
    cmd.AddValue("ttt", "time-to-trigger (ms), both rules", tttMs);
    cmd.AddValue("h0", "ROAM base margin (dB)", P.h0);
    cmd.AddValue("etaH", "ROAM weight of the premature-handover risk H (dB)", P.etaH);
    cmd.AddValue("etaL", "ROAM weight of the lateness evidence L (dB)", P.etaL);
    cmd.AddValue("etaA", "ROAM weight of the path overlap (dB)", P.etaA);
    cmd.AddValue("etaS", "ROAM weight of the service term (dB)", P.etaS);
    cmd.AddValue("mCap", "ROAM margin cap (dB)", P.mCap);
    cmd.AddValue("tauF", "history discount time constant (s)", P.tauF);
    cmd.AddValue("discard", "prefix excluded from all statistics (s)", P.discard);
    cmd.AddValue("nUe", "number of UEs", nUe);
    cmd.AddValue("isd", "inter-site distance (m)", isd);
    cmd.AddValue("discRadius", "radius of the UE mobility disc (m), 0 = 1.3*isd", discRadius);
    cmd.AddValue("speed", "UE speed (m/s)", speed);
    cmd.AddValue("simTime", "simulated time (s), including the discarded prefix", simTime);
    cmd.AddValue("scenario", "3GPP scenario: UMa | UMi | RMa", scenario);
    cmd.AddValue("condition", "channel condition: LOS | NLOS", condition);
    cmd.AddValue("shadowing", "enable log-normal shadowing", shadowing);
    cmd.AddValue("fading", "enable TR 38.901 fast fading", fading);
    cmd.AddValue("fadingUpdate", "channel update period (ms); 0 = time to travel 1 m", fadingUpdateMs);
    cmd.AddValue("frequency", "carrier frequency (Hz)", frequency);
    cmd.AddValue("bandwidth", "carrier bandwidth (Hz)", bandwidth);
    cmd.AddValue("numerology", "NR numerology", numerology);
    cmd.AddValue("gnbTxPower", "gNB transmit power (dBm)", gnbTxPower);
    cmd.AddValue("idealRrc", "ideal RRC", idealRrc);
    cmd.AddValue("tr36839", "TR 36.839 handover failure model", tr36839);
    cmd.AddValue("qOut", "Qout (dB)", P.qOut);
    cmd.AddValue("qIn", "Qin (dB)", qIn);
    cmd.AddValue("t310", "T310 (ms)", t310Ms);
    cmd.AddValue("n310", "N310", n310);
    cmd.AddValue("n311", "N311", n311);
    cmd.AddValue("prepDelay", "handover preparation delay (ms)", prepDelayMs);
    cmd.AddValue("udpInterval", "downlink UDP packet interval (ms)", udpIntervalMs);
    cmd.AddValue("udpPacketSize", "downlink UDP packet size (bytes)", udpPacketSize);
    cmd.AddValue("events", "write per-attempt and per-RLF CSV files", events);
    cmd.AddValue("measCsv", "write the 200 ms RSRP reports", measCsv);
    cmd.AddValue("rngRun", "RNG run number (seed)", rngRun);
    cmd.AddValue("outDir", "output directory (Windows style path)", outDir);
    cmd.AddValue("tag", "job id / prefix of the output files", tag);
    cmd.AddValue("progress", "progress print step (s), 0 = off", progressStep);
    std::string scen = "base";
    cmd.AddValue("scen", "base (open area) | urban (TR 37.885 street grid with buildings)", scen);
    std::string traffic = "light";
    double fullRateMbps = 12.0;
    cmd.AddValue("traffic", "light (one small downlink flow per UE) | mixed (per service class) | full (downlink overload)", traffic);
    cmd.AddValue("fullRate", "offered downlink rate per UE with --traffic=full (Mbit/s)", fullRateMbps);
    bool ulTraffic = false;
    cmd.AddValue("ulTraffic", "traffic=mixed: also start the uplink flows (off: nr v5.1 aborts on UL data around handovers)", ulTraffic);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(P.rule != "a3" && P.rule != "roam", "unknown --rule " << P.rule);
    NS_ABORT_MSG_IF(traffic != "light" && traffic != "mixed" && traffic != "full",
                    "unknown --traffic " << traffic);
    NS_ABORT_MSG_IF(scen != "base" && scen != "urban", "unknown --scen " << scen);
    const bool urban = (scen == "urban");
    // ---- urban scenario: constants fixed before any run ------------------------------------
    const double gridX = 433.0;  // distance between intersections, x (TR 37.885 Annex A)
    const double gridY = 250.0;  // distance between intersections, y
    const double streetW = 20.0; // 2 x 2 lanes of 3.5 m + 2 x 3 m sidewalk
    const double bldgH = 20.0;   // building height; any value above the 10 m sites gives the same LOS
    if (urban)
    {
        scenario = "UMi";        // TR 38.901 UMi street canyon, sites below the rooftops
        condition = "Buildings"; // LOS/NLOS from the geometry of the building blocks
        gnbHeight = 10.0;        // TR 38.901 Table 7.2-1, UMi
    }
    P.roam = (P.rule == "roam");
    P.t310 = t310Ms / 1000.0;
    if (discRadius <= 0.0)
    {
        discRadius = 1.3 * isd;
    }
    const uint32_t nGnb = 7;
    P.nGnb = nGnb;
    const double ueNoiseFigure = 5.0;
    P.noiseDbm = -174.0 + 10.0 * std::log10(15000.0 * std::pow(2.0, numerology)) + ueNoiseFigure;

    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(rngRun);

    // ---- defaults: TR 36.839 radio link and handover failure model --------------
    Config::SetDefault("ns3::NrGnbPhy::TxPower", DoubleValue(gnbTxPower));
    Config::SetDefault("ns3::NrGnbPhy::Numerology", UintegerValue(numerology));
    Config::SetDefault("ns3::NrUePhy::NoiseFigure", DoubleValue(ueNoiseFigure));
    Config::SetDefault("ns3::NrUePhy::EnableRlfDetection", BooleanValue(true));
    Config::SetDefault("ns3::NrUePhy::Qout", DoubleValue(P.qOut));
    Config::SetDefault("ns3::NrUePhy::Qin", DoubleValue(qIn));
    Config::SetDefault("ns3::NrUeRrc::T310", TimeValue(MilliSeconds(t310Ms)));
    Config::SetDefault("ns3::NrUeRrc::N310", UintegerValue(n310));
    Config::SetDefault("ns3::NrUeRrc::N311", UintegerValue(n311));
    Config::SetDefault("ns3::NrUeRrc::Tr36839HandoverFailure", BooleanValue(tr36839));
    Config::SetDefault("ns3::NrGnbRrc::HandoverDecisionDelay", TimeValue(MilliSeconds(prepDelayMs)));
    if (fading)
    {
        if (fadingUpdateMs <= 0.0)
        {
            fadingUpdateMs = std::floor(1000.0 / std::max(speed, 1.0));
        }
        Config::SetDefault("ns3::ThreeGppChannelModel::UpdatePeriod",
                           TimeValue(MilliSeconds(fadingUpdateMs)));
    }

    // ---- helpers ---------------------------------------------------------------
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    nrHelper->SetEpcHelper(epcHelper);
    nrHelper->SetAttribute("UseIdealRrc", BooleanValue(idealRrc));

    if (P.roam)
    {
        nrHelper->SetHandoverAlgorithmType("ns3::RoamA3Algorithm");
        nrHelper->SetHandoverAlgorithmAttribute("Hysteresis", DoubleValue(P.h0));
    }
    else
    {
        nrHelper->SetHandoverAlgorithmType("ns3::NrA3RsrpHandoverAlgorithm");
        nrHelper->SetHandoverAlgorithmAttribute("Hysteresis", DoubleValue(hyst));
    }
    nrHelper->SetHandoverAlgorithmAttribute("TimeToTrigger", TimeValue(MilliSeconds(tttMs)));

    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(1));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(1));
    nrHelper->SetUeAntennaAttribute("AntennaElement",
                                    PointerValue(CreateObject<IsotropicAntennaModel>()));
    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(1));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(1));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
                                     PointerValue(CreateObject<IsotropicAntennaModel>()));
    Ptr<IdealBeamformingHelper> bfHelper = CreateObject<IdealBeamformingHelper>();
    bfHelper->SetAttribute("BeamformingMethod", TypeIdValue(DirectPathBeamforming::GetTypeId()));
    nrHelper->SetBeamformingHelper(bfHelper);

    // ---- topology ---------------------------------------------------------------
    NodeContainer gnbNodes;
    gnbNodes.Create(nGnb);
    NodeContainer ueNodes;
    ueNodes.Create(nUe);

    std::vector<Vector> gnbXyz;
    gnbXyz.emplace_back(0.0, 0.0, gnbHeight);
    for (uint32_t k = 0; k < 6; ++k)
    {
        const double a = k * M_PI / 3.0;
        gnbXyz.emplace_back(isd * std::cos(a), isd * std::sin(a), gnbHeight);
    }
    if (urban)
    {
        // Streets of the 2 x 2 block area: y = -250, 0, 250 (x in [-433, 433]) and
        // x = -433, 0, 433 (y in [-250, 250]); an intersection is at the origin. Every site of
        // the hexagonal plan is moved to the nearest point of a street centre line (a tie goes
        // to the east-west street), and four building blocks fill the grid cells.
        for (auto& p : gnbXyz)
        {
            double best = 1e300;
            Vector q = p;
            for (int k = -1; k <= 1; ++k)
            {
                const double cx = std::clamp(p.x, -gridX, gridX);
                const double d = std::hypot(p.x - cx, p.y - k * gridY);
                if (d < best)
                {
                    best = d;
                    q = Vector(cx, k * gridY, gnbHeight);
                }
            }
            for (int k = -1; k <= 1; ++k)
            {
                const double cy = std::clamp(p.y, -gridY, gridY);
                const double d = std::hypot(p.x - k * gridX, p.y - cy);
                if (d < best)
                {
                    best = d;
                    q = Vector(k * gridX, cy, gnbHeight);
                }
            }
            p = q;
        }
        for (int bx = -1; bx <= 0; ++bx)
        {
            for (int by = -1; by <= 0; ++by)
            {
                Ptr<Building> b = CreateObject<Building>();
                b->SetBoundaries(Box(bx * gridX + streetW / 2,
                                     (bx + 1) * gridX - streetW / 2,
                                     by * gridY + streetW / 2,
                                     (by + 1) * gridY - streetW / 2,
                                     0.0,
                                     bldgH));
            }
        }
    }
    Ptr<ListPositionAllocator> gnbPos = CreateObject<ListPositionAllocator>();
    for (const auto& p : gnbXyz)
    {
        gnbPos->Add(p);
    }
    MobilityHelper gnbMobility;
    gnbMobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gnbMobility.SetPositionAllocator(gnbPos);
    gnbMobility.Install(gnbNodes);

    if (urban)
    {
        // Vehicles on the street centre lines at constant speed; at an intersection straight
        // on with probability 0.5, left 0.25, right 0.25 (TR 36.885 A.1.2); a direction that
        // would leave the area is not offered and the remaining ones are renormalised.
        Ptr<UniformRandomVariable> rv = CreateObject<UniformRandomVariable>();
        rv->SetStream(200);
        const int DX[4] = {1, 0, -1, 0}; // 0 east, 1 north, 2 west, 3 south
        const int DY[4] = {0, 1, 0, -1};
        auto hasEdge = [&](int ix, int iy, int d) {
            const int jx = ix + DX[d];
            const int jy = iy + DY[d];
            return jx >= 0 && jx <= 2 && jy >= 0 && jy <= 2;
        };
        const double totalLen = 6 * gridX + 6 * gridY;
        for (uint32_t u = 0; u < nUe; ++u)
        {
            // uniform over the road length: 6 east-west edges of 433 m, 6 north-south of 250 m
            double s = rv->GetValue(0.0, totalLen);
            int ix;
            int iy;
            int d;
            double frac;
            if (s < 6 * gridX)
            {
                const int e = static_cast<int>(s / gridX);
                ix = e % 2;
                iy = e / 2;
                d = 0;
                frac = s / gridX - e;
            }
            else
            {
                s -= 6 * gridX;
                const int e = static_cast<int>(s / gridY);
                ix = e % 3;
                iy = e / 3;
                d = 1;
                frac = s / gridY - e;
            }
            frac = std::clamp(frac, 0.001, 0.999);
            double x = (ix - 1) * gridX + DX[d] * frac * gridX;
            double y = (iy - 1) * gridY + DY[d] * frac * gridY;
            int nx = ix + DX[d]; // node ahead
            int ny = iy + DY[d];
            if (rv->GetValue() < 0.5)
            {
                d = (d + 2) % 4; // drive the other way: the node ahead is the edge's start
                nx = ix;
                ny = iy;
            }
            Ptr<WaypointMobilityModel> wm = CreateObject<WaypointMobilityModel>();
            double t = 0.0;
            wm->AddWaypoint(Waypoint(Seconds(t), Vector(x, y, ueHeight)));
            while (t < simTime + 5.0)
            {
                const double tx = (nx - 1) * gridX;
                const double ty = (ny - 1) * gridY;
                t += std::hypot(tx - x, ty - y) / speed;
                x = tx;
                y = ty;
                wm->AddWaypoint(Waypoint(Seconds(t), Vector(x, y, ueHeight)));
                const int cand[3] = {d, (d + 1) % 4, (d + 3) % 4}; // straight, left, right
                const double w[3] = {0.5, 0.25, 0.25};
                double sum = 0.0;
                for (int c = 0; c < 3; ++c)
                {
                    sum += hasEdge(nx, ny, cand[c]) ? w[c] : 0.0;
                }
                int nd = (d + 2) % 4; // dead end (does not occur in this grid)
                if (sum > 0.0)
                {
                    double r = rv->GetValue(0.0, sum);
                    for (int c = 0; c < 3; ++c)
                    {
                        if (!hasEdge(nx, ny, cand[c]))
                        {
                            continue;
                        }
                        nd = cand[c];
                        if (r < w[c])
                        {
                            break;
                        }
                        r -= w[c];
                    }
                }
                d = nd;
                nx += DX[d];
                ny += DY[d];
            }
            ueNodes.Get(u)->AggregateObject(wm);
        }
        BuildingsHelper::Install(gnbNodes);
        BuildingsHelper::Install(ueNodes);
    }
    else
    {
    std::ostringstream speedRv;
    speedRv << "ns3::ConstantRandomVariable[Constant=" << speed << "]";
    Ptr<UniformDiscPositionAllocator> uePos = CreateObject<UniformDiscPositionAllocator>();
    uePos->SetAttribute("rho", DoubleValue(0.95 * discRadius));
    uePos->SetAttribute("Z", DoubleValue(ueHeight));
    uePos->AssignStreams(100);
    MobilityHelper ueMobility;
    ueMobility.SetMobilityModel("ns3::RandomDirectionDisc2dMobilityModel",
                                "Radius",
                                DoubleValue(discRadius),
                                "Speed",
                                StringValue(speedRv.str()),
                                "Pause",
                                StringValue("ns3::ConstantRandomVariable[Constant=0.0]"));
    ueMobility.SetPositionAllocator(uePos);
    ueMobility.Install(ueNodes);
    ueMobility.AssignStreams(ueNodes, 200);
    }

    // ---- channel ----------------------------------------------------------------
    Ptr<NrChannelHelper> channelHelper = CreateObject<NrChannelHelper>();
    channelHelper->ConfigureFactories(scenario, condition, "ThreeGpp");
    channelHelper->SetPathlossAttribute("ShadowingEnabled", BooleanValue(shadowing));
    CcBwpCreator ccBwpCreator;
    CcBwpCreator::SimpleOperationBandConf bandConf(frequency, bandwidth, static_cast<uint8_t>(1));
    OperationBandInfo band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);
    uint8_t chFlags = NrChannelHelper::INIT_PROPAGATION;
    if (fading)
    {
        chFlags |= NrChannelHelper::INIT_FADING;
    }
    channelHelper->AssignChannelsToBands({band}, chFlags);
    BandwidthPartInfoPtrVector allBwps = CcBwpCreator::GetAllBwps({band});

    // ---- devices ----------------------------------------------------------------
    NetDeviceContainer gnbDevs = nrHelper->InstallGnbDevice(gnbNodes, allBwps);
    NetDeviceContainer ueDevs = nrHelper->InstallUeDevice(ueNodes, allBwps);

    for (uint32_t i = 0; i < gnbDevs.GetN(); ++i)
    {
        Ptr<NrGnbNetDevice> gnb = gnbDevs.Get(i)->GetObject<NrGnbNetDevice>();
        NS_ABORT_MSG_IF(gnb->GetCellId() != i + 1, "unexpected cell id numbering");
        if (P.roam)
        {
            PointerValue pv;
            gnb->GetAttribute("NrHandoverAlgorithm", pv);
            Ptr<RoamA3Algorithm> a = pv.Get<RoamA3Algorithm>();
            NS_ABORT_MSG_IF(!a, "handover algorithm is not a RoamA3Algorithm");
            a->SetGnbRrc(gnb->GetRrc());
        }
    }

    // ---- core network, remote host, IP -----------------------------------------
    Ptr<Node> pgw = epcHelper->GetPgwNode();
    NodeContainer remoteHostContainer;
    remoteHostContainer.Create(1);
    Ptr<Node> remoteHost = remoteHostContainer.Get(0);
    InternetStackHelper internet;
    internet.Install(remoteHostContainer);
    PointToPointHelper p2ph;
    p2ph.SetDeviceAttribute("DataRate", DataRateValue(DataRate("100Gb/s")));
    p2ph.SetDeviceAttribute("Mtu", UintegerValue(1500));
    p2ph.SetChannelAttribute("Delay", TimeValue(MilliSeconds(10)));
    NetDeviceContainer internetDevices = p2ph.Install(pgw, remoteHost);
    Ipv4AddressHelper ipv4h;
    ipv4h.SetBase("1.0.0.0", "255.0.0.0");
    ipv4h.Assign(internetDevices);
    Ipv4StaticRoutingHelper routingHelper;
    Ptr<Ipv4StaticRouting> remoteHostRouting =
        routingHelper.GetStaticRouting(remoteHost->GetObject<Ipv4>());
    remoteHostRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"), Ipv4Mask("255.0.0.0"), 1);
    internet.Install(ueNodes);
    Ipv4InterfaceContainer ueIfaces = epcHelper->AssignUeIpv4Address(ueDevs);
    for (uint32_t u = 0; u < ueNodes.GetN(); ++u)
    {
        Ptr<Ipv4StaticRouting> r = routingHelper.GetStaticRouting(ueNodes.Get(u)->GetObject<Ipv4>());
        r->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);
    }
    nrHelper->AddX2Interface(gnbNodes);
    nrHelper->AttachToClosestGnb(ueDevs, gnbDevs);

    // ---- service classes: exact shares for 20 UEs (4/4/3/6/3), shuffled with the seed ------
    std::vector<int> svcList;
    auto assignServices = [&]() {
        for (int k = 0; k < 5; ++k)
        {
            const uint32_t cnt =
                static_cast<uint32_t>(std::lround(SVC[k].n20 * static_cast<double>(nUe) / 20.0));
            for (uint32_t i = 0; i < cnt; ++i)
            {
                svcList.push_back(k);
            }
        }
        while (svcList.size() < nUe)
        {
            svcList.push_back(3);
        }
        svcList.resize(nUe);
        Ptr<UniformRandomVariable> svcRv = CreateObject<UniformRandomVariable>();
        svcRv->SetStream(7100);
        for (uint32_t i = nUe - 1; i > 0; --i)
        {
            const uint32_t j = svcRv->GetInteger(0, i);
            std::swap(svcList[i], svcList[j]);
        }
    };
    if (traffic != "light")
    {
        assignServices(); // the traffic profile depends on the class
    }

    // ---- traffic ---------------------------------------------------------------------
    // light: the same small downlink flow for every UE (--udpInterval, --udpPacketSize).
    // mixed: one downlink profile per service class; the rates are the rate demands of the
    //        service table for video call (2 Mbit/s), gaming (1), streaming (5) and web
    //        (1 Mbit/s); voice is one 60-byte packet per 20 ms (24 kbit/s). Packet sizes are
    //        assumptions. Uplink flows exist (--ulTraffic=1) but are off by default.
    // full:  every UE is offered --fullRate Mbit/s downlink, more than a cell can carry.
    struct Prof
    {
        double dlMs;
        uint32_t dlBytes;
        double ulMs; // 0 = no uplink flow
        uint32_t ulBytes;
    };
    const Prof mixedProf[5] = {{20.0, 60, 20.0, 60},     // voice
                               {5.0, 1250, 10.0, 1250},  // video call, 2 Mbit/s down
                               {4.0, 500, 10.0, 100},    // gaming, 1 Mbit/s down, 80 kbit/s up
                               {2.0, 1250, 0.0, 0},      // streaming, 5 Mbit/s down
                               {10.0, 1250, 0.0, 0}};    // web / background, 1 Mbit/s down
    g_lastRx.assign(nUe, -1.0);
    for (auto& h : C.cDelayHist)
    {
        h.assign(5001, 0);
    }
    Ptr<UniformRandomVariable> startRv = CreateObject<UniformRandomVariable>();
    startRv->SetStream(7000);
    const uint16_t dlPortBase = 10000;
    const uint16_t ulPortBase = 20000;
    Ipv4Address remoteHostAddr = remoteHost->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
    for (uint32_t u = 0; u < ueNodes.GetN(); ++u)
    {
        Prof pr{udpIntervalMs, udpPacketSize, 0.0, 0};
        if (traffic == "mixed")
        {
            pr = mixedProf[svcList[u]];
            if (!ulTraffic)
            {
                pr.ulMs = 0.0;
            }
        }
        else if (traffic == "full")
        {
            pr = Prof{1400.0 * 8.0 / (fullRateMbps * 1e3), 1400, 0.0, 0};
        }
        const uint16_t port = dlPortBase + u;
        UdpClientHelper client(ueIfaces.GetAddress(u), port);
        client.SetAttribute("Interval", TimeValue(MilliSeconds(pr.dlMs)));
        client.SetAttribute("MaxPackets", UintegerValue(100000000));
        client.SetAttribute("PacketSize", UintegerValue(pr.dlBytes));
        ApplicationContainer c = client.Install(remoteHost);
        PacketSinkHelper sink("ns3::UdpSocketFactory",
                              InetSocketAddress(Ipv4Address::GetAny(), port));
        ApplicationContainer s = sink.Install(ueNodes.Get(u));
        c.Get(0)->TraceConnectWithoutContext("Tx", MakeBoundCallback(&TxTrace, u));
        s.Get(0)->TraceConnectWithoutContext("Rx", MakeBoundCallback(&RxTrace, u));

        Ptr<NrQosRule> rule = Create<NrQosRule>();
        NrQosRule::PacketFilter dlpf;
        dlpf.localPortStart = port;
        dlpf.localPortEnd = port;
        rule->Add(dlpf);
        ApplicationContainer uc;
        ApplicationContainer us;
        if (pr.ulMs > 0.0)
        {
            const uint16_t uport = ulPortBase + u;
            UdpClientHelper ulClient(remoteHostAddr, uport);
            ulClient.SetAttribute("Interval", TimeValue(MilliSeconds(pr.ulMs)));
            ulClient.SetAttribute("MaxPackets", UintegerValue(100000000));
            ulClient.SetAttribute("PacketSize", UintegerValue(pr.ulBytes));
            uc = ulClient.Install(ueNodes.Get(u));
            PacketSinkHelper ulSink("ns3::UdpSocketFactory",
                                    InetSocketAddress(Ipv4Address::GetAny(), uport));
            us = ulSink.Install(remoteHost);
            uc.Get(0)->TraceConnectWithoutContext("Tx", MakeBoundCallback(&UlTxTrace, u));
            us.Get(0)->TraceConnectWithoutContext("Rx", MakeBoundCallback(&UlRxTrace, u));
            NrQosRule::PacketFilter ulpf;
            ulpf.remotePortStart = uport;
            ulpf.remotePortEnd = uport;
            rule->Add(ulpf);
        }
        NrQosFlow flow(NrQosFlow::NGBR_VIDEO_TCP_DEFAULT);
        nrHelper->ActivateDedicatedQosFlow(ueDevs.Get(u), flow, rule);

        s.Start(Seconds(0.3));
        c.Start(Seconds(0.4 + startRv->GetValue(0.0, 0.1)));
        c.Stop(Seconds(simTime - 0.5));
        if (pr.ulMs > 0.0)
        {
            us.Start(Seconds(0.3));
            uc.Start(Seconds(0.5 + startRv->GetValue(0.0, 0.1)));
            uc.Stop(Seconds(simTime - 0.5));
        }
    }

    nrHelper->AssignStreams({.assignEpc = true,
                             .remoteHostNodes = remoteHostContainer,
                             .ueNodes = ueNodes,
                             .gnbNodes = gnbNodes,
                             .beamformingHelper = bfHelper,
                             .gnbDevs = gnbDevs,
                             .ueDevs = ueDevs});

    // ---- path-loss-only radio map (best-server regions) ---------------------------
    {
        std::string lossType = "ns3::ThreeGppUmaPropagationLossModel";
        if (scenario == "UMi")
        {
            lossType = "ns3::ThreeGppUmiStreetCanyonPropagationLossModel";
        }
        else if (scenario == "RMa")
        {
            lossType = "ns3::ThreeGppRmaPropagationLossModel";
        }
        ObjectFactory lf(lossType);
        lf.Set("Frequency", DoubleValue(frequency));
        lf.Set("ShadowingEnabled", BooleanValue(false));
        lf.Set("BuildingPenetrationLossesEnabled", BooleanValue(false));
        Ptr<ThreeGppPropagationLossModel> lm = lf.Create<ThreeGppPropagationLossModel>();
        Ptr<ChannelConditionModel> ccm;
        if (condition == "LOS")
        {
            ccm = CreateObject<AlwaysLosChannelConditionModel>();
        }
        else
        {
            ccm = CreateObject<NeverLosChannelConditionModel>();
        }
        lm->SetChannelConditionModel(ccm);
        g_map.loss = lm;
        g_map.ueHeight = ueHeight;
        g_map.gnb.resize(nGnb + 1);
        g_map.gnbPos.resize(nGnb + 1);
        NodeContainer probeNodes;
        probeNodes.Create(nGnb + 1);
        for (uint32_t k = 1; k <= nGnb; ++k)
        {
            Ptr<ConstantPositionMobilityModel> m = CreateObject<ConstantPositionMobilityModel>();
            m->SetPosition(gnbXyz[k - 1]);
            probeNodes.Get(k)->AggregateObject(m);
            g_map.gnb[k] = m;
            g_map.gnbPos[k] = gnbXyz[k - 1];
        }
        Ptr<ConstantPositionMobilityModel> pm = CreateObject<ConstantPositionMobilityModel>();
        probeNodes.Get(0)->AggregateObject(pm);
        g_map.probe = pm;
    }
    // is the best-server map of the configured model identical to the Voronoi diagram?
    uint32_t mapPts = 0;
    uint32_t mapDiff = 0;
    for (double x = -discRadius; x <= discRadius; x += discRadius / 40.0)
    {
        for (double y = -discRadius; y <= discRadius; y += discRadius / 40.0)
        {
            mapPts++;
            if (g_map.Best(x, y) != g_map.Nearest(x, y))
            {
                mapDiff++;
            }
        }
    }

    g_hht.Init(nGnb, (urban ? gridX : discRadius) + 100.0, P.binRes);

    if (urban)
    {
        // description of the layout for the log: sites, and how much of the road network has a
        // line of sight to each site, to at least one site, and to its nearest site
        std::cout << "urban layout: sites";
        for (uint32_t k = 1; k <= nGnb; ++k)
        {
            std::cout << " " << k << "=(" << g_map.gnbPos[k].x << "," << g_map.gnbPos[k].y << ")";
        }
        std::vector<uint32_t> losK(nGnb + 1, 0);
        uint32_t pts = 0;
        uint32_t any = 0;
        uint32_t nearest = 0;
        auto probe = [&](double x, double y) {
            pts++;
            bool a = false;
            const uint16_t nk = g_map.Nearest(x, y);
            for (uint32_t k = 1; k <= nGnb; ++k)
            {
                bool blocked = false;
                for (auto b = BuildingList::Begin(); b != BuildingList::End(); ++b)
                {
                    blocked = blocked || (*b)->IsIntersect(g_map.gnbPos[k], Vector(x, y, ueHeight));
                }
                if (!blocked)
                {
                    losK[k]++;
                    a = true;
                    if (k == nk)
                    {
                        nearest++;
                    }
                }
            }
            any += a ? 1 : 0;
        };
        for (int k = -1; k <= 1; ++k)
        {
            for (double x = -gridX; x <= gridX; x += 1.0)
            {
                probe(x, k * gridY);
            }
            for (double y = -gridY; y <= gridY; y += 1.0)
            {
                probe(k * gridX, y);
            }
        }
        std::cout << "; road points " << pts << ", LOS to at least one site " << 100.0 * any / pts
                  << " %, LOS to the nearest site " << 100.0 * nearest / pts << " %, per site";
        for (uint32_t k = 1; k <= nGnb; ++k)
        {
            std::cout << " " << 100.0 * losK[k] / pts;
        }
        std::cout << " %" << std::endl;
    }

    // ---- UE state, service classes, traces ---------------------------------------
    if (traffic == "light")
    {
        assignServices();
    }

    const std::string prefix = outDir + "/" + tag;
    if (events)
    {
        g_attCsv.open(prefix + "_att.csv");
        NS_ABORT_MSG_IF(!g_attCsv.is_open(), "cannot write to " << prefix << "_att.csv");
        g_attCsv << "t_cmd,ue,imsi,svc,src,tgt,t_exec,t_final,reason,dwell,n,gain_eval,gain_obs,"
                    "resc_eval,resc_obs,outcome_eval,outcome_obs,pp,x,y,margin,in_window\n";
        g_rlfCsv.open(prefix + "_rlf.csv");
        g_rlfCsv << "time_s,ue,imsi,cell,cause,old_state,t310_elapsed_ms,ms_since_last_ho_ok,"
                    "handled,x,y,in_window\n";
    }
    if (measCsv)
    {
        g_measCsv.open(prefix + "_meas.csv");
        g_measCsv << "time_s,ue,cell,rsrp_l1_dbm,rsrp_l3_dbm,serving\n";
    }

    g_ue.resize(nUe);
    for (uint32_t u = 0; u < nUe; ++u)
    {
        Ptr<NrUeNetDevice> ue = ueDevs.Get(u)->GetObject<NrUeNetDevice>();
        UeState& s = g_ue[u];
        s.idx = u;
        s.imsi = ue->GetImsi();
        s.svc = svcList[u];
        s.node = ueNodes.Get(u);
        s.rrc = ue->GetRrc();
        s.l1.assign(nGnb + 1, NAN);
        s.l3.assign(nGnb + 1, NAN);
        s.rowBuf.assign(nGnb + 1, NAN);
        s.margin.assign(nGnb + 1, NAN);
        g_imsiToUe[s.imsi] = u;
        s.rrc->TraceConnectWithoutContext("HandoverEndOk", MakeCallback(&UeHandoverEndOk));
        s.rrc->TraceConnectWithoutContext("RadioLinkFailureCause",
                                          MakeCallback(&UeRadioLinkFailureCause));
        NrHelper::GetUePhy(ueDevs.Get(u), 0)
            ->TraceConnectWithoutContext("ReportUeMeasurements",
                                         MakeBoundCallback(&UeMeasurement, u));
        s.rrc->TraceConnectWithoutContext("StateTransition", MakeBoundCallback(&UeRrcState, u));
    }
    g_discSince.assign(nUe, 0.0); // not connected at the start
    for (uint32_t i = 0; i < gnbDevs.GetN(); ++i)
    {
        NrHelper::GetGnbPhy(gnbDevs.Get(i), 0)
            ->TraceConnectWithoutContext("SlotDataStats", MakeCallback(&SlotData));
    }
    for (uint32_t i = 0; i < gnbDevs.GetN(); ++i)
    {
        Ptr<NrGnbRrc> rrc = gnbDevs.Get(i)->GetObject<NrGnbNetDevice>()->GetRrc();
        rrc->TraceConnectWithoutContext("HandoverStart", MakeCallback(&GnbHandoverStart));
    }
    Simulator::Schedule(Seconds(1.0), &HhtDecayTick);

    // ---- run ---------------------------------------------------------------------
    std::cout << "ho-scenario: tag=" << tag << " rule=" << P.rule << " hyst=" << hyst
              << " ttt=" << tttMs << " h0=" << P.h0 << " etaH=" << P.etaH << " etaL=" << P.etaL
              << " etaA=" << P.etaA << " etaS=" << P.etaS << " mCap=" << P.mCap
              << " traffic=" << traffic << " nUe=" << nUe
              << " isd=" << isd << " speed=" << speed << " simTime=" << simTime
              << " discard=" << P.discard << " fading=" << fading << " rngRun=" << rngRun
              << " mapDiff=" << mapDiff << "/" << mapPts << std::endl;

    Simulator::Stop(Seconds(simTime));
    auto t0 = std::chrono::steady_clock::now();
    if (progressStep > 0)
    {
        Simulator::Schedule(Seconds(progressStep), &Progress, progressStep, t0);
    }
    Simulator::Run();
    const double wall =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    for (uint32_t u = 0; u < nUe; ++u)
    {
        if (g_discSince[u] >= 0.0)
        {
            C.outageS += std::max(0.0, simTime - std::max(g_discSince[u], P.discard));
        }
    }

    // ---- censored events at the end of the run --------------------------------------
    for (auto& s : g_ue)
    {
        if (s.inflight)
        {
            if (InWindow(s.tCmd))
            {
                C.out[OUT_CENS]++;
            }
            s.inflight = false;
        }
        Finalize(s, "end");
    }

    // ---- metrics ----------------------------------------------------------------------
    const double ueMin = nUe * (simTime - P.discard) / 60.0;
    const uint64_t classified = C.out[0] + C.out[1] + C.out[2] + C.out[3];
    const uint64_t failures = C.rlfT310 + C.rlfLateCmd + C.rlfDuringHo + C.rlfRlc;
    const uint64_t sumOut = classified + C.out[OUT_CENS] + C.unresolved;
    auto ratio = [](double a, double b) { return b > 0 ? a / b : 0.0; };

    std::ostringstream js;
    js << std::setprecision(8);
    js << "{\"tag\":\"" << tag << "\",\"rule\":\"" << P.rule << "\",\"hyst\":" << hyst
       << ",\"ttt_ms\":" << tttMs << ",\"h0\":" << P.h0 << ",\"etaH\":" << P.etaH
       << ",\"etaL\":" << P.etaL << ",\"etaA\":" << P.etaA << ",\"etaS\":" << P.etaS
       << ",\"mCap\":" << P.mCap << ",\"nUe\":" << nUe << ",\"isd\":" << isd
       << ",\"speed\":" << speed << ",\"simTime\":" << simTime << ",\"discard\":" << P.discard
       << ",\"fading\":" << (fading ? 1 : 0) << ",\"rngRun\":" << rngRun
       << ",\"ue_min\":" << ueMin << ",\"attempts\":" << C.attempts
       << ",\"executed\":" << C.executed << ",\"useful\":" << C.out[OUT_USEFUL]
       << ",\"unnecessary\":" << C.out[OUT_UNNEC] << ",\"early\":" << C.out[OUT_EARLY]
       << ",\"late\":" << C.out[OUT_LATE] << ",\"censored\":" << C.out[OUT_CENS]
       << ",\"unresolved\":" << C.unresolved << ",\"sum_outcomes\":" << sumOut
       << ",\"late_cmd\":" << C.lateCmd << ",\"late_exec\":" << C.lateExec
       << ",\"late_other\":" << C.lateOther << ",\"rlf_no_pending\":" << C.rlfNoPending
       << ",\"rlf_t310\":" << C.rlfT310 << ",\"rlf_late_cmd\":" << C.rlfLateCmd
       << ",\"rlf_during_ho\":" << C.rlfDuringHo << ",\"rlf_rlc\":" << C.rlfRlc
       << ",\"rlf_other\":" << C.rlfOther << ",\"failures\":" << failures
       << ",\"pp\":" << C.pp << ",\"pp_un\":" << C.ppUn << ",\"un_short\":" << C.cShort
       << ",\"un_gain\":" << C.cGain << ",\"rescue\":" << C.rescue
       << ",\"obs_useful\":" << C.obs[0] << ",\"obs_unnecessary\":" << C.obs[1]
       << ",\"obs_early\":" << C.obs[2] << ",\"obs_late\":" << C.obs[3]
       << ",\"ho_pm\":" << ratio(C.attempts, ueMin) << ",\"uho_pm\":" << ratio(C.out[OUT_UNNEC], ueMin)
       << ",\"fail_pm\":" << ratio(failures, ueMin) << ",\"uhr\":" << ratio(C.out[OUT_UNNEC], classified)
       << ",\"hof_rate\":" << ratio(C.out[OUT_EARLY] + C.out[OUT_LATE], classified)
       << ",\"pp_ratio\":" << ratio(C.pp, C.attempts)
       << ",\"dwell_s\":" << ratio(C.dwellSum, C.out[0] + C.out[1] + C.out[2])
       << ",\"tx_pkts\":" << C.txPkts << ",\"rx_pkts\":" << C.rxPkts
       << ",\"delivery\":" << ratio(C.rxPkts, C.txPkts)
       << ",\"sinr_db\":" << ratio(C.sinrSum, C.sinrN)
       << ",\"mean_margin\":" << ratio(C.marginSum, C.marginN)
       << ",\"mean_H\":" << ratio(C.hSum, C.marginN) << ",\"mean_L\":" << ratio(C.lSum, C.marginN)
       << ",\"mean_df\":" << ratio(C.dfSum, C.marginN)
       << ",\"mean_gamma\":" << ratio(C.gammaSum, C.marginN / std::max<uint32_t>(nGnb - 1, 1))
       << ",\"table_updates\":" << g_hht.m_updates << ",\"table_mass\":" << g_hht.RouteMass();
    for (int k = 0; k < 5; ++k)
    {
        js << ",\"n_" << SVC[k].key << "\":" << C.svcN[k] << ",\"un_" << SVC[k].key
           << "\":" << C.svcUn[k];
    }
    js << ",\"all_attempts\":" << C.allAttempts << ",\"all_rlf\":" << C.allRlf
       << ",\"map_diff\":" << mapDiff << ",\"map_pts\":" << mapPts << ",\"wall_s\":" << wall
       << ",\"sim_per_wall\":" << simTime / wall << ",\"scen\":\"" << scen << "\",\"los_serving\":"
       << (C.losN ? static_cast<double>(C.losServ) / C.losN : -1.0);
    // ---- fields added later (appended, so that earlier columns keep their meaning) ----
    js << ",\"traffic\":\"" << traffic << "\""
       << ",\"prepDelay_ms\":" << prepDelayMs << ",\"t310_ms\":" << t310Ms << ",\"n310\":" << n310
       << ",\"outage_s_pm\":" << ratio(C.outageS, ueMin)
       << ",\"occ_slots\":" << ratio(C.slotActive, C.slotN)
       << ",\"occ_prb\":" << ratio(C.regUsed, C.regAvail);
    for (int k = 0; k < 5; ++k)
    {
        const double um = std::max<double>(1e-9, (simTime - P.discard) / 60.0 *
                                                     std::count(svcList.begin(), svcList.end(), k));
        // 95th percentile of the delay from the 1 ms histogram
        uint64_t tot = 0;
        for (auto v : C.cDelayHist[k])
        {
            tot += v;
        }
        double p95 = 0.0;
        uint64_t acc = 0;
        for (size_t b = 0; b < C.cDelayHist[k].size() && tot > 0; ++b)
        {
            acc += C.cDelayHist[k][b];
            if (acc >= 0.95 * tot)
            {
                p95 = (b + 0.5) / 1000.0;
                break;
            }
        }
        const std::string key(SVC[k].key);
        js << ",\"ues_" << key << "\":" << std::count(svcList.begin(), svcList.end(), k)
           << ",\"deliv_" << key << "\":" << ratio(C.cRx[k], C.cTx[k])
           << ",\"delay_ms_" << key << "\":" << 1000.0 * ratio(C.cDelaySum[k], C.cRx[k])
           << ",\"delay95_ms_" << key << "\":" << 1000.0 * p95
           << ",\"stall100_pm_" << key << "\":" << C.cGap100[k] / um
           << ",\"stall500_pm_" << key << "\":" << C.cGap500[k] / um
           << ",\"ul_deliv_" << key << "\":" << (C.cUlTx[k] ? ratio(C.cUlRx[k], C.cUlTx[k]) : -1.0);
    }
    js << "}";

    std::cout << "\n==== summary (window " << P.discard << ".." << simTime << " s) ====\n"
              << "attempts=" << C.attempts << " executed=" << C.executed
              << " useful=" << C.out[0] << " unnecessary=" << C.out[1] << " early=" << C.out[2]
              << " late=" << C.out[3] << " censored=" << C.out[4]
              << " unresolved=" << C.unresolved << " (sum=" << sumOut << ")\n"
              << "RLF: T310=" << C.rlfT310 << " late_cmd=" << C.rlfLateCmd
              << " during_ho=" << C.rlfDuringHo << " rlc=" << C.rlfRlc << " other=" << C.rlfOther
              << " no_pending=" << C.rlfNoPending << "\n"
              << "HO/UE-min=" << ratio(C.attempts, ueMin) << " UHO/UE-min="
              << ratio(C.out[1], ueMin) << " fail/UE-min=" << ratio(failures, ueMin)
              << " pp=" << C.pp << " delivery=" << ratio(C.rxPkts, C.txPkts)
              << " sinr=" << ratio(C.sinrSum, C.sinrN) << " dB\n"
              << "wall=" << wall << " s speed=" << simTime / wall << " sim s per wall s\n";

    std::ofstream jf(prefix + ".json.tmp");
    NS_ABORT_MSG_IF(!jf.is_open(), "cannot write to " << prefix << ".json.tmp (use C:/... paths)");
    jf << js.str() << "\n";
    jf.close();
    std::remove((prefix + ".json").c_str());
    std::rename((prefix + ".json.tmp").c_str(), (prefix + ".json").c_str());

    if (g_attCsv.is_open())
    {
        g_attCsv.close();
        g_rlfCsv.close();
    }
    if (g_measCsv.is_open())
    {
        g_measCsv.close();
    }
    for (auto& s : g_ue)
    {
        s.node = nullptr;
        s.rrc = nullptr;
    }
    g_ue.clear();
    g_map = RadioMap();
    Simulator::Destroy();
    return 0;
}
