"""Combination of vulnerability and hazard. RULE-BASED, NOT VALIDATED against any observed outcome.

points = vulnerability class index (0..3) + hazard level (0..3)            -> 0..6
class  : 0-1 Low, 2-3 Moderate, 4-5 High, 6 Severe
score  : (expected vulnerability index + hazard level) / 6                  -> 0..1, an index for ordering/colouring, not a probability
"""
from app.features import CLASS_ORDER

BINS = [(0, 1, "low"), (2, 3, "moderate"), (4, 5, "high"), (6, 6, "severe")]


def combine(vuln_index: int, vuln_expected: float, hazard_level: int) -> tuple[str, float]:
    points = int(vuln_index) + int(hazard_level)
    cls = next(name for lo, hi, name in BINS if lo <= points <= hi)
    assert cls in CLASS_ORDER
    return cls, round((float(vuln_expected) + int(hazard_level)) / 6.0, 4)
