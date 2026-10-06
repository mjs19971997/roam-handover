# Results

Output directory of the experiment scripts (override with the environment variable
`ROAM_RESULTS`).

| File | Written by | Content |
|---|---|---|
| `tune.csv` | `experiments/tune.py` | one row per (method family, configuration, profile, seed) of the tuning grid |
| `tune_extra.csv` | `experiments/tune.py <family> ...` | same, when only some families are re-tuned |
| `tuned.json` | `experiments/select_configs.py` | selected class and parameters per method family, and the failure budget |
| `tune_summary.csv` | `experiments/select_configs.py` | validation means per configuration, with `feasible` and `selected` flags |
| `exp_<block>.csv` | `experiments/run_experiments.py <block>` | one row per run of the block (`profiles`, `load`, `density`, `real`, `ablation`, `hht`, `nonstat`, `sens`, `thresh`, `posthoc`, `tempo`) |
| `summary.json` | `experiments/analyze.py` | means, 95 % confidence intervals and paired tests per block |
| `data_stats.json` | `experiments/data_stats.py` | descriptive statistics of the radio environments |

The method label `Proposed` in these files denotes ROAM; `tuned.json` refers to the classes
of `roam/policies.py` by name.
