#!/bin/bash
# Build ns-3 (run inside the MSYS2 UCRT64 shell). NS3_JOBS = number of parallel compilers.
export CCACHE_DIR=C:/cl/tools/ns3/ccache
export CCACHE_MAXSIZE=2G
cd /c/cl/tools/ns3/ns-3-dev || exit 1
START=$(date +%s)
echo "build start: $(date)" > /c/cl/tools/ns3/build.log
python ns3 build -j ${NS3_JOBS:-16} >> /c/cl/tools/ns3/build.log 2>&1
RC=$?
END=$(date +%s)
echo "build end: $(date)  rc=$RC  wall_seconds=$((END-START))" >> /c/cl/tools/ns3/build.log
echo "rc=$RC wall_seconds=$((END-START))"
exit $RC
