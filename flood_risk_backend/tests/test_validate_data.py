"""Tests for scripts/validate_data.py. Synthetic files in tmp_path only; pandas + stdlib (no database)."""
import hashlib
import json
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import validate_data as V  # noqa: E402

SQ = json.dumps({"type": "Polygon", "coordinates": [[[91.0, 26.0], [91.1, 26.0], [91.1, 26.1], [91.0, 26.1], [91.0, 26.0]]]})
Q = dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140)


def write(folder, name, rows):
    pd.DataFrame(rows).to_csv(os.path.join(folder, name), index=False)


def good_folder(tmp_path, n=3):
    f = tmp_path / "data"
    f.mkdir()
    write(f, "districts.csv", [dict(id=i, name=f"D{i}", state="Assam", geometry=SQ, mean_elevation_m=50.0, elevation_std_m=5.0,
                                    mean_slope_deg=1.0, low_lying_frac=0.3, pop_density_km2=None) for i in range(1, n + 1)])
    write(f, "flood_labels.csv", [dict(district=f"D{i}", year=y, status="reported" if y == 2020 else "unknown",
                                       impact_class="low" if y == 2020 else None, affected_population=10 if y == 2020 else None)
                                  for i in range(1, n + 1) for y in (2019, 2020)])
    write(f, "rainfall_daily.csv", [dict(district_id=1, date=f"2023-07-{d:02d}", rainfall_mm=float(d), n_stations=1) for d in range(1, 6)])
    write(f, "climatology.csv", [dict(district_id=1, window_days=w, doy=doy, n_values=50, n_years=5, **Q) for w in (3, 7) for doy in range(180, 190)])
    write(f, "rainfall_imd_recent.csv", [dict(district_id=1, date="2026-08-19", rainfall_mm=1.5, source="IMD_daily_actual_2026")])
    (f / "hazard_config.json").write_text(json.dumps({"windows": [3, 7], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8}))
    return str(f)


def run(folder, **kw):
    kw.setdefault("expected_districts", 3)
    kw.setdefault("years", (2019, 2020))
    return V.validate(folder, **kw)


def has(r, sev, check, file=None):
    return any(f.severity == sev and f.check == check and (file is None or f.file == file) for f in r.findings)


def tree_hash(folder):
    return {n: hashlib.sha256(open(os.path.join(folder, n), "rb").read()).hexdigest() for n in sorted(os.listdir(folder))}


def test_clean_data_passes_and_files_are_not_modified(tmp_path):
    f = good_folder(tmp_path)
    before = tree_hash(f)
    r = run(f)
    assert r.n("ERROR") == 0, [x.message for x in r.findings if x.severity == "ERROR"]
    assert r.counts["districts.csv"] == 3 and r.counts["flood_labels.csv"] == 6
    assert V.main(["--data-dir", f, "--expected-districts", "3"]) in (0, 1)
    assert tree_hash(f) == before and sorted(os.listdir(f)) == sorted(before)          # nothing changed, nothing added


def test_missing_required_file_and_columns(tmp_path):
    f = good_folder(tmp_path)
    os.remove(os.path.join(f, "districts.csv"))
    assert has(run(f), "ERROR", "missing_file", "districts.csv")
    f2 = good_folder(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path)
    write(f2, "rainfall_daily.csv", [dict(district_id=1, date="2023-07-01")])
    assert has(run(f2), "ERROR", "required_columns", "rainfall_daily.csv")


def test_bad_district_ids_duplicates_and_geometry(tmp_path):
    f = good_folder(tmp_path)
    write(f, "districts.csv", [dict(id=1, name="A", state="Assam", geometry=SQ), dict(id=1, name="B", state="Assam", geometry="not json"),
                               dict(id=2, name="a ", state="Assam", geometry=json.dumps({"type": "Point", "coordinates": [91, 26]}))])
    r = run(f)
    assert has(r, "ERROR", "duplicates", "districts.csv")                    # duplicate id and duplicate normalised name
    assert has(r, "ERROR", "geometry", "districts.csv")
    f2 = good_folder(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path)
    d = pd.read_csv(os.path.join(f2, "districts.csv"))
    d.loc[0, "geometry"] = json.dumps({"type": "Polygon", "coordinates": [[[26.0, 91.0], [26.1, 91.0], [26.1, 91.1], [26.0, 91.0]]]})   # lat/lon swapped
    d.to_csv(os.path.join(f2, "districts.csv"), index=False)
    assert has(run(f2), "WARN", "geometry_extent", "districts.csv")
    d.loc[0, "geometry"] = json.dumps({"type": "Polygon", "coordinates": [[[91.0, 26.0], [91.1, 26.0], [91.0, 26.0]]]})                # ring has < 4 points
    d.to_csv(os.path.join(f2, "districts.csv"), index=False)
    assert has(run(f2), "ERROR", "geometry", "districts.csv")


def test_rainfall_invalid_values_dates_duplicates_and_unknown_district(tmp_path):
    f = good_folder(tmp_path)
    write(f, "rainfall_daily.csv", [
        dict(district_id=1, date="2023-07-01", rainfall_mm=-4.0, n_stations=1),
        dict(district_id=1, date="2023-07-02", rainfall_mm="abc", n_stations=1),
        dict(district_id=1, date="2023-02-31", rainfall_mm=1.0, n_stations=1),          # impossible date
        dict(district_id=1, date="2999-01-01", rainfall_mm=1.0, n_stations=1),          # future
        dict(district_id=1, date="2023-07-03", rainfall_mm=2.0, n_stations=1),
        dict(district_id=1, date="2023-07-03", rainfall_mm=3.0, n_stations=1),          # duplicate key
        dict(district_id=99, date="2023-07-03", rainfall_mm=3.0, n_stations=1),         # unknown district
        dict(district_id=1, date="2023-07-04", rainfall_mm=None, n_stations=1),         # blank: allowed, stays NULL
        dict(district_id=1, date="2023-07-05", rainfall_mm=2000.0, n_stations=1)])
    r = run(f)
    assert has(r, "ERROR", "rainfall_values", "rainfall_daily.csv")
    assert has(r, "ERROR", "type", "rainfall_daily.csv")
    assert has(r, "ERROR", "dates", "rainfall_daily.csv")
    assert has(r, "ERROR", "date_range", "rainfall_daily.csv")
    assert has(r, "WARN", "duplicates", "rainfall_daily.csv") and has(r, "WARN", "district_ids", "rainfall_daily.csv")
    assert has(r, "INFO", "missing_values", "rainfall_daily.csv")                 # blank is reported as missing, never as an error or zero


def test_labels_values_granularity_and_mapping(tmp_path):
    f = good_folder(tmp_path)
    write(f, "flood_labels.csv", [
        dict(district="D1", year=2019, status="reported", impact_class="catastrophic", affected_population=5),    # bad class
        dict(district="D1", year=2020, status="maybe", impact_class=None, affected_population=-3),                # bad status, negative
        dict(district="Atlantis", year=2020, status="unknown"),                                                   # unmapped district
        dict(district="D2", year="2020.5", status="unknown"),                                                     # non-integer year
        dict(district="D2", year=2019, status="unknown", impact_class="high"),                                    # unknown with a class
        dict(district="D2", year=2019, status="unknown")])                                                        # duplicate district-year
    r = run(f)
    assert has(r, "ERROR", "values", "flood_labels.csv") and has(r, "ERROR", "district_mapping") and has(r, "ERROR", "value_range", "flood_labels.csv")
    assert has(r, "ERROR", "type", "flood_labels.csv")
    assert has(r, "WARN", "consistency", "flood_labels.csv") and has(r, "WARN", "duplicates", "flood_labels.csv")


def test_daily_label_columns_are_rejected_as_wrong_granularity(tmp_path):
    f = good_folder(tmp_path)
    write(f, "flood_labels.csv", [dict(district="D1", year=2020, date="2020-07-01", status="reported", impact_class="low")])
    assert has(run(f), "ERROR", "granularity", "flood_labels.csv")


def test_label_names_mapped_to_parent_districts_are_not_unmatched(tmp_path):
    f = good_folder(tmp_path)
    d = pd.read_csv(os.path.join(f, "districts.csv"))
    d.loc[0, "name"] = "Barpeta"
    d.to_csv(os.path.join(f, "districts.csv"), index=False)
    write(f, "flood_labels.csv", [dict(district="Bajali", year=2020, status="unknown"), dict(district="Barpeta", year=2020, status="unknown")])
    r = run(f)
    assert not has(r, "ERROR", "district_mapping") and has(r, "WARN", "duplicates", "flood_labels.csv")


def test_climatology_structure(tmp_path):
    f = good_folder(tmp_path)
    rows = [dict(district_id=1, window_days=3, doy=180, n_values=5, n_years=2, **Q),
            dict(district_id=1, window_days=3, doy=180, n_values=5, n_years=2, **Q),                    # duplicate key
            dict(district_id=1, window_days=3, doy=181, n_values=5, n_years=2, **{**Q, "q90": 5}),      # decreasing quantiles
            dict(district_id=1, window_days=3, doy=400, n_values=5, n_years=2, **Q),                    # doy out of range
            dict(district_id=1, window_days=3, doy=182, n_values=5, n_years=2, **{**Q, "q99": None}),   # blank quantile
            dict(district_id=77, window_days=3, doy=183, n_values=5, n_years=2, **Q),                   # unknown district
            dict(district_id=1, window_days=9, doy=184, n_values=5, n_years=2, **Q)]                    # window not configured
    write(f, "climatology.csv", rows)
    r = run(f)
    for chk in ("duplicates", "structure", "value_range", "missing_values", "district_ids"):
        assert has(r, "ERROR", chk, "climatology.csv"), chk
    assert has(r, "WARN", "windows", "climatology.csv")


def test_imd_source_duplicates_and_values(tmp_path):
    f = good_folder(tmp_path)
    write(f, "rainfall_imd_recent.csv", [
        dict(district_id=1, date="2026-08-19", rainfall_mm=1.0, source="OTHER_SOURCE"),
        dict(district_id=1, date="2026-08-20", rainfall_mm=None, source="IMD_daily_actual_2026"),
        dict(district_id=1, date="2026-08-21", rainfall_mm=2.0, source="IMD_daily_actual_2026"),
        dict(district_id=1, date="2026-08-21", rainfall_mm=3.0, source="IMD_daily_actual_2026"),
        dict(district_id=55, date="2026-08-22", rainfall_mm=3.0, source="IMD_daily_actual_2026")])
    r = run(f)
    for chk in ("source", "missing_values", "duplicates", "district_ids"):
        assert has(r, "ERROR", chk, "rainfall_imd_recent.csv"), chk
    assert V.main(["--data-dir", f, "--expected-districts", "3"]) == 1               # serious failure -> non-zero exit


def test_district_count_and_config_checks(tmp_path):
    f = good_folder(tmp_path)
    assert has(V.validate(f, expected_districts=33, years=(2019, 2020)), "ERROR", "row_count", "districts.csv")
    (tmp_path / "data" / "hazard_config.json").write_text(json.dumps({"windows": [3, -7], "level_quantiles": [0.9, 0.75], "min_obs_fraction": 0.5}))
    r = run(f)
    assert has(r, "ERROR", "values", "hazard_config.json")


def test_row_count_changes_against_baseline_and_database(tmp_path):
    f = good_folder(tmp_path)
    r = run(f, baseline={"rainfall_daily.csv": 100, "climatology.csv": 20, "flood_labels.csv": 6})
    assert has(r, "WARN", "row_count", "rainfall_daily.csv") and not has(r, "WARN", "row_count", "climatology.csv")
    db = str(tmp_path / "x.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rainfall_daily (id INTEGER)")
    con.executemany("INSERT INTO rainfall_daily VALUES (?)", [(i,) for i in range(50)])
    con.commit()
    con.close()
    write(f, "rainfall_daily.csv", [dict(district_id=1, date="2023-07-01", rainfall_mm=None, n_stations=1)][:0] or [dict(district_id=1, date="2023-07-01", rainfall_mm=1.0, n_stations=1)])
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    r = run(f, db_path=db)
    assert has(r, "WARN", "row_count", "rainfall_daily.csv")                        # 1 row vs 50 in the database
    assert hashlib.sha256(open(db, "rb").read()).hexdigest() == before             # database only read


def test_baseline_cannot_be_written_inside_data_folder(tmp_path):
    f = good_folder(tmp_path)
    before = tree_hash(f)
    assert V.main(["--data-dir", f, "--expected-districts", "3", "--write-baseline", os.path.join(f, "counts.json")]) == 2
    assert tree_hash(f) == before
    out = str(tmp_path / "counts.json")
    V.main(["--data-dir", f, "--expected-districts", "3", "--write-baseline", out])
    assert json.load(open(out))["districts.csv"] == 3


def test_shipped_data_has_no_errors():
    folder = os.path.join(os.path.dirname(__file__), "..", "data")
    if not os.path.isfile(os.path.join(folder, "districts.csv")):
        return
    before = tree_hash(folder)
    r = V.validate(folder)
    assert r.n("ERROR") == 0, [f"{x.file}: {x.message}" for x in r.findings if x.severity == "ERROR"]
    assert tree_hash(folder) == before
