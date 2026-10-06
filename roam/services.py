# -*- coding: utf-8 -*-
"""Service (traffic) classes following the standardised 5QI values of 3GPP TS 23.501,
Table 5.7.4-1.

Whether a handover is worth its interruption depends on the service: a short break
is severe for real-time gaming (packet delay budget 50 ms) and barely noticeable for
buffered streaming (300 ms).  The thresholds that define an unnecessary handover
and the interruption weight used by the decision rule are therefore per service.

Mapping from the standardised attributes to the model parameters:
  * w_int   (interruption weight) grows as the packet delay budget tightens;
  * T_min   (minimum useful time-of-stay) is longer for GBR / delay-critical flows,
            because a short-lived connection cannot sustain a real-time flow;
  * theta_Q (minimum quality gain) is larger for throughput-driven services
            (streaming), for which a move only pays off if the rate really improves.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    """One service class: 5QI attributes plus the model parameters derived from them."""
    key: str
    name: str
    fiveqi: int          # standardised 5QI value
    resource: str        # GBR / Non-GBR / Delay-critical GBR
    pdb_ms: int          # packet delay budget [ms] (3GPP)
    T_min: float         # minimum useful time-of-stay [s]
    theta_Q: float       # minimum quality gain [dB]
    w_int: float         # interruption weight used in the decision margin
    share: float         # share of the user population


# 5QI / resource type / PDB exactly as in TS 23.501; the last four columns are model parameters.
SERVICES = [
    Service("voice",  "Conversational voice",              1, "GBR",                 100, 4.0, 0.7, 0.35, 0.20),
    Service("vcall",  "Conversational video (video call)", 2, "GBR",                 150, 6.0, 1.0, 0.55, 0.20),
    Service("gaming", "Real-time gaming",                  3, "Delay-critical GBR",   50, 7.0, 1.2, 0.70, 0.15),
    Service("stream", "Buffered video streaming",          6, "Non-GBR",             300, 3.0, 1.5, 0.20, 0.30),
    Service("web",    "Web browsing / background",         9, "Non-GBR",             300, 2.0, 0.4, 0.10, 0.15),
]
