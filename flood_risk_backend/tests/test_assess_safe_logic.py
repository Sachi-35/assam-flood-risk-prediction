"""Pure-logic tests for scripts/assess_safe.py (no database): calculation parity with the scalar hazard functions, diffing, planning."""
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace as NS

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import assess_safe as A  # noqa: E402
from app.services import hazard as H  # noqa: E402
from app.services.risk_rules import combine  # noqa: E402

LQ = [0.75, 0.9, 0.97]
Q = {3: dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140), 7: dict(q50=20, q75=60, q90=120, q95=150, q97=180, q99=250)}
RAIN = {date(2023, 7, 1) + timedelta(days=i): v for i, v in enumerate([0, 5, 50, 0, None, 10, 80, 5, 0, 0]) if v is not None}
CLIM = {(1, w): pd.DataFrame([{"doy": d, **q} for d in range(150, 260)]) for w, q in Q.items()}
VUL = {1: {"class_index": 2, "expected_index": 2.0, "model_version": None}}
LO, HI = pd.Timestamp("2023-07-01"), pd.Timestamp("2023-07-10")


def _rows(rain=None, vul=None, clim=None, ids=(1,)):
    rain = {1: {pd.Timestamp(k): v for k, v in RAIN.items()}} if rain is None else rain
    return A.build_assessment_rows(list(ids), rain, CLIM if clim is None else clim, VUL if vul is None else vul, LO, HI, [3, 7], 0.8, LQ)


def test_rows_match_scalar_hazard_functions_for_every_day():
    rows = _rows()
    assert len(rows) == 20
    for r in rows:
        tot, frac = H.window_total(RAIN, r["as_of_date"], r["window_days"], 0.8)
        qrow = Q[r["window_days"]]
        lvl = H.level_for_total(tot, qrow, LQ)
        assert r["window_rain_mm"] == tot and abs(r["obs_fraction"] - frac) < 1e-12
        assert r["hazard_level"] == lvl
        if tot is None:
            assert r["status"] == "insufficient_rainfall_data" and r["combined_class"] is None
        else:
            assert r["status"] == "ok"
            assert (r["combined_class"], r["combined_score"]) == combine(2, 2.0, lvl)


def test_missing_rain_is_unknown_never_zero_or_low():
    rows = _rows(rain={1: {pd.Timestamp("2023-07-01"): 0.0}})
    late = [r for r in rows if r["as_of_date"] >= date(2023, 7, 8)]
    assert late and all(r["window_rain_mm"] is None and r["hazard_level"] is None and r["combined_class"] is None for r in late)
    assert all(r["status"] == "insufficient_rainfall_data" for r in late)


def test_district_without_rain_gets_unknown_rows():
    rows = _rows(ids=(1, 7))
    r7 = [r for r in rows if r["district_id"] == 7]
    assert len(r7) == 20 and all(r["status"] == "insufficient_rainfall_data" and r["obs_fraction"] == 0.0 and r["hazard_level"] is None for r in r7)


def test_no_climatology_and_no_vulnerability_statuses():
    assert {r["status"] for r in _rows(clim={}) if r["window_rain_mm"] is not None} == {"no_climatology"}
    ok = [r for r in _rows(vul={}) if r["window_rain_mm"] is not None]
    assert {r["status"] for r in ok} == {"vulnerability_unavailable"} and all(r["hazard_level"] is not None and r["combined_class"] is None for r in ok)


def test_diff_insert_update_unchanged():
    planned = _rows()
    existing = {(r["district_id"], r["as_of_date"], r["window_days"]): {"id": i, **{f: r[f] for f in A.ASSESS_FIELDS}} for i, r in enumerate(planned[:10], 1)}
    existing[(1, date(2023, 7, 2), 3)]["hazard_level"] = 3                      # drifted value
    ins, upd, same = A.diff_assessments(existing, planned)
    assert len(ins) == 10 and len(upd) == 1 and same == 9
    assert upd[0]["id"] == existing[(1, date(2023, 7, 2), 3)]["id"] and upd[0]["hazard_level"] == planned[[(r["as_of_date"], r["window_days"]) for r in planned].index((date(2023, 7, 2), 3))]["hazard_level"]
    assert A.diff_assessments({(r["district_id"], r["as_of_date"], r["window_days"]): {"id": 1, **r} for r in planned}, planned) == ([], [], 20)


def test_range_and_window_validation():
    for s, e in (("2023-07-10", "2023-07-01"), ("not-a-date", "2023-07-01")):
        try:
            A.parse_range(s, e, [])
            raise AssertionError("should refuse")
        except A.Refused:
            pass
    try:
        A.parse_range(None, None, [])
        raise AssertionError("should refuse")
    except A.Refused:
        pass
    assert A.parse_range(None, None, [pd.Timestamp("2020-01-05"), pd.Timestamp("2020-02-01")]) == (pd.Timestamp("2020-01-05"), pd.Timestamp("2020-02-01"))
    for bad in ([], [0], [-3], [3.5]):
        try:
            A.check_windows(bad)
            raise AssertionError("should refuse")
        except A.Refused:
            pass
    assert A.check_windows([7, 3, 7]) == [3, 7]


def _lab(status, cls=None):
    return NS(status=status, impact_class=cls)


def test_plan_vulnerabilities_history_only_and_ml_gated_off():
    dists = [NS(id=1, name="A"), NS(id=2, name="B"), NS(id=3, name="C")]
    labels = {1: [_lab("reported", "high"), _lab("reported", "moderate"), _lab("unknown")], 2: [_lab("reported", "severe")]}
    bundle = object()                                                   # would crash if the ML route were taken
    meta = {"vulnerability_source": "ml_model"}
    v, missing = A.plan_vulnerabilities(dists, labels, {1: {"season_total_mm": 1.0}}, meta, bundle, allow_ml=False)
    assert set(v) == {1} and v[1]["source"] == "district_history" and v[1]["class_index"] == 2 and v[1]["expected_index"] == 1.5
    assert len(missing) == 2 and "need 2" in missing[0]                 # B: 1 known year; C: none; Unknown is never defaulted


def test_diff_vulnerabilities_counts():
    old = {1: {"source": "district_history", "risk_class": "high", "class_index": 2, "expected_index": 2.0, "model_version": None}, 2: {"source": "district_history", "risk_class": "low", "class_index": 0, "expected_index": 0.0, "model_version": None}}
    new = {1: dict(old[1], class_index=3), 3: dict(old[1])}
    d = A.diff_vulnerabilities(old, new)
    assert d["added"] == [3] and d["removed"] == [2] and d["changed"] == [1] and d["unchanged"] == 0
