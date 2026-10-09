#!/bin/bash
# nr v5.1 aborts the whole simulation when an uplink SRS reaches a gNB whose receiver is not idle
# (NrSpectrumPhy::StartRxSrs: "Cannot RX SRS while TX", "Not allowed state for starting SRS
# reception", ...). After a handover this happens in some traces. The patch turns every abort
# of that function into a warning, so that the one SRS is dropped; a run that never reached
# these branches is unaffected (checked by rerunning a finished job). Run inside the MSYS2 UCRT64 shell with
# no simulation running. The untouched file is kept as nr-spectrum-phy.cc.orig.
F=/c/cl/tools/ns3/ns-3-dev/contrib/nr/model/nr-spectrum-phy.cc
[ -f "$F.orig" ] || cp "$F" "$F.orig"
cp "$F.orig" "$F"
A=$(grep -n '^NrSpectrumPhy::StartRxSrs' "$F" | cut -d: -f1)
B=$(grep -n '^NrSpectrumPhy::GetCellId' "$F" | cut -d: -f1)
sed -i "${A},${B}s|NS_FATAL_ERROR(|NS_LOG_WARN(/* ns3study patch: SRS dropped */ |" "$F"
echo "patched lines: $(sed -n "${A},${B}p" "$F" | grep -c 'ns3study patch')  left: $(sed -n "${A},${B}p" "$F" | grep -c NS_FATAL_ERROR)"
bash /c/cl/tools/ns3/build.sh
RC=$?
grep -n -E ' error ' /c/cl/tools/ns3/build.log | head -10
echo "FIX_RC=$RC"
exit $RC
