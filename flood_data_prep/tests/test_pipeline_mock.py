"""End-to-end run on fake raw data that mimics the real layout (no network, no gauges, no rivers)."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

import mock_data

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _run(cfg, *a):
    return subprocess.run([sys.executable, str(SCRIPTS / "run_pipeline.py"), "--config", str(cfg), *a], capture_output=True, text=True)


def test_full_pipeline(tmp_path):
    cfg = mock_data.build(tmp_path)
    r = _run(cfg)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    out = r.stdout

    # ---- boundaries: all six polygons used, names taken from the boundary file
    d = pd.read_csv(tmp_path / "data" / "interim" / "districts.csv")
    assert set(d["district_name"]) == set(mock_data.BOXES)

    # ---- rainfall: two overlapping clipped files merged; upstream zone not covered -> dropped, not faked
    rain = pd.read_csv(tmp_path / "data" / "interim" / "rainfall_daily.csv")
    assert "UPSTREAM" not in set(rain["zone_id"]) and rain["rain_mm"].notna().all()
    assert "UPSTREAM series dropped" in out

    proc = pd.read_csv(tmp_path / "data" / "processed" / "district_day_features.csv", parse_dates=["date"])
    allr = pd.read_csv(tmp_path / "data" / "processed" / "district_day_features_all.csv", parse_dates=["date"])
    assert len(allr) > len(proc) > 0                                   # unlabelled days kept for the dashboard only
    assert proc["target_class"].between(0, 3).all()
    assert proc["rain_30d"].notna().all()                              # buffer made long windows complete on day 1
    assert not any(c.startswith(("water_", "upstream_", "has_gauge")) for c in proc.columns)   # absent data -> absent columns
    assert set(proc["split"]) <= {"train", "val", "test"} and "train" in set(proc["split"])

    # ---- labels
    lab = pd.read_csv(tmp_path / "data" / "interim" / "labels_daily.csv", parse_dates=["date"])
    sea = pd.read_csv(tmp_path / "data" / "interim" / "labels_seasonal.csv")
    assert len(sea) == 1 and sea["affected_population"].iloc[0] == 999999       # seasonal total kept apart
    # the seasonal 999999 must not appear on any day
    assert lab.loc[lab.district_id == "dhemaji", "date"].nunique() == lab["date"].nunique()
    known = lab[lab.risk_class.notna()]
    assert known["date"].nunique() < lab["date"].nunique()                      # dry days are UNKNOWN, not zero
    thr = json.loads((tmp_path / "data" / "interim" / "label_thresholds.json").read_text())
    assert thr["method"] == "train_quantile" and thr["train_end"] == "2019-08-31"
    audit = (tmp_path / "reports" / "label_audit.md").read_text()
    assert "Tamulpur" in audit and "Bajali" in audit                           # unmatched + merged reported, not silent
    # Bajali was added to Barpeta
    b = lab[(lab.district_id == "barpeta") & (lab.date == "2019-06-12")]["metric_value"].iloc[0]
    assert b > 100 * 20000 * 0.6 / 150000 - 1e-6

    # ---- static features
    st = pd.read_csv(tmp_path / "data" / "interim" / "static_features.csv")
    assert st["elev_mean_m"].notna().all() and st["dem_valid_pct"].min() > 99
    assert (tmp_path / "reports" / "terrain_quality.csv").exists() and (tmp_path / "reports" / "input_inspection.md").exists()

    # ---- backend export (v2 schema)
    exp = tmp_path / "data" / "backend_export"
    dist = pd.read_csv(exp / "districts.csv")
    assert list(dist.columns) == ["id", "name", "state", "geometry", "mean_elevation_m", "elevation_std_m", "mean_slope_deg",
                                  "low_lying_frac", "pop_density_km2"]
    json.loads(dist["geometry"].iloc[0])
    df = pd.read_csv(exp / "daily_features.csv")
    assert list(df.columns) == ["district_id", "date", "rainfall_mm", "rainfall_3day_cum_mm", "rainfall_7day_cum_mm",
                                "rainfall_15day_cum_mm", "rainfall_30day_cum_mm", "rainfall_deviation_pct", "split",
                                "risk_class_next_day", "risk_class_today"]
    assert df.iloc[:, 2:8].notna().all().all()                                  # NOT NULL in the backend
    assert df["risk_class_next_day"].isna().any() and set(df["risk_class_next_day"].dropna()) <= {"low", "moderate", "high", "severe"}
    assert len(df) == len(allr)
    assert (tmp_path / "reports" / "data_quality.md").exists()


def test_leakage_deviation_baseline_uses_training_only(tmp_path):
    """rainfall_deviation_pct for test rows must not change if test-period rainfall changes."""
    cfg = mock_data.build(tmp_path)
    assert _run(cfg).returncode == 0
    a = pd.read_csv(tmp_path / "data" / "processed" / "district_day_features_all.csv", parse_dates=["date"])
    import xarray as xr, numpy as np
    for f in (tmp_path / "data" / "raw" / "rainfall").glob("rf_part2.nc"):
        ds = xr.open_dataset(f).load(); ds.close()
        late = ds["time"] > np.datetime64("2019-10-01")
        ds["rf"] = ds["rf"].where(~late, ds["rf"] + 300)
        f.unlink(); ds.to_netcdf(f)
    assert _run(cfg).returncode == 0
    b = pd.read_csv(tmp_path / "data" / "processed" / "district_day_features_all.csv", parse_dates=["date"])
    m = a.merge(b, on=["district_id", "date"], suffixes=("_a", "_b"))
    early = m[m["date"] <= "2019-09-30"]
    assert np.allclose(early["rainfall_deviation_pct_a"], early["rainfall_deviation_pct_b"])
    assert not np.allclose(m[m["date"] > "2019-10-05"]["rainfall_deviation_pct_a"], m[m["date"] > "2019-10-05"]["rainfall_deviation_pct_b"])


def test_reference_dir_reuses_ids(tmp_path):
    cfg = mock_data.build(tmp_path)
    assert _run(cfg).returncode == 0
    ref = tmp_path / "backend_data"
    ref.mkdir()
    names = ["Barpeta", "Dhemaji", "Jorhat", "Kamrup Metropolitan", "Karimganj", "Majuli"]
    pd.DataFrame({"id": [7, 3, 9, 5, 11, 2], "name": names}).to_csv(ref / "districts.csv", index=False)
    r = subprocess.run([sys.executable, str(SCRIPTS / "09_export_for_backend.py"), "--config", str(cfg), "--reference-dir", str(ref)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    got = pd.read_csv(tmp_path / "data" / "backend_export" / "districts.csv").set_index("name")["id"].to_dict()
    assert got == dict(zip(names, [7, 3, 9, 5, 11, 2]))
