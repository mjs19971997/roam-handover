#!/bin/bash
# Step 1: compiler and build tools. Run in the "MSYS2 UCRT64" window:
#   bash setup/1_tools.sh
set -e
if [ "$MSYSTEM" != "UCRT64" ]; then echo; echo "WRONG WINDOW: this is the $MSYSTEM shell. Close it, open \"MSYS2 UCRT64\" from the Start menu and run the same command again."; exit 1; fi
pacman -S --needed --noconfirm git \
  mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-gdb \
  mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-ccache \
  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-eigen3 mingw-w64-ucrt-x86_64-sqlite3
echo
g++ --version | head -1
cmake --version | head -1
python --version
echo "STEP 1 OK"
