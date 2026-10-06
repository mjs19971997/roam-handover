# -*- coding: utf-8 -*-
"""Descriptive statistics of the six radio environments -> results/data_stats.json.
Drive-test environments whose trace file is missing are skipped."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import get_env, get_fw, OUT, DS
from roam.simulator import SimParams

if __name__ == "__main__":
    P = SimParams(); S = {}
    for name in ["UDN-20", "UDN-40", "UDN-60", "DT01", "DT02", "DT03"]:
        if not os.path.exists(DS[name]):
            print(name, "skipped (data file not found, see data/drive_tests/README.md)")
            continue
        e = get_env(name, P); df = e.base.df; fw = get_fw(e)
        d = np.sort(np.linalg.norm(e.pos[:, None] - e.pos[None], axis=2), axis=1)[:, 1]
        s = dict(samples=int(len(df)), cells=int(e.M), w=float(e.xmax - e.xmin), h=float(e.ymax - e.ymin),
                 rsrp_min=float(df.RSRP.min()), rsrp_mean=float(df.RSRP.mean()), rsrp_max=float(df.RSRP.max()),
                 dist_med=float(df.Distance.median()), isd_med=float(np.median(d)),
                 n_min=float(e.n.min()), n_med=float(np.median(e.n)), n_max=float(e.n.max()),
                 hot=int(e.hot.sum()), blk=int(e.blk.sum()), bg_mean=float(e.bg.mean()),
                 fw_acc=fw.acc, fw_k=fw.k, fw_feat=fw.n_feat, fw_comp=fw.n_comp, fw_depth=fw.depth, fw_train=fw.n_train)
        if e.route is not None:
            s["route_km"] = float(np.hypot(*np.diff(e.route, axis=0).T).sum() / 1000)
            s["own_fit"] = int(sum(v[1] for v in e.base.fit_info.values()))
        S[name] = s
        print(name, s)
    with open(os.path.join(OUT, "data_stats.json"), "w") as fh:
        json.dump(S, fh, indent=1)
