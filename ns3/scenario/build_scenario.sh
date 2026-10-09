#!/bin/bash
# Copy the scenario into the ns-3 tree and build ONLY that program (MSYS2 UCRT64 shell):
#   bash build_scenario.sh
# The ns-3 libraries are not touched. The script first lists what ninja would do and refuses to
# build if anything but this program is out of date (pass --force to build anyway).
NAME=ho-scenario
HERE="$(cd "$(dirname "$0")" && pwd)"
NS3=${NS3_DIR:-/c/cl/tools/ns3/ns-3-dev}
export CCACHE_DIR=C:/cl/tools/ns3/ccache
cp "$HERE/$NAME.cc" "$NS3/scratch/$NAME.cc" || exit 1
cd "$NS3/cmake-cache" || exit 1
LOG="$NS3/../build_$NAME.log"
ninja build.ninja > "$LOG" 2>&1
PLAN=$(ninja -n scratch_$NAME | grep -E '^\[' | grep -v -E "$NAME|Re-checking|Re-running")
if [ -n "$PLAN" ] && [ "$1" != "--force" ]; then
  echo "REFUSED: the build would also touch:"; echo "$PLAN" | head -20; exit 3
fi
T0=$(date +%s)
ninja -j ${NS3_JOBS:-2} scratch_$NAME >> "$LOG" 2>&1
RC=$?
echo "rc=$RC wall_seconds=$(( $(date +%s) - T0 ))"
grep -n -E 'error|warning: unused' "$LOG" | head -30
ls -la "$NS3/build/scratch/" | grep "$NAME"
exit $RC
