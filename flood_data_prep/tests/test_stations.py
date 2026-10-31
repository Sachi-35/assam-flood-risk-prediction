import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from floodprep import stations as S

DISTRICTS = gpd.GeoDataFrame({"district_id": ["a", "b", "c"], "district_name": ["Alpha", "Beta", "Gamma"]},
                             geometry=[box(90, 26, 91, 27), box(91, 26, 92, 27), box(95, 26, 96, 27)], crs="EPSG:4326")


def write(tmp_path, rows, name="r.csv"):
    pd.DataFrame(rows).to_csv(tmp_path / name, index=False)


def row(station, district, lat, lon, date, rain):
    return {"Station": station, "District": district, "Latitude": lat, "Longitude": lon,
            "Data Acquisition Time": date, "Manual Daily Rainfall (mm)": rain, "Agency": "X"}


def test_missing_stays_missing_negative_invalid_mixed_date_formats(tmp_path):
    write(tmp_path, [row("s1", "Alpha", 26.5, 90.5, "18-02-2013 08:30", "5.0"),
                     row("s1", "Alpha", 26.5, 90.5, "09-03-2021", ""),
                     row("s1", "Alpha", 26.5, 90.5, "10-03-2021", "-999"),
                     row("s1", "Alpha", 26.5, 90.5, "11-03-2021", "NA"),
                     row("s1", "Alpha", 26.5, 90.5, "12-03-2021", "0"),
                     row("s1", "Alpha", 26.5, 90.5, "not a date", "3")])
    df, qc = S.load_station_csvs(tmp_path, None)
    info = qc["files"]["r.csv"]
    assert info["bad_dates"] == 1 and info["negative"] == 1 and info["missing_tokens"] == 2
    r = df.set_index("date")["rain"]
    assert r[pd.Timestamp("2013-02-18")] == 5.0 and r[pd.Timestamp("2021-03-12")] == 0.0       # a real zero is kept as 0
    assert r[pd.Timestamp("2021-03-09")] != r[pd.Timestamp("2021-03-09")]                     # blank stays NaN, not 0
    assert np.isnan(r[pd.Timestamp("2021-03-10")]) and np.isnan(r[pd.Timestamp("2021-03-11")])


def test_dayfirst_parsing(tmp_path):
    write(tmp_path, [row("s1", "Alpha", 26.5, 90.5, "03-04-2021", "1")])
    df, _ = S.load_station_csvs(tmp_path, None)
    assert df["date"].iloc[0] == pd.Timestamp("2021-04-03")                                    # 3 April, not 4 March


def test_missing_column_message(tmp_path):
    pd.DataFrame({"a": [1]}).to_csv(tmp_path / "r.csv", index=False)
    with pytest.raises(ValueError, match="lacks column"):
        S.load_station_csvs(tmp_path, None)


def test_duplicates_counted_and_collapsed(tmp_path):
    write(tmp_path, [row("s1", "Alpha", 26.5, 90.5, "01-07-2020", "10"), row("s1", "Alpha", 26.5, 90.5, "01-07-2020", "10"),
                     row("s2", "Alpha", 26.6, 90.6, "01-07-2020", "4"), row("s2", "Alpha", 26.6, 90.6, "01-07-2020", "8")])
    df, qc = S.load_station_csvs(tmp_path, None)
    assert qc["duplicate_rows"] == 4 and qc["conflicting_duplicate_rows"] == 2
    c = S.collapse_duplicates(df, "mean").set_index("station_id")["rain"]
    assert c["s1__alpha"] == 10 and c["s2__alpha"] == 6


def test_station_assignment_prefers_polygon_and_flags_mismatch():
    df = pd.DataFrame({"station_id": ["x", "y", "z"], "station": ["x", "y", "z"], "district": ["Alpha", "Alpha", "Nowhere"],
                       "lat": [26.5, 26.5, 10.0], "lon": [91.5, 90.5, 70.0], "rain": [1.0, 1.0, 1.0],
                       "date": pd.Timestamp("2020-01-01")})
    st = S.station_table(df, DISTRICTS, None).set_index("station_id")
    assert st.loc["x", "district_id"] == "b" and st.loc["x", "flag_name_mismatch"]               # coordinates say Beta
    assert st.loc["y", "district_id"] == "a" and not st.loc["y", "flag_name_mismatch"]
    assert st.loc["z", "assigned_by"] == "none" and st.loc["z", "flag_outside_assam"]


def test_district_mean_only_over_reporting_stations():
    clean = pd.DataFrame({"station_id": ["s1", "s2", "s1"], "date": pd.to_datetime(["2020-07-01", "2020-07-01", "2020-07-02"]),
                          "rain": [10.0, np.nan, 0.0]})
    st = pd.DataFrame({"station_id": ["s1", "s2"], "district_id": ["a", "a"]})
    out = S.aggregate_to_districts(clean, st).set_index("date")
    assert out.loc["2020-07-01", "rain_mm"] == 10.0 and out.loc["2020-07-01", "n_stations"] == 1     # NaN station not averaged as 0
    assert out.loc["2020-07-02", "rain_mm"] == 0.0


def test_idw_only_for_stationless_districts_within_radius():
    d = pd.date_range("2020-07-01", periods=2)
    clean = pd.DataFrame({"station_id": ["s1"] * 2, "date": d, "rain": [10.0, np.nan], "lat": 26.5, "lon": 91.2})
    st = pd.DataFrame({"station_id": ["s1"], "district_id": ["b"], "lat": [26.5], "lon": [91.2]})
    out = S.idw_fill_districts(clean, st, DISTRICTS, ["a", "c"], radius_km=50)
    assert set(out["district_id"]) == {"a"}                                                          # c is hundreds of km away
    assert len(out) == 1 and out["source"].iloc[0] == "idw" and out["rain_mm"].iloc[0] == 10.0        # NaN day stays missing


def test_conflicting_duplicates_become_missing_and_are_audited(tmp_path):
    import pandas as pd
    from floodprep import stations as ST
    (tmp_path / "a.csv").write_text("Station,District,Latitude,Longitude,Data Acquisition Time,Manual Daily Rainfall (mm)\n"
                                    "S1,Nalbari,26.4,91.4,01-07-2021,10\nS1,Nalbari,26.4,91.4,01-07-2021,30\n"
                                    "S1,Nalbari,26.4,91.4,02-07-2021,5\nS1,Nalbari,26.4,91.4,02-07-2021,5\n"
                                    "S1,Nalbari,26.4,91.4,03-07-2021,1500\nS1,Nalbari,26.4,91.4,04-07-2021,450\n")
    (tmp_path / "b.csv").write_text("station,district,latitude,longitude,data acquisition time,manual daily rainfall(mm)\nS1,Nalbari,26.4,91.4,05-07-2021,2\n")
    raw, qc = ST.load_station_csvs(tmp_path, ["a.csv", "b.csv"], review_mm=300, max_daily_mm=1000)
    assert qc["duplicate_rows"] == 4 and qc["conflicting_duplicate_rows"] == 2
    aud = ST.duplicate_audit(raw)
    assert aud["conflict"].sum() == 2 and len(aud) == 4
    c = ST.collapse_duplicates(raw, "missing").set_index("date")["rain"]
    assert pd.isna(c[pd.Timestamp("2021-07-01")]) and c[pd.Timestamp("2021-07-02")] == 5          # conflict -> missing, identical -> value
    assert pd.isna(c[pd.Timestamp("2021-07-03")]) and c[pd.Timestamp("2021-07-04")] == 450         # >max excluded; >review kept
    assert set(raw.loc[raw["flag"] != "", "flag"]) == {"above_max_excluded", "review_extreme"}
    assert raw.loc[raw["flag"] == "above_max_excluded", "rain_raw"].iloc[0] == 1500                # original kept for the audit
    assert ST.collapse_duplicates(raw, "max").set_index("date")["rain"][pd.Timestamp("2021-07-01")] == 30
