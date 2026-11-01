"""CHIRPS v3 as the primary rainfall source, tested end to end against a LOCAL archive with the official layout
(<base>/final/<product>/<year>/<daily .tif>). Nothing here touches the network; the real CHC server was not reachable from the build
environment, so the HTTP path itself is only exercised by the live run (see README). Fixture values are hand-made plumbing data."""
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr
import yaml
from rasterio.transform import from_origin

import mock_data
from floodprep.zonal import zonal_mean

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
Y0, Y1 = 2012, 2023


def make_archive(root: Path, bounds, product="sat", skip=(), nodata_days=()):
    """One daily GeoTIFF per day, 0.05 deg, nodata -9999, over `bounds` plus a margin. Returns the archive base folder."""
    x0, y0, x1, y1 = bounds
    x0, y0 = np.floor(x0) - 1, np.floor(y0) - 1
    x1, y1 = np.ceil(x1) + 1, np.ceil(y1) + 1
    w, h = int(round((x1 - x0) / 0.05)), int(round((y1 - y0) / 0.05))
    tr = from_origin(x0, y1, 0.05, 0.05)
    rng = np.random.default_rng(3)
    wet = {y: rng.normal() for y in range(Y0, Y1 + 1)}
    base = root / "archive"
    for d in pd.date_range(f"{Y0}-01-01", f"{Y1}-12-31"):
        if d in skip:
            continue
        seas = 3 + 14 * np.exp(-((d.dayofyear - 200) ** 2) / (2 * 40 ** 2))
        arr = (rng.gamma(0.5, 1.0, (h, w)) * seas * np.exp(0.35 * wet[d.year])).astype("float32")
        if d in nodata_days:
            arr[:, : w // 2] = -9999                                  # half of the grid has no data that day
        folder = base / "final" / product / str(d.year)
        folder.mkdir(parents=True, exist_ok=True)
        with rasterio.open(folder / f"chirps-v3.0.{product}.{d:%Y.%m.%d}.tif", "w", driver="GTiff", height=h, width=w, count=1,
                           dtype="float32", crs="EPSG:4326", transform=tr, nodata=-9999) as dst:
            dst.write(arr, 1)
    return base


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("chirps")
    cfg_path = mock_data.build_seasonal(root)
    cfg = yaml.safe_load(cfg_path.read_text())
    g = gpd.read_file(root / "data" / "raw" / "boundaries" / "assam_districts.geojson")
    skip = set(pd.date_range("2013-03-03", "2013-03-03"))
    gap = pd.date_range("2021-06-01", "2021-09-30")                      # a missing download period inside a labelled season
    base = make_archive(root, tuple(g.total_bounds), skip=skip | set(gap), nodata_days={pd.Timestamp("2014-07-01")})
    cfg["rainfall"]["source"] = "chirps_v3"
    cfg["rainfall"]["chirps_v3"].update(base_url=str(base), start_date=f"{Y0}-01-01", end_date=f"{Y1}-12-31", product="sat")
    cfg["hazard"].update(baseline_years=[Y0, 2018], min_normal_years=5)
    cfg["rainfall"]["station_csv"]["files"] = ["rainfall_assam_1991_2020.csv", "rainfall_assam_2021_2025.csv"]
    cfg["project"]["end_date"] = "2023-12-31"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    r = subprocess.run([sys.executable, str(SCRIPTS / "02_download_rainfall.py"), "--config", str(cfg_path), "--workers", "4"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    r = subprocess.run([sys.executable, str(SCRIPTS / "run_pipeline.py"), "--config", str(cfg_path), "--no-compare"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-5000:] + r.stderr[-3000:]
    return root, cfg_path


def test_download_subsets_and_labels_files(proj):
    root, _ = proj
    f = root / "data" / "raw" / "rainfall" / "chirps_v3_sat_2015.nc"
    with xr.open_dataset(f) as ds:
        assert ds.attrs["product"] == "CHIRPS-v3.0" and ds.attrs["version"] == "3.0" and ds.attrs["units"] == "mm/day" and ds.attrs["stage"] == "final"
        assert ds["precip"].shape[0] == 365 and ds["lat"].values[0] < ds["lat"].values[-1]
        assert float(ds["precip"].max()) < 1500 and float(ds["precip"].min()) >= 0
        assert ds["lon"].size < 400                                          # window of the bbox, not a global grid
    man = pd.read_csv(root / "reports" / "chirps_v3_download_manifest.csv")
    assert (man["status"] == "missing").sum() == 122 + 1 and (man["status"] == "ok").sum() > 4000


def test_missing_and_nodata_days_are_nan_not_zero(proj):
    root, _ = proj
    with xr.open_dataset(root / "data" / "raw" / "rainfall" / "chirps_v3_sat_2013.nc") as ds:
        day = ds["precip"].sel(time="2013-03-03")
        assert bool(day.isnull().all())                                      # file absent -> NaN
    with xr.open_dataset(root / "data" / "raw" / "rainfall" / "chirps_v3_sat_2014.nc") as ds:
        d = ds["precip"].sel(time="2014-07-01").values
        assert np.isnan(d).any() and not (d == 0).any() and (d >= 0)[~np.isnan(d)].all()   # -9999 fill -> NaN
    rd = pd.read_csv(root / "data" / "interim" / "rainfall_daily.csv", parse_dates=["date"])
    miss = rd[(rd.date >= "2021-06-01") & (rd.date <= "2021-09-30")]
    assert miss["rain_mm"].isna().all() and (rd["source"] == "chirps_v3").all()


def test_all_districts_have_rainfall_and_stations_are_supplementary(proj):
    root, _ = proj
    rd = pd.read_csv(root / "data" / "interim" / "rainfall_daily.csv")
    assert rd["zone_id"].nunique() == 12 and "goalpara" in set(rd["zone_id"])       # grid covers a district that has no station
    st = root / "data" / "interim" / "rainfall_daily_stations.csv"
    assert st.exists() and (root / "reports" / "chirps_vs_stations.md").exists()
    assert not set(pd.read_csv(st)["zone_id"]) >= {"goalpara"}                       # stations stay separate, no IDW
    assert (pd.read_csv(root / "data" / "raw" / "rainfall" / "rainfall_assam_1991_2020.csv", dtype=str).shape[0] > 1000)   # originals untouched


def test_unavailable_district_years_are_flagged_not_dropped(proj):
    root, _ = proj
    tab = pd.read_csv(root / "data" / "processed" / "model_table_seasonal.csv")
    lab = pd.read_csv(root / "data" / "interim" / "labels_annual.csv")
    assert len(tab) == int(lab["metric_value"].notna().sum())                        # every labelled district-year is still there
    bad = tab[tab["rainfall_status"] != "ok"]
    assert set(bad["year"]) == {2021} and len(bad) >= 5 and bad["season_total_mm"].isna().all()
    assert bad["rainfall_status"].str.contains("observed").all()                     # reason names the observed/needed days
    ok = tab[tab["rainfall_status"] == "ok"]
    assert len(ok) > 20 and ok["season_total_mm"].notna().all()
    sf = pd.read_csv(root / "data" / "backend_export" / "season_features.csv")
    assert len(sf) == len(tab) and (sf["rainfall_status"] != "ok").sum() == len(bad)


def test_climatology_uses_reference_years_only(proj):
    root, _ = proj
    cov = pd.read_csv(root / "reports" / "climatology_coverage.csv")
    assert (cov["reference_years_requested"] == f"{Y0}-2018").all()
    assert cov["years_with_window_totals"].str.split(",").map(lambda y: max(map(int, y))).max() <= 2018      # nothing from label years
    hc = json.loads((root / "data" / "backend_export" / "hazard_config.json").read_text())
    assert hc["baseline_years"] == [Y0, 2018]


def test_v2_or_unlabelled_files_are_refused(tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    import importlib
    m = importlib.import_module("03_extract_rainfall")
    cc = {"product": "sat"}
    ds = xr.Dataset({"precip": (("time", "lat", "lon"), np.zeros((1, 2, 2)))}, coords={"time": pd.to_datetime(["2020-01-01"]), "lat": [26, 27], "lon": [90, 91]})
    with pytest.raises(ValueError, match="not a CHIRPS v3.0 file"):
        m.check_chirps_v3(Path("chirps_erddap_2020.nc"), ds, cc)
    ds.attrs.update(product="CHIRPS-v3.0", version="3.0", units="mm/day", stage="final", daily_product="rnl")
    with pytest.raises(ValueError, match="No silent product switching"):
        m.check_chirps_v3(Path("x.nc"), ds, cc)
    ds.attrs["daily_product"] = "sat"
    m.check_chirps_v3(Path("x.nc"), ds, cc)


def test_zonal_requires_enough_valid_cells():
    from shapely.geometry import box
    lat, lon = np.array([26.025, 26.075, 26.125, 26.175]), np.array([90.025, 90.075, 90.125, 90.175])
    a = np.full((2, 4, 4), 10.0)
    a[1, :, :2] = np.nan                                                    # day 2: half of the cells missing
    ds = xr.Dataset({"precip": (("time", "lat", "lon"), a)}, coords={"time": pd.to_datetime(["2020-01-01", "2020-01-02"]), "lat": lat, "lon": lon})
    ds["precip"].attrs["units"] = "mm/day"
    z = {"d": box(90.0, 26.0, 90.2, 26.2)}
    loose, _, _ = zonal_mean(ds, z)
    strict, _, _ = zonal_mean(ds, z, min_valid_weight=0.9)
    assert loose["rain_mm"].tolist() == [10.0, 10.0]                         # old behaviour: mean over what is left
    assert strict["rain_mm"].iloc[0] == 10.0 and np.isnan(strict["rain_mm"].iloc[1])
