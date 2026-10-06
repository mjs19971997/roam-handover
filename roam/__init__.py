"""ROAM: outcome-memory and path-overlap handover decision layer for dense 5G networks.

Modules
-------
radiomap   radio map (cell positions, per-cell path-loss fit) built from drive-test data
mobility   the five mobility profiles
services   the five 5QI service classes
simulator  load-coupled system-level handover simulator and its metrics
policies   ROAM and the baseline decision rules
"""
from .radiomap import RadioMap, load_dataset
from .mobility import PROFILES, PROF_BY_KEY
from .services import SERVICES
from .simulator import SimParams, RadioEnv, gen_traj, assign_services, simulate, area_frac
from .policies import (Base, BaseLayer, RouteTable, LocationTable, A3, ROAM, PBPHS, TrajPred,
                       ToSSkip, MPScreen, STCMAB, ClusterRL)

__version__ = "1.0.0"
