# Raw output of the two runs drawn in Fig. 5

Fig. 5(a) and (b) of the paper show every handover attempt of the measured part (60 s to 180 s)
of one pair of test runs of stage S1 (urban grid, nominal inter-site distance 200 m, 16 m/s,
20 terminals, seed 12): tuned A3 (`test_A3_tuned_d200_v16_s12`) and ROAM
(`test_ROAM_d200_v16_s12`). The files here are the unmodified output of the scenario program
for these two jobs; their rows in `../results/campaign_urban/results.csv` have the same job
identifiers.

| File | One row per | Columns used by the figure |
|---|---|---|
| `<job>_att.csv` | handover command | `x`, `y` (position of the terminal when the command was sent, in metres), `outcome_eval` (useful, unnecessary, early, late, censored), `in_window` (1 = measured part) |
| `<job>_rlf.csv` | radio-link failure or late command | `x`, `y`, `cause`, `handled`, `in_window` |

Other columns of `<job>_att.csv`: time of the command, terminal, service class, source and
target cell, time of execution and of the outcome, dwell time, gain and rescue flag by the
evaluation rule (`_eval`) and by the observable proxy (`_obs`), ping-pong flag, margin.

The pair was chosen by rule, not by inspection: of the 20 seeds of this design cell, the one
whose four rates (unnecessary handovers and failures per UE-minute of both rules) are closest to
the means of the cell (smallest sum of squared standardised deviations); see `pick_run` in
`experiments/make_paper_figures.py`. The figure script checks the counts of these files against
the two rows of `results.csv`.

    python experiments/make_paper_figures.py ns3      # figures/fig_i_ns3.pdf, fig_i_ns3.json

The same files are written again when the two runs are repeated with the commands of
Table S25 of the supplemental file.
