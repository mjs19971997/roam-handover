# -*- coding: utf-8 -*-
"""Radio map built from drive-test data (measured or synthetic).

From the measurement samples the module estimates the position of every base
station (cell / PCI) and fits a per-cell log-distance path-loss model
RSRP(d) = A - 10 n log10(d).  The result is the radio map on which the simulator
moves its users.
"""
import numpy as np
import pandas as pd

EARTH_LAT_M = 110540.0     # metres per degree of latitude
EARTH_LON_M = 111320.0     # metres per degree of longitude at the equator


def load_dataset(path):
    """Read a drive-test CSV and normalise its column names."""
    df = pd.read_csv(path)
    # drop the unnamed index column present in the measured traces
    if df.columns[0].startswith("Unnamed") or df.columns[0] == "":
        df = df.drop(columns=df.columns[0])
    ren = {"Height (m)": "Height", "Distance (m)": "Distance", "Speed (m/s)": "Speed"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    return df


class RadioMap:
    """Cell positions and per-cell path-loss fits estimated from a drive-test table.

    Required columns: Lon, Lat, RSRP, PCI, Distance, Azimuth.
    Attributes used by the simulator: name, cells, cell_pos (M,2) [m], A_arr and
    n_arr (path-loss intercept / exponent per cell), xmin/xmax/ymin/ymax [m], df.
    """

    def __init__(self, df, name="dataset"):
        self.name = name
        self.df = df.reset_index(drop=True)
        self.lat0 = float(df.Lat.mean())
        self.lon0 = float(df.Lon.mean())
        self._project()
        self._estimate_cells()
        self._fit_pathloss()

    def to_xy(self, lon, lat):
        """Geographic coordinates -> local metres (equirectangular projection)."""
        x = (np.asarray(lon) - self.lon0) * EARTH_LON_M * np.cos(np.radians(self.lat0))
        y = (np.asarray(lat) - self.lat0) * EARTH_LAT_M
        return x, y

    def _project(self):
        self.df["x"], self.df["y"] = self.to_xy(self.df.Lon.values, self.df.Lat.values)
        self.xmin, self.xmax = self.df.x.min(), self.df.x.max()
        self.ymin, self.ymax = self.df.y.min(), self.df.y.max()

    def _estimate_cells(self):
        """Base-station positions from the reported distance and azimuth of each sample."""
        self.cells = sorted(self.df.PCI.unique().tolist())
        self.cell_xy = {}
        for c in self.cells:
            sub = self.df[self.df.PCI == c]
            az = np.radians(sub.Azimuth.values)
            d = sub.Distance.values
            px, py = sub.x.values, sub.y.values
            # the azimuth convention is ambiguous; keep the reading with the smaller scatter
            cand1 = np.c_[px + d * np.sin(az), py + d * np.cos(az)]
            cand2 = np.c_[px - d * np.sin(az), py - d * np.cos(az)]
            best = cand1 if cand1.std(0).sum() <= cand2.std(0).sum() else cand2
            self.cell_xy[c] = np.median(best, axis=0)
        self.cell_pos = np.array([self.cell_xy[c] for c in self.cells])

    def _fit_pathloss(self):
        """Per-cell least-squares fit of RSRP = A - 10 n log10(d)."""
        self.pl = {}
        gA, gn = [], []
        for c in self.cells:
            sub = self.df[self.df.PCI == c]
            d = np.clip(sub.Distance.values, 1.0, None)
            rsrp = sub.RSRP.values
            X = np.log10(d)
            if len(d) >= 8 and X.std() > 1e-3:
                slope, intercept = np.polyfit(X, rsrp, 1)
                n = np.clip(-slope / 10.0, 1.6, 5.0)
                A = intercept
            else:
                n, A = 3.0, float(np.median(rsrp) + 30.0)
            self.pl[c] = (A, n)
            gA.append(A); gn.append(n)
        self.global_pl = (float(np.median(gA)), float(np.median(gn)))
        self.A_arr = np.array([self.pl[c][0] for c in self.cells])
        self.n_arr = np.array([self.pl[c][1] for c in self.cells])

    def info(self):
        """One-line description of the map."""
        return (f"{self.name}: cells={len(self.cells)} "
                f"area={self.xmax-self.xmin:.0f}x{self.ymax-self.ymin:.0f} m "
                f"pathloss n_med={self.global_pl[1]:.2f}")
