# Study plan: ROAM against tuned Event A3 in ns-3 (nr v5.1)

Written on 8 October 2026, before any run of the stages below except where stated. The
stages, sizes and analyses are fixed in the run script and in `analyze_study.py`; this file states
them in words. Every stage is reported whatever it shows, including stages that end early and
jobs that fail.

## What was known when this plan was written

* Urban scenario, light traffic, test seeds 1-10 (300 runs, finished): ROAM against the tuned
  A3, pooled over the six cells: unnecessary handovers -36 %, handovers -26 %, failures per
  UE-minute 0.025 -> 0.086 (almost all late commands), delivery equal. Selected settings:
  `A3_h6_t100`, `ROAM_h1_t300_e14-8-8_c9`; failure budget of the tuning 0.10.
* Base scenario: a partial campaign (tuning rows only) on another machine.
* Software checks of the new features with short runs (at most 60 s, seed 1): they showed that
  failures become frequent under mixed and full traffic (a few per UE-minute in the first
  seconds of two runs). No tuning or test result of the new stages existed.

So for the urban core the confirmatory data are seeds 11-20; seeds 1-10 are reported
alongside, and pooled.

## Scenarios, rules, outcome definitions

As documented in `README.md` (base scenario, ROAM in the Cell-Individual-Offset form,
outcome classifier, TR 36.839 failure parameters, urban scenario).
20 UEs and 7 gNBs unless a stage says otherwise; the first 60 s of every run are discarded.

Traffic modes (`--traffic`):

| Mode | Definition | Source |
|---|---|---|
| light | one 200-byte downlink packet per 100 ms per UE (16 kbit/s) | this study (phases 2-3) |
| mixed | downlink flow per service class: voice 60 B / 20 ms (24 kbit/s); video call 1250 B / 5 ms (2 Mbit/s); gaming 500 B / 4 ms (1 Mbit/s); streaming 1250 B / 2 ms (5 Mbit/s); web 1250 B / 10 ms (1 Mbit/s); 44 Mbit/s offered in total | rates of the last four: the rate demands r_s of the paper's service table (the authors' model parameters); voice rate and all packet sizes: assumed. No 3GPP traffic model was verified for this plan. Constant bit rate, no on/off behaviour |
| full | every UE is offered 8 Mbit/s downlink (1400 B packets), 160 Mbit/s in total, above the capacity of the seven 10 MHz cells | the full-buffer worst case commonly used in 3GPP evaluations (assumed, not re-verified) |

Uplink user traffic is not generated: with uplink data nr v5.1 aborts around handovers
("gNB transmission overlaps in time with UE transmission"). All flows use the same bearer type
and scheduler; the service class changes the traffic and the outcome thresholds only.
Measured in short runs (urban, 16 m/s): share of cell-slots with at least one scheduled UE
6 % (light), 63 % (mixed), 85 to 91 % (full); data-region resources used 0.3 %, 42 to 44 %, 76 to 79 %.

## Endpoints

**Primary** (core stages S1 and S2): unnecessary handovers per UE-minute and failures per
UE-minute, ROAM against the tuned A3, paired by (cell, seed), pooled over the six cells;
two-sided exact Wilcoxon signed-rank test, mean paired difference with 95 % confidence
interval, relative change of the means. Four tests (two endpoints, two scenarios); all four
are reported. A lower unnecessary-handover rate bought with a higher failure rate is not
counted as a win; that trade-off is what stage S3 resolves.

**Secondary, pre-specified** (S3): comparison at equal failure rate on the test cells.
(a) the frozen ROAM setting against the A3 configuration with the fewest unnecessary handovers
among those whose failure rate does not exceed ROAM's, paired by (cell, seed); and the mirror
image for the frozen A3; (b) the lowest unnecessary-handover rate of each family within failure
budgets 0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.50 per UE-minute; (c) the two Pareto fronts
(failures, unnecessary handovers) and which points are dominated by the other family. Because
the best configuration is picked on the same runs it is evaluated on, (a) favours the family
whose best member is searched for; this is stated in the report.

**Secondary** (S4): the two primary endpoints under mixed traffic with its own tuning, and
under downlink overload with the settings frozen under mixed traffic.

**Exploratory**: ablations (overlap only, history only, A3 with ROAM's base margin), the
fast-fading subsets, all sensitivities of S5, handover and ping-pong rates, delivery ratio,
outage time, per-class service metrics (delivery, mean and 95th-percentile delay, gaps above
100 ms and 500 ms in the received stream).

## Stages (running order)

Hours are for 24 workers on the user's machine, scaled from its finished campaign (512 runs in
1.0 h, i.e. about one simulated second per worker-second with light traffic) and from cost
ratios measured on the development machine: mixed 6.5x, full 13x, fast fading 4.3x, 10 / 40 /
60 UEs 0.5x / 2.9x / 6.5x. The ratios for mixed and full come from short runs and may be off
by a third.

| Stage | Folder(s) | Content | Jobs | Hours |
|---|---|---|---|---|
| S1 urban core | `campaign_urban` | tuning 192 (exist), test 5 rules x 6 cells x seeds 1-20 (seeds 1-10 exist), fading subset 20 (exist) | 812 (300 new) | 0.6 |
| S2 base core | `campaign` | tuning 192 x 150 s, test 600 x 180 s, fading subset 20 x 120 s | 812 | 1.7 |
| S3 frontier | `s3_frontier_urban`, `s3_frontier_base` | all 24 A3 and 24 ROAM tuning configurations on the six test cells, seeds 1-4, 180 s | 2304 | 4.7 |
| S4 load | `s4_mixed_urban`, `s4_mixed_base`, `s4_full_urban` | mixed: tuning 192 x 100 s and test 5 rules x 6 cells x seeds 1-5 x 120 s per scenario; full (urban): tuned A3 and ROAM x 6 cells x seeds 1-5 x 100 s | 744 | 6.4 |
| S5 sensitivities | `s5_sens_urban`, `s5_sens_base` | frozen core settings, tuned A3 and ROAM, seeds 1-10, 180 s unless stated (list below) | 1140 | 4.7 |
| Total | | | 5812 (5300 new) | about 18 |

S5 conditions (reference cells: ISD 400 m and 200 m at 16 m/s): number of UEs 10, 40 (both
reference cells) and 60 (ISD 400 m only); speeds 3 and 42 m/s at both ISDs; ISD 300 m at
16 m/s (both scenarios) and 500 m (base only: in the urban layout the ring sites would leave
the street area); fast fading on all six cells (120 s); preparation delay 20 and 100 ms
(50 ms is the core value); T310 0.5 and 2 s (1 s is the core value); run length 600 s on the
reference cells with all four ROAM-family rules (history better trained).

Order and stopping: S1, S2, S3, S4, S5. A stop at any time leaves every finished
job in its `results.csv`; the analysis works on whatever is there and says how many runs each
number rests on.

## Deviations from the proposal that preceded this plan, with reasons

* S3 uses 4 seeds per cell instead of about 5, and S4 uses shorter runs (100 / 120 s) and 5
  seeds: loaded cells cost 6.5 to 13 times more per simulated second than the light-traffic
  runs, because every cell then transmits in most slots.
* Traffic `full` has no tuning of its own (cost); it is a test of the settings frozen under
  mixed traffic.
* Mixed traffic is downlink only (nr abort with uplink data, see above).
* 60 UEs only on one reference cell (cost 6.5x).

## Rules for the analysis

* Tuning and selection per stage folder exactly as in the core campaigns (24 + 24
  configurations, four validation traces, selection by the rule stated in `README.md`).
* No run is excluded. A job that fails twice is listed with its log; its cell is analysed
  with the remaining seeds and the report says so.
* Results from different machines are not pooled (ROAM runs can differ between compiler
  builds at exact ties of the best-server map).
