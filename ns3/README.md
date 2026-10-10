# Validation in ns-3: ROAM against tuned Event A3

This folder belongs to Section 7 of the paper and Section S7 of its supplemental file. The
decision rule of the paper was implemented a second time, in ns-3 with the 5G-LENA NR module,
and compared with a tuned Event A3 rule under a plan that was written before the runs.

| Path | Content |
|---|---|
| `PLAN.md` | the study plan as written on 8 October 2026, before the stages were run (only references to files and tools that are not part of this repository were edited) |
| `analyze_ns3.py` | statistics of one stage: tuning table and selection, per-cell and pooled comparisons, paired tests; writes `report.txt` and `ns3_summary.json` |
| `analyze_study.py` | consolidated report over all stages; writes `results/report_study.txt` and `results/report_study.json` |
| `results/<stage>/results.csv` | one row per finished run |
| `results/<stage>/tuned_ns3.json` | the automatic selection of that stage, with the complete validation table |
| `results/<stage>/report.txt`, `ns3_summary.json` | output of `analyze_ns3.py` for the stage |
| `results/report_study.txt`, `report_study.json` | output of `analyze_study.py`; every ns-3 number of the paper is computed from the JSON file and the stage CSV files |
| `scenario/ho-scenario.cc` | the ns-3 scenario program (C++, built against ns-3.48 and nr v5.1): both environments, the rules `a3` and `roam`, the traffic modes and the outcome classification |
| `scenario/campaign.py`, `scenario/run_study.py` | the scripts that start the runs: one core campaign, and all stages of the study |
| `fig5_runs/<job>_att.csv`, `<job>_rlf.csv` | raw output of the two runs drawn in Fig. 5 of the paper (tuned A3 and ROAM, urban grid, 200 m, 16 m/s, seed 12): one row per handover command and one row per failure, with the position of the terminal |
| `make_ns3_figures.py` | figure of the supplemental file: all 48 configurations with the two fronts, urban grid and open area (`figures/fig_ns3_fronts`); Fig. 5 is drawn by `experiments/make_paper_figures.py ns3` |
| `scenario/build_scenario.sh`, `scenario/fix_srs.sh`, `scenario/setup/` | build of the program, the one change to the NR module, and the installation of the tool chain (see "Building and running the scenario") |

The per-handover trace files of the runs (about 1 GB) are not included, except those of the two
runs of Fig. 5 (`fig5_runs/`); the scenario program
writes them again when a run is repeated.

## Tool chain

* ns-3 release 3.48 and the NR module of 5G-LENA (`nr`) version 5.1, built natively on Windows
  in the MSYS2 UCRT64 environment (g++ 16, CMake, Ninja).
* Four commits of the official ns-3 repository are applied on top of release 3.48: three that
  the release notes of the NR module recommend, and one without which the release does not
  start when built with this compiler.
* One change to the NR module. After a handover an uplink SRS can reach a gNB whose receiver
  is not idle, and `NrSpectrumPhy::StartRxSrs` (`contrib/nr/model/nr-spectrum-phy.cc`) then
  ends the simulation through one of five `NS_FATAL_ERROR` statements. These five statements
  were turned into warnings (`scenario/fix_srs.sh`), so that the one SRS is dropped and the run
  continues. A run that had finished before the change was repeated after it and gave
  identical metrics. No other library code was changed.
* All runs of the stages were made on one machine (Intel Core i9-14900K), 10 to 28 runs in
  parallel. Results from different machines or builds are not pooled: ROAM runs can differ
  between compiler builds at exact ties of the best-server map.

## Handover procedure and failure model

Event A3 is evaluated by the RRC of the terminal on L3-filtered RSRP (filter coefficient 4)
once per L1 measurement period of 200 ms, so a time-to-trigger of 100, 300, 500 and 1000 ms
means one, two, three and six consecutive evaluations. The source gNB sends the handover
command after a preparation delay of 50 ms; the execution is the procedure of the module
(about 4 ms with ideal RRC signalling). Radio-link failure follows the counters of the
terminal: Qout = -8 dB evaluated over 200 ms, Qin = -6 dB over 100 ms, N310 = N311 = 1,
T310 = 1 s. The handover-failure model of 3GPP TR 36.839 is switched on: a handover command
that reaches the terminal while T310 is running is a handover failure (a late handover).

Failures per UE-minute = (T310 expiries + RLC retransmission failures + late commands +
failed executions) / UE-minutes.

In the NR module a gNB transmits its downlink control symbol only in slots in which it has
something to send, and a terminal evaluates Qout on the control symbols of its own cell. With
the light traffic of the core stages most monitored slots are free of interference, so the
failure rates of these stages are rates at light load.

## ROAM in ns-3

The rule is implemented in the form of Proposition 1 of the paper. The stock A3 event is
configured once (hysteresis h0, offset 0, the time-to-trigger of the rule). A controller, called
from the measurement trace of the terminal immediately before its RRC evaluates the events,
rewrites for every terminal and every neighbour the cell-individual offset

    Ocn(i, j) = h0 - m_ij,
    m_ij = clip(h0 + eta_H * H - eta_L * L + eta_S * w_s - eta_A * gamma_i * (f_j - f_c), 0, m_cap)

so that the unmodified entering condition of the terminal reads `F_ij - F_ic > m_ij`. Nothing
in the terminal is changed. On the network side the stock algorithm hands over to the
strongest reported cell, whereas ROAM takes the cell with the largest excess over its margin;
a small handover-algorithm class with the same report configuration therefore selects the
reported cell with the largest RSRP + offset.

* With all weights zero ROAM and the stock A3 algorithm produce identical per-handover records
  (127 attempts in the check run of the open area, 100 in the urban grid). Two runs with the
  same seed are identical.
* Position, speed and heading are the true values of the mobility model.
* Overlap: the 48-point quadrature of the paper, on a nominal best-server map computed from
  the configured path-loss model without shadowing and, in the urban grid, without buildings.
* History table: as in the paper (40 m bins, kappa_L = 3, beta = 1, alpha = 0.6, forgetting
  time 600 s). It is empty at the start of every run; the discarded 60 s are its only warm-up.
* Not implemented: the base-layer bonus and the hold timer (the paper's ablation finds both
  dispensable).

Every handover command is an attempt and receives exactly one outcome (useful, unnecessary,
early, late; attempts whose window is cut by the end of the run are censored), computed during
the run from traces with the definition of the paper. ns-3 has no trace of the SINR a terminal
would have on a neighbour cell, so the gain and the rescue flag are computed from the 200 ms
RSRP reports of all seven cells, with every cell counted as an interferer. An independent
recomputation from the raw reports agreed on all attempts of the two runs checked (83 of 83,
69 of 69).

## Environments

Common to both: 7 gNBs (one in the centre, six around it), 40 dBm, single-element isotropic
antennas, one 10 MHz carrier at 3.5 GHz, numerology 0; 20 terminals at a constant speed of 8,
16 or 30 m/s; nominal inter-site distance 200 or 400 m (six cells of the design: distance x
speed); five service classes in the proportions of the paper (4 voice, 4 video call, 3 gaming,
6 streaming, 3 web); light traffic of one 200-byte downlink packet per 100 ms and terminal;
ideal RRC signalling; no fast fading unless a stage says so.

| | Open area (`base`) | Urban grid (`urban`) |
|---|---|---|
| Propagation | UMa, non-line-of-sight (TR 38.901), sites 25 m high | UMi street canyon (TR 38.901), sites 10 m high |
| Blockage | none; shadowing of the ns-3 model drawn per link | line of sight decided by geometry: a link is NLOS if it crosses a building; shadowing per link, redrawn when the LOS state changes |
| Layout | disc of radius 1.3 x ISD | urban grid of 3GPP TR 37.885: road grid 433 m x 250 m, streets 20 m wide, 2 x 2 blocks, buildings 20 m high; sites moved to the nearest street centre line |
| Mobility | straight legs at constant speed | vehicles on the street centre lines; at an intersection straight 0.5, left 0.25, right 0.25 |

In the urban grid blockage is tied to place and is the same for every terminal; in the open
area nothing but geometry is repeatable by place. The two environments also differ in
propagation model, site height and mobility, so a difference between them cannot be attributed
to one of these alone.

## Tuning and test protocol

* Tuning, separately per environment: 24 A3 and 24 ROAM configurations on four validation
  traces of 150 s (ISD 400 m at 16 and 30 m/s, ISD 200 m at 16 and 30 m/s; seeds 101-104, not
  used in the test). A3: hysteresis 1-6 dB x time-to-trigger 100/300/500/1000 ms. ROAM:
  h0 in {1, 2} dB x time-to-trigger {100, 300} ms x (eta_H, eta_L, eta_A) in {(14, 8, 8),
  (6, 4, 6), (10, 6, 3)} dB x m_cap in {5, 9} dB, eta_S = 4 dB.
* Selection (automatic): among the configurations whose failure rate on the validation traces
  does not exceed that of the reference A3 (3 dB, 300 ms), the one with the fewest unnecessary
  handovers per UE-minute; if none, the lowest failure rate. Ties: lower failure rate, then
  lower handover rate, then grid order. The selected settings are frozen.
* Test: 5 rules x 6 cells x 20 seeds per environment, 180 s per run with the first 60 s
  discarded (40 UE-minutes per run). Rules: `A3_tuned`, `ROAM`, `ROAM_overlap` (history
  weights zero), `ROAM_history` (overlap weight zero), `A3_h0` (stock A3 with the base
  hysteresis and time-to-trigger of ROAM).
* Pairing: within a seed all rules see the same trajectories, service assignment and random
  streams. Comparisons are paired by (inter-site distance, speed, seed); the pooled
  comparisons have 120 pairs. Reported: mean paired difference with 95 % confidence interval,
  relative change of the means, two-sided exact Wilcoxon signed-rank test.
* Urban seeds 1-10 were known when the plan was written; seeds 11-20 are the confirmatory part
  and are also reported separately.

## Stages

| Stage | Folder | Content | Planned | Finished |
|---|---|---|---|---|
| S1 | `campaign_urban` | urban core: tuning 192, test 600, fast-fading subset 20 | 812 | 812 |
| S2 | `campaign` | open-area core: the same | 812 | 812 |
| S3 | `s3_frontier_urban`, `s3_frontier_base` | all 48 configurations on the six test cells, seeds 1-4 | 2304 | 2304 |
| S4 | `s4_mixed_urban`, `s4_mixed_base` | mixed traffic: own tuning (192) and test (5 rules x 6 cells x 5 seeds) | 684 | 646 |
| S4 | `s4_full_urban` | downlink overload, settings frozen under mixed traffic | 60 | 60 |
| S5 | `s5_sens_urban`, `s5_sens_base` | sensitivities with the frozen core settings | 1140 | 1140 |
| | | total | 5812 | 5774 |

The 38 missing runs (17 urban, 21 open area, all under mixed traffic) stopped inside the NR
module with the error "Cannot TX while RX" in both of their attempts. That error was not
patched; the runs are left out, and the reports state on how many runs each number rests.

## Results in brief

Rates per UE-minute; ROAM against tuned A3.

* Urban grid, 120 pairs: unnecessary handovers 2.220 -> 1.390 (-37.4 %, p = 1.5e-27);
  seeds 11-20 only: -38.8 %. Failures 0.031 -> 0.098 (p = 1.9e-21), almost all of them late
  handover commands. Handovers 6.220 -> 4.565. Delivery ratio unchanged. (The ROAM failure rate
  is 468 failures in 4800 UE-minutes, exactly 0.0975; the paper rounds it to 0.098, while
  `report_study.txt` prints the binary value of the mean as 0.097.)
* Urban grid at equal failure rate (S3): the selected ROAM has 1.371 unnecessary handovers at
  0.097 failures; the best A3 configuration whose failure rate does not exceed that (5 dB,
  300 ms) has 1.994 at 0.086. Difference -0.623 +/- 0.267 (p = 9.1e-05). That A3 configuration
  is picked on the same runs, which favours A3. Within a failure budget of 0.02 per UE-minute
  the best A3 configuration is ahead of the best ROAM configuration (2.964 against 3.349).
* Urban sensitivities: the reduction holds with fast fading on all cells (-36.6 %), with 10,
  40 and 60 terminals (-40.2, -38.2, -22.7 %), at 42 m/s (-44.0 %), at ISD 300 m (-41.9 %),
  with a preparation delay of 20 and 100 ms (-38.3, -41.0 %) and with T310 of 0.5 and 2 s
  (-30.5, -41.2 %). At 3 m/s there is no difference (+3.1 %, p = 0.81). The failure rate of
  ROAM is higher in every condition. In 600 s runs full ROAM is 24.4 % below its overlap-only
  and 25.2 % below its history-only variant.
* Open area, 120 pairs: unnecessary handovers 0.715 -> 0.779 (+9.0 %, p = 0.0018), failures
  0.004 -> 0.015. No advantage; every configuration on the ROAM front is dominated by an A3
  configuration.
* Loaded network (S4, exploratory): with the neighbour cells transmitting, all rules have
  between 0.9 and 3.7 failures per UE-minute, the tuning selects very late A3 settings, and the
  rate of unnecessary handovers is no longer a meaningful endpoint. Under mixed traffic ROAM
  delivered more packets (urban 85.9 % -> 89.4 %) with less outage (0.41 -> 0.21 s per
  UE-minute); in the open area it had about half the failures of A3. Under overload in the
  urban grid it had 17 % more failures. Differences in the service metrics were not tested,
  the traffic profiles are assumed and downlink only, and the aborted runs are missing.

## Building and running the scenario

The folder `scenario/` holds everything needed to repeat the runs on Windows with MSYS2
(UCRT64 environment):

| File | Purpose |
|---|---|
| `ho-scenario.cc` | the scenario program: two environments (`--scen`: `base` or `urban`), rules (`--rule`: `a3` or `roam`), traffic modes, outcome classification, one JSON line of metrics per run (`--PrintHelp` lists the options) |
| `setup/1_tools.sh` | compiler and build tools (pacman packages) |
| `setup/2_ns3.sh` | ns-3.48, the four upstream commits in `setup/patches/`, nr v5.1, the SRS change, the full build and this program |
| `fix_srs.sh` | the one local change to nr v5.1: the five aborts in `NrSpectrumPhy::StartRxSrs` become "drop this SRS" |
| `build_scenario.sh` | copies the source into `scratch/` of the ns-3 tree and builds that one program |
| `campaign.py` | one core campaign: tuning (24 A3 and 24 ROAM configurations on four validation traces), automatic selection, test with seeds 1-10, fast-fading subset; `--scen urban` for the urban grid; resumable |
| `run_study.py` | the complete study of `PLAN.md` (stages S1 to S5, test seeds 1-20), resumable; `--status`, `--list`, `--only`, `--smoke` |

    cd scenario
    bash setup/1_tools.sh               # in the "MSYS2 UCRT64" shell
    bash setup/2_ns3.sh                 # long: downloads and builds ns-3 and nr
    NS3_WORKERS=24 python run_study.py  # 5812 runs; python run_study.py --smoke for a short test

The scripts expect ns-3 in `C:\cl\tools\ns3\ns-3-dev` and MSYS2 in `C:\cl\tools\msys64`
(`2_ns3.sh` creates the first). For other locations change `NS3` and `DLL_PATH` at the top of
`campaign.py` and the paths in the shell scripts (`build_scenario.sh` also reads `NS3_DIR`).

New runs are written to stage folders inside `scenario/` (`campaign_urban/results.csv` and so
on, per-attempt files in `res/`), with the same folder names as under `results/`; the runs of
the paper in `results/` are not touched. At its end `run_study.py` calls
`analyze_study.py --root scenario` on the new runs. Results from another machine or compiler
build need not be bit-identical to the stored rows: ROAM runs can differ at exact ties of the
best-server map (see "Tool chain"). An A3 test run of 180 s repeated on a second machine gave
the stored row in every field except the run time and `map_diff`, a diagnostic count of such
ties.

## Re-running the analysis

    python analyze_study.py              # all stages under results/
    python analyze_ns3.py results/campaign_urban
    python analyze_study.py --root scenario   # runs made with scenario/run_study.py

Both scripts need the Python standard library only. The shipped reports were produced without
SciPy, with the built-in table of t quantiles; when SciPy is installed the scripts use its
quantile function and some confidence half-widths change in the third decimal. Means, paired
differences and p-values are not affected.

## Columns of `results.csv`

| Column | Meaning |
|---|---|
| `phase`, `label`, `config` | `tune` / `test` / `rob` (fast-fading subset) / `front` / `sens`; rule or configuration label |
| `rule`, `hyst`, `ttt_ms`, `h0`, `etaH`, `etaL`, `etaA`, `etaS`, `mCap` | parameters of the run |
| `nUe`, `isd`, `speed`, `simTime`, `discard`, `fading`, `rngRun`, `scen`, `traffic`, `cond` | scenario, seed and, in S5, the sensitivity condition |
| `ue_min` | UE-minutes measured (after the discarded part) |
| `attempts`, `useful`, `unnecessary`, `early`, `late`, `censored` | handover attempts and their outcomes |
| `failures`, `late_cmd`, `rlf_t310`, `rlf_rlc`, `rlf_during_ho` | failures and their causes |
| `ho_pm`, `uho_pm`, `fail_pm`, `uhr`, `pp_ratio` | handovers, unnecessary handovers and failures per UE-minute; unnecessary-handover ratio; ping-pong ratio |
| `delivery`, `sinr_db`, `los_serving` | delivery ratio of the downlink packets; mean SINR of the serving cell estimated from the RSRP reports; share of samples with a line of sight to the serving site (urban) |
| `mean_margin`, `mean_H`, `mean_L`, `mean_df`, `mean_gamma` | means of the ROAM terms |
| `outage_s_pm`, `occ_slots`, `occ_prb`, `deliv_*`, `delay_ms_*`, `delay95_ms_*`, `stall100_pm_*`, `stall500_pm_*` | S4 and S5: outage time, resource occupancy and per-class service metrics |

## Differences from the simulator of the paper

Only Event A3 is compared (the other six baselines were not implemented in ns-3); 7 cells and
20 terminals; decisions every 200 ms instead of 100 ms; no base-layer bonus and no hold timer;
shadowing drawn per link by the ns-3 models instead of a static spatial field; no load-coupled
interference model and no throughput metric; the evaluation label is computed from RSRP
reports; a handover is late when its command arrives while T310 is running; the history table
is warmed up inside the run (60 s, 20 terminals); the ROAM tuning grid has three weight
triples and two caps. Section S7 of the supplemental file lists these in full.
