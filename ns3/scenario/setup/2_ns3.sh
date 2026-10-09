#!/bin/bash
# Step 2: download ns-3.48 and 5G-LENA (nr v5.1), apply the patches, build everything.
# Run in the "MSYS2 UCRT64" window (the first build is long):
#   bash setup/2_ns3.sh
# Optional: NS3_JOBS=24 bash setup/2_ns3.sh   (number of parallel compilers)
set -e
if [ "$MSYSTEM" != "UCRT64" ]; then echo; echo "WRONG WINDOW: this is the $MSYSTEM shell. Close it, open \"MSYS2 UCRT64\" from the Start menu and run the same command again."; exit 1; fi
SETUP="$(cd "$(dirname "$0")" && pwd)"      # this folder
STUDY="$(dirname "$SETUP")"                 # the folder with the scenario source
[ -f "$STUDY/ho-scenario.cc" ] || { echo "the scenario source is not next to the setup folder"; exit 1; }
mkdir -p /c/cl/tools/ns3 && cd /c/cl/tools/ns3

# ns-3, release 3.48, plus four commits of the official repository:
# three recommended by the nr release notes and one that Windows needs to start any program
[ -d ns-3-dev ] || git clone https://gitlab.com/nsnam/ns-3-dev.git
cd ns-3-dev
git checkout -q -B ns-3.48-nr ns-3.48
git -c user.name=local -c user.email=local@localhost am -q "$SETUP"/patches/*.patch
git log --oneline -4

# 5G-LENA
[ -d contrib/nr ] || git clone https://gitlab.com/cttc-lena/nr.git contrib/nr
git -C contrib/nr checkout -q -B v5.1-local v5.1

python ns3 configure -G Ninja -d optimized --enable-modules=nr \
       --enable-examples --enable-tests --filter-module-examples-and-tests=nr

cp "$SETUP/build.sh" /c/cl/tools/ns3/build.sh
bash "$STUDY/fix_srs.sh"        # SRS patch of the nr module, then the full build
bash "$STUDY/build_scenario.sh"   # the scenario program
ls -la /c/cl/tools/ns3/ns-3-dev/build/scratch/ | grep ho-scenario && echo "STEP 2 OK"
