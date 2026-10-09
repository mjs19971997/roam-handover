# ROAM: Mitigating Unnecessary Handovers in Dense 5G Networks

Code for the paper *"ROAM: Mitigating Unnecessary Handovers in Dense 5G Networks With an
Outcome Memory and a Path-Overlap Margin"* by Mostafa Jalili Sanjarani, Yasser Elmi Sola,
Hesam Hasanpour and Ali Akbar Neghabi (Islamic Azad University, Sabzevar).

## What this is

The repository contains three things:

- an **outcome-based definition of unnecessary handovers**: a handover is labelled by what
  happened after it (time-of-stay, quality gain over the counterfactual source cell, failure),
  not by any quantity that a decision rule optimises;
- the **ROAM decision layer**: 3GPP Event A3 whose margin is set per user and per neighbour
  from a route/location outcome table, a path-overlap term and a 5QI service weight;
- a **load-coupled system-level simulator** together with **seven baseline decision rules**,
  all acting through the same measurement and trigger machinery.

## Repository layout

```
roam/                       the library
  simulator.py              SimParams, RadioEnv, gen_traj, assign_services, simulate, area_frac
  policies.py               BaseLayer, RouteTable, LocationTable, Base, A3, ROAM and the baselines
  radiomap.py               RadioMap: cell positions and path-loss fits from drive-test data
  mobility.py               the five mobility profiles
  services.py               the five 5QI service classes
experiments/
  common.py                 paths, environments (get_env), base layer (get_fw), scenario()
  runner.py                 parallel job runner
  tune.py                   equal-budget tuning grid            -> results/tune.csv
  select_configs.py         one configuration per method        -> results/tuned.json, tune_summary.csv
  run_experiments.py        the test experiment blocks          -> results/exp_<block>.csv
  analyze.py                statistics                          -> results/summary.json
  make_figures.py           result figures                      -> figures/fig_*.pdf (also .svg and .png)
  make_concept_figures.py   illustrative figures                -> figures/fig_*.pdf (also .svg and .png)
  data_stats.py             statistics of the environments      -> results/data_stats.json
  plotstyle.py               matplotlib style
examples/quickstart.py      small A3-versus-ROAM demo
data/synthetic/             three synthetic dense-urban layouts (20 / 40 / 60 cells)
data/drive_tests/           place for the three measured drive-test traces (not distributed, see below)
results/                    result files
ns3/                        validation in ns-3 (5G-LENA): plan, per-run results, analysis scripts (see ns3/README.md)
figures/                    figures
docs/                       additional documentation
run_all.sh                  the full pipeline
```

A Persian code guide is in docs/ (`docs/CODE_GUIDE.md`, and the same content as a single page in `docs/code_guide.html`).

## Installation

Python 3.10 or newer.

```
git clone https://github.com/mjs19971997/roam-handover.git
cd roam-handover
pip install -r requirements.txt
```

`requirements.txt` pins the versions the experiments were run with (Python 3.12). The scripts
are run from a checkout; nothing needs to be installed as a package.

## Quick start

```
python examples/quickstart.py
```

This builds the 40-cell layout, moves 60 users on the street grid for 60 s and prints a small
comparison of A3 and ROAM (both with explicit parameters). It takes about a minute.

## Reproducing the paper

```
python experiments/tune.py                      # results/tune.csv
python experiments/select_configs.py            # results/tuned.json, results/tune_summary.csv
python experiments/run_experiments.py profiles load density real ablation hht nonstat sens thresh posthoc tempo
                                                # results/exp_<block>.csv
python experiments/analyze.py                   # results/summary.json
python experiments/make_figures.py              # figures/fig_*.pdf (also .svg and .png)
python experiments/make_concept_figures.py      # figures/fig_*.pdf (also .svg and .png) (no results needed)
python experiments/data_stats.py                # results/data_stats.json
```

`bash run_all.sh` runs the pipeline from tuning to the result figures.

- **Tuning** runs 24 configurations of each of the eight methods on validation traces (UDN-40,
  300 users, street-grid and highway profiles, seeds 101 and 102, 120 s). `select_configs.py`
  then applies one rule to every method: among the configurations whose mobility-failure rate
  does not exceed that of the reference A3 (3 dB, TTT 0.3 s), take the one with the fewest
  unnecessary handovers per user-minute; if none meets the budget, take the one with the lowest
  failure rate. Test seeds (1, 2, ...) are never used for tuning.
- **Run time** on 8 cores: tuning about 1.5 h, all test blocks about 10 to 14 h. Blocks can be
  run one at a time; `python experiments/run_experiments.py` without arguments lists them.
- **Workers**: all cores but one by default; set `ROAM_PROCS` to change it.
- **Output directory**: `results/`, or the directory named by `ROAM_RESULTS`.
- **Determinism**: all random streams are seeded, and every method of a (scenario, seed) pair
  sees the same trajectories, services and shadowing. Results are reproducible for a given set
  of library versions; the only non-deterministic output column is `dec_us` (decision time).
- The learning methods (ROAM, ST-CMAB, Cluster-RL) are warmed up for 240 s on independent
  traces before every test run unless a block says otherwise.

In the result files the method label `Proposed` denotes ROAM.

## Main results

Test seeds 1–8, 40-cell layout, 300 users; every method tuned with the same 24-configuration budget and selection rule. Rates are per user-minute. Produced by `experiments/analyze.py` from `results/exp_profiles.csv`.

| Mobility | Unnecessary HO, tuned A3 | Unnecessary HO, ROAM | Reduction | Failures, A3 | Failures, ROAM | Delivered/demand, ROAM − A3 [pts] |
|---|---|---|---|---|---|---|
| Pedestrian | 0.42 | 0.27 | 35% | 0.045 | 0.055 | -1.2 |
| Vehicular, open area | 1.46 | 0.87 | 40% | 0.34 | 0.34 | -0.6 |
| Vehicular, street grid | 1.60 | 0.86 | 46% | 0.40 | 0.34 | -1.5 |
| Highway | 4.11 | 1.57 | 62% | 0.50 | 0.43 | -1.4 |
| High-speed train | 9.85 | 4.56 | 54% | 1.66 | 1.77 | -5.0 |

Over all five profiles ROAM removes 53% of the unnecessary handovers of tuned A3; the change in the mobility-failure rate is -0.7% (Wilcoxon p = 0.08). The cost is a lower delivered-to-demanded rate. The learned outcome table is better than a constant offset on the highway but not on the street grid or in the open area, and not at all when shadowing is drawn independently per user (`exp_tempo.csv`). The paper discusses these results and their limits.

## Validation in ns-3

The decision rule was also implemented in ns-3 (release 3.48) with the 5G-LENA NR module
(v5.1) and compared with a tuned Event A3 rule on 7 gNBs with 20 terminals, under a plan
written before the runs (`ns3/PLAN.md`). Rates are per UE-minute, 120 paired runs per
environment.

| Environment | Unnecessary HO, tuned A3 | Unnecessary HO, ROAM | Change | Failures, A3 | Failures, ROAM |
|---|---|---|---|---|---|
| Urban grid (3GPP TR 37.885, blockage by buildings) | 2.220 | 1.390 | -37.4% | 0.031 | 0.098 |
| Open area (shadowing drawn per link) | 0.715 | 0.779 | +9.0% | 0.004 | 0.015 |

In the urban grid the reduction is reproduced, at 37% against 53% in the simulator of this
repository, and it comes with about three times the failure rate of A3; compared with the A3
configuration that fails no more often, ROAM still has 0.62 ± 0.27 fewer unnecessary
handovers per UE-minute. In the open area ROAM has no advantage. `ns3/README.md` describes the
set-up, the protocol, the one change made to the NR module and all stages; the plan, the
per-run results and the analysis scripts are in `ns3/`. The ns-3 scenario program is available
from the authors on request.

## Experiment blocks

| Block | Content |
|---|---|
| `profiles` | Central comparison: all eight methods on the five mobility profiles (UDN-40, 300 users, 240 s, 8 seeds). |
| `load` | All methods with 100, 500 and 700 users on the street grid (6 seeds). |
| `density` | All methods on the 20-cell and 60-cell layouts (street grid, 300 users, 6 seeds). |
| `real` | All methods on the three measured drive-test routes (60 users following the route, 6 seeds). Needs the traces. |
| `ablation` | Eleven ROAM variants: terms added to the base rule one by one and removed from the full method (street, highway, vehicular). |
| `hht` | Role of the outcome table: warm start, cold start, frozen table, table fixed at its prior, no table; with 20 s time curves; tuned A3 as reference. |
| `nonstat` | Non-stationary environment: hotspots, blockage and shadowing field re-drawn at 240 s of a 720 s run; no forgetting versus forgetting time constants of 600 s and 150 s. |
| `sens` | One-at-a-time sensitivity of ROAM to its parameters, to heading and speed estimation errors, and to the shadowing model (4 seeds). |
| `thresh` | All methods with the outcome thresholds rescaled (T_min x0.5 / x1.5, theta_Q x0.5 / x2). |
| `posthoc` | ROAM with a positive margin floor (0, 1, 2 dB); a variant defined after the test results were seen and reported as such. |
| `tempo` | ROAM, two table-less variants and A3 with temporal shadowing only (no static field), where outcomes are not a repeatable property of place. |

## Simulator model

All values are the defaults of `SimParams` in `roam/simulator.py`.

- **Time**: all users advance together in 100 ms steps; default run length 240 s.
- **Radio map**: cell positions and a per-cell log-distance path-loss fit estimated from
  drive-test samples (`roam/radiomap.py`); each cell has its 6 nearest cells as neighbours.
- **Shadowing**: a static, spatially correlated field per cell (standard deviation 4 dB,
  decorrelation distance 50 m, inter-site correlation 0.5, 5 m grid) plus a small temporal
  component (1.5 dB, correlation time 1 s). A quarter of the cells are blockage-prone (1.5
  times the standard deviation). `shadow_mode="temporal"` replaces the field by a per-user
  correlated process.
- **Measurements**: L3-filtered RSRP with filter weight 0.30 per 100 ms sample.
- **SINR and load**: thermal noise -122 dBm per resource element; inter-cell interference is
  proportional to the load of the interfering cells (coupling 0.20). A quarter of the cells
  are hotspots with background load 0.55 to 0.85, the others 0.05 to 0.25. Carrier: 106 PRB
  (38.16 MHz), spectral efficiency capped at 7.4 bit/s/Hz. GBR demands are served first, the
  remainder is shared by the non-GBR users; cell load feeds back into interference.
- **Failures**: radio-link failure when the serving SINR stays below Qout = -8 dB for
  T310 = 1 s; a handover commanded while the serving SINR is below Qout fails (too late).
  Either event causes a 1 s re-establishment outage. A successful handover interrupts the
  user for 50 ms. Ping-pong window 1 s.
- **Mobility profiles** (`roam/mobility.py`): pedestrian (0.8 to 2 m/s, random waypoint),
  urban vehicular (8 to 16 m/s, random waypoint), urban street grid (8 to 16 m/s, 150 m
  blocks), highway (22 to 33 m/s, three lanes, both directions), high-speed train (40 to
  60 m/s, all users on one track at a common speed). On the measured traces the users follow
  the measured route.
- **Service classes** (`roam/services.py`), with rate demand, T_min and theta_Q:

  | Service | 5QI | Resource type | Rate [Mbit/s] | T_min [s] | theta_Q [dB] | Share |
  |---|---|---|---|---|---|---|
  | Conversational voice | 1 | GBR | 0.1 | 4 | 0.7 | 0.20 |
  | Conversational video | 2 | GBR | 2 | 6 | 1.0 | 0.20 |
  | Real-time gaming | 3 | Delay-critical GBR | 1 | 7 | 1.2 | 0.15 |
  | Buffered streaming | 6 | Non-GBR | 5 | 3 | 1.5 | 0.30 |
  | Web / background | 9 | Non-GBR | 1 | 2 | 0.4 | 0.15 |

- **Outcome of a handover** (evaluation): observed for T_min of the user's service or until
  the user leaves the target. The handover is *failed* if the link is lost in the target
  within the window; otherwise it is *unnecessary* if the stay was shorter than T_min or the
  mean SINR gain over the source cell was below theta_Q, unless the source cell itself would
  have gone into radio-link failure. Handovers whose window is cut by the end of the run are
  not classified. The label fed back to a learning rule uses only what the network can
  observe (dwell time, L3 measurements, failure events).
- **Main metrics** returned by `simulate`: `HO_pm`, `UHO_pm` (handovers and unnecessary
  handovers per user-minute), `UHR` (unnecessary share of the classified handovers),
  `fail_pm` (radio-link failures plus too-late handovers per user-minute), `PP_rate`,
  `outage_pct`, `satisf` (delivered over demanded rate), `thr_mbps`, `sinr_db`, and per-service
  variants.

## Methods

| Name in results | Class (`roam/policies.py`) | Principle |
|---|---|---|
| Proposed (ROAM) | `ROAM` | Event A3 with a per-user, per-neighbour margin: outcome table (risk and lateness per route and location), path overlap, service weight, small bonus for the base-layer prediction, hold timer. |
| A3 | `A3` | 3GPP Event A3: neighbour better than serving by a hysteresis for a time-to-trigger. |
| MP-Screen | `MPScreen` | A3 after mobility-prediction screening: strong cells outside a distance and angle window around the direction of travel are penalised. |
| ToS-Skip | `ToSSkip` | A3 handover skipped when the predicted time-of-stay in the target is short, unless the serving link is much weaker. |
| Traj-Pred | `TrajPred` | Target chosen by the predicted signal at the extrapolated future position, with a margin on the current gap. |
| ST-CMAB | `STCMAB` | Contextual bandit (serving cell, heading octant) over the A3-eligible neighbours, rewarded by time-of-stay. |
| Cluster-RL | `ClusterRL` | Tabular Q-learning trigger on (gap bin, speed bin, recent-handover flag). |
| PBPHS | `PBPHS` | Follows the cell predicted by the base layer (K-means + PCA + decision tree) as soon as it is measurably better. |

`BaseLayer` is the K-means + PCA + decision-tree predictor used by ROAM and PBPHS;
`RouteTable` and `LocationTable` are the outcome memories of ROAM. The baselines are
re-implementations of the cited ideas on the common interface, each tuned with the same budget.

## Adding a decision rule

Subclass `roam.policies.Base` and implement `decide(ctx)`, which returns an integer array
with one entry per user: the target cell index, or -1 to stay.

```python
import numpy as np
from roam.policies import Base

class StrongestWithMargin(Base):
    def __init__(self, margin=3.0, name="Strongest"):
        self.margin, self.name = margin, name

    def decide(self, ctx):
        gap = np.where(self.env.nbmask[ctx["serv"]], self._gap(ctx), -1e9)
        tgt = np.argmax(gap, axis=1)
        tgt[gap[self.ar, tgt] <= self.margin] = -1
        return tgt
```

`ctx` is a dict rebuilt every step:

| Key | Content |
|---|---|
| `t`, `k` | time [s] and step index |
| `meas` | L3-filtered RSRP [dBm] of every cell, shape (users, cells) |
| `serv` | serving cell index per user |
| `x`, `y` | position [m] |
| `v`, `th` | speed [m/s] and heading [rad] estimates (with injected error if `head_err` / `speed_err` are set) |
| `last_ho` | time of the user's last handover [s] |
| `svc` | service index per user (position in `roam.services.SERVICES`) |
| `rng` | the run's random generator |
| `active` | False while a user is re-establishing after a failure |

Optional hooks:

- `reset_run(U, env, P, traj=None)`: called once before a run; call `super().reset_run(...)`
  first (it sets `self.U`, `self.env`, `self.P`, `self.ar` and the time-to-trigger timers).
- `on_outcome(src, tgt, out, uidx, dwell, t)`: observable outcome of executed handovers
  (`OUT_USEFUL`, `OUT_UNNEC`, `OUT_FAIL` from `roam.simulator`).
- `on_late(src, tgt, uidx, t)`: the link was lost in `src` before a handover completed.
- `after_step(ctx, sinr_s, hoflag)`: end of every step, with the serving SINR and the flags
  of the users that executed a handover.

`Base._gap(ctx)` gives the measured gap to the serving cell and `Base._a3(ctx, gap, margin, ttt)`
the A3 entering condition with per-neighbour timers. To run the rule through the experiment
scripts, import the class in `experiments/common.py` and refer to it by its class name in a
job, e.g. `pol=("StrongestWithMargin", dict(margin=2.0))`.

## Data and licences

- **Code**: MIT licence, see `LICENSE`.
- **`data/synthetic/`**: three synthetic dense-urban drive-test tables (20, 40 and 60 cells)
  created by the authors for this study and distributed under the same licence.
- **`data/drive_tests/`**: the measured traces `drive_test_measurements01.csv` to `03.csv`
  are third-party data from <https://github.com/jpshlima/lstm-handover>. That repository
  states no licence, so the files are not redistributed here; see `data/drive_tests/README.md`
  for how to obtain them. Only the `real` block (and the DT rows of `data_stats.py`) needs them.

## How to cite

The paper is under review:

> M. Jalili Sanjarani, Y. Elmi Sola, H. Hasanpour, A. A. Neghabi, "ROAM: Mitigating
> Unnecessary Handovers in Dense 5G Networks With an Outcome Memory and a Path-Overlap
> Margin," under review, 2026.

Earlier work:

> M. Jalili Sanjarani, Y. Elmi Sola, H. Hasanpour, A. A. Neghabi, "Handover reduction in 5G
> mobile networks using ensemble learning method," *Scientific Reports*, 2026.
> doi: 10.1038/s41598-026-73269-1

## Contact

Yasser Elmi Sola, Yasser.Elmi@iau.ac.ir
