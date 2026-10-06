#!/bin/bash
# Full pipeline: tuning -> selection -> test experiments -> statistics -> figures.
# Usage: bash run_all.sh        (PYTHON=<interpreter> and ROAM_PROCS=<workers> are optional)
# The "real" block needs the drive-test traces (data/drive_tests/README.md); it is skipped if they are missing.
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python}
OUT=${ROAM_RESULTS:-results}
mkdir -p "$OUT" figures

BLOCKS="profiles load density ablation hht nonstat sens thresh posthoc tempo"
if [ -f data/drive_tests/drive_test_measurements01.csv ] && [ -f data/drive_tests/drive_test_measurements02.csv ] \
   && [ -f data/drive_tests/drive_test_measurements03.csv ]; then
  BLOCKS="$BLOCKS real"
else
  echo "drive-test traces not found: skipping block 'real'"
fi

rm -f "$OUT/tune_extra.csv"
$PY experiments/tune.py                  > "$OUT/tune.log" 2>&1     || exit 1
$PY experiments/select_configs.py        > "$OUT/select.log" 2>&1   || exit 1
$PY experiments/run_experiments.py $BLOCKS > "$OUT/experiments.log" 2>&1 || exit 1
$PY experiments/analyze.py               > "$OUT/analyze.log" 2>&1  || exit 1
$PY experiments/make_figures.py          > "$OUT/figures.log" 2>&1  || exit 1
echo "pipeline finished; results in $OUT, figures in figures/"
