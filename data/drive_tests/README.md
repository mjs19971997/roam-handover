# Measured drive-test traces (not distributed)

The `real` experiment block uses three measured drive-test traces published with

> J. P. S. H. Lima et al., "Deep Learning-Based Handover Prediction for 5G and Beyond
> Networks," IEEE ICC 2023. doi: 10.1109/ICC45041.2023.10279195

Source repository: <https://github.com/jpshlima/lstm-handover>

That repository does not state a licence, so the files are not redistributed here. To run
the `real` block, download the three files from the source repository and place them in this
directory under their original names:

```
data/drive_tests/drive_test_measurements01.csv
data/drive_tests/drive_test_measurements02.csv
data/drive_tests/drive_test_measurements03.csv
```

Expected columns (the first, unnamed column is a row index):

```
,Lon,Lat,RSRP,RSRQ,CINR,PCI,Height (m),Distance (m),Azimuth,Elevation
```

In the code the traces are the environments `DT01`, `DT02` and `DT03`
(`experiments/common.py`). All other experiment blocks, the tuning and the quick-start
example run without these files. Please cite the paper above when you use the traces.
