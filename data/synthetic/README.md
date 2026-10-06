# Synthetic layouts

Three synthetic dense-urban drive-test tables created by the authors for this study.
They are distributed under the licence of this repository.

| File | Environment name | Cells | Samples |
|---|---|---|---|
| `realistic_5G_drive_test.csv` | `UDN-20` | 20 | 10000 |
| `realistic_5G_2x.csv` | `UDN-40` | 40 | 20000 |
| `realistic_5G_3x.csv` | `UDN-60` | 60 | 30000 |

Columns: `Lon, Lat, RSRP, RSRQ, CINR, PCI, Height (m), Distance (m), Azimuth, Elevation, Speed (m/s)`.
The simulator uses `Lon`, `Lat`, `RSRP`, `PCI`, `Distance (m)` and `Azimuth` to estimate the
cell positions and a per-cell path-loss model (`roam/radiomap.py`).
