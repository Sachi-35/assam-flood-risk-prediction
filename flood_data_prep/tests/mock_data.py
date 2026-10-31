"""Build a tiny, fully fake raw-data tree that mimics the REAL dataset layout, so the pipeline can run end to end offline.

    python tests/mock_data.py /tmp/mockproj
    python scripts/run_pipeline.py --config /tmp/mockproj/config.yaml

Mimics: boundaries with fields dt_code/district/st_code/year/st_nm (incl. Karimganj, Kamrup Metropolitan, Majuli);
NetCDF rainfall variable 'rf' split over two overlapping files and CLIPPED to Assam (so the default upstream zone is not covered);
labels in data/processed/labels/annual with audit columns and mixed granularity (daily / period / seasonal) and the names
'Bajali' (merged into Barpeta), 'Sribhumi' (alias of Karimganj) and 'Tamulpur' (unmatched); a DEM and a population raster;
NO gauge, rivers or land cover. The numbers are random: this proves the plumbing, not anything about real floods.
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
import yaml
from rasterio.transform import from_origin
from shapely.geometry import box

BOXES = {  # name: (lon0, lat0, lon1, lat1)
    "Dhemaji": (94.3, 27.2, 95.0, 27.8),
    "Majuli": (94.1, 26.8, 94.5, 27.1),
    "Barpeta": (90.8, 26.2, 91.4, 26.7),
    "Karimganj": (92.2, 24.4, 92.8, 24.9),
    "Kamrup Metropolitan": (91.5, 26.0, 91.9, 26.3),
    "Jorhat": (94.0, 26.4, 94.6, 26.75),
}
GRID = [89.5, 24.0, 96.1, 28.0]  # rainfall grid clipped to Assam (lon0, lat0, lon1, lat1)
DEM_BBOX = [89.5, 24.0, 96.1, 28.0]


def build(root: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    root = Path(root).resolve()
    raw = root / "data" / "raw"
    for sub in ["boundaries", "rainfall", "terrain", "population"]:
        (raw / sub).mkdir(parents=True, exist_ok=True)
    lab_dir = root / "data" / "processed" / "labels" / "annual"
    lab_dir.mkdir(parents=True, exist_ok=True)

    gdf = gpd.GeoDataFrame({"dt_code": [f"{i:03d}" for i in range(len(BOXES))], "district": list(BOXES), "st_code": "18",
                            "year": 2020, "st_nm": "Assam", "geometry": [box(*b) for b in BOXES.values()]}, crs="EPSG:4326")
    gdf.to_file(raw / "boundaries" / "assam_districts.geojson", driver="GeoJSON")

    # rainfall: 0.25 deg grid, variable 'rf', two overlapping files (identical values on the overlap)
    lats, lons = np.arange(GRID[1], GRID[3] + 1e-9, 0.25), np.arange(GRID[0], GRID[2] + 1e-9, 0.25)
    times = pd.date_range("2019-03-01", "2019-10-31", freq="D")
    base = rng.gamma(0.6, 6.0, size=(len(times), len(lats), len(lons)))
    for s, e in [("2019-06-10", "2019-06-14"), ("2019-07-20", "2019-07-26"), ("2019-09-02", "2019-09-05")]:
        m = (times >= s) & (times <= e)
        base[m] += rng.gamma(3.0, 25.0, size=(m.sum(), len(lats), len(lons)))
    base[5, 3, 3] = -999.0  # fill value must become NaN
    for name, a, b in [("rf_part1.nc", "2019-03-01", "2019-08-15"), ("rf_part2.nc", "2019-08-01", "2019-10-31")]:
        m = (times >= a) & (times <= b)
        xr.Dataset({"rf": (("time", "lat", "lon"), base[m].astype("float32"), {"units": "mm/day"})},
                   coords={"time": times[m], "lat": lats, "lon": lons}).to_netcdf(raw / "rainfall" / name)

    def write(path, arr, dtype, nodata):
        tf = from_origin(DEM_BBOX[0], DEM_BBOX[3], 0.01, 0.01)
        with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=dtype,
                           crs="EPSG:4326", transform=tf, nodata=nodata) as dst:
            dst.write(arr.astype(dtype), 1)

    h, w = int((DEM_BBOX[3] - DEM_BBOX[1]) / 0.01), int((DEM_BBOX[2] - DEM_BBOX[0]) / 0.01)
    yy, xx = np.mgrid[0:h, 0:w]
    dem = 50 + 0.05 * yy + 5 * np.sin(xx / 40.0)
    dem[:40, :40] = -9999.0  # nodata corner (outside every district)
    write(raw / "terrain" / "dem.tif", dem, "float32", -9999.0)
    write(raw / "population" / "population.tif", np.full((h, w), 50.0), "float32", -9999.0)

    # labels: daily reports during three episodes; one period row; seasonal totals
    ev = [("2019-06-12", "2019-06-18", {"Dhemaji": 60000, "Majuli": 30000, "Bajali": 20000, "Barpeta": 5000}),
          ("2019-07-22", "2019-08-02", {"Dhemaji": 200000, "Sribhumi": 5000, "Jorhat": 800, "Barpeta": 40000, "Bajali": 30000}),
          ("2019-09-03", "2019-09-08", {"Majuli": 15000, "Tamulpur": 100})]
    rows = []
    for s, e, hit in ev:
        for day in pd.date_range(s, e):
            for dist, n in hit.items():
                rows.append({"district": dist, "date": day.strftime("%Y-%m-%d"),
                             "affected_population": int(n * rng.uniform(0.6, 1.0)), "period_start": "", "period_end": "",
                             "label_granularity": "daily", "source_pdf": "daily.pdf", "source_section": "table 2"})
    rows.append({"district": "Dhemaji", "date": "2019-10-31", "affected_population": 999999, "period_start": "2019-05-01",
                 "period_end": "2019-10-31", "label_granularity": "seasonal", "source_pdf": "memo.pdf", "source_section": "total"})
    rows.append({"district": "Majuli", "date": "2019-09-30", "affected_population": 12345, "period_start": "2019-09-20",
                 "period_end": "2019-09-30", "label_granularity": "period", "source_pdf": "memo.pdf", "source_section": "wave 3"})
    pd.DataFrame(rows).to_csv(lab_dir / "labels_2019_audit.csv", index=False)

    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "config.yaml").read_text())
    cfg["project_root"] = str(root)
    cfg["project"].update(start_date="2019-05-01", end_date="2019-10-31", mode="daily")
    cfg["rainfall"]["source"] = "netcdf"
    cfg["labels"]["input_dir"] = str(lab_dir)
    cfg["paths"] = {k: str(root / v) for k, v in cfg["paths"].items()}
    cfg["districts"]["boundary_file"] = str(raw / "boundaries" / "assam_districts.geojson")
    cfg["labels"]["min_positive_train_rows"] = 10
    cfg["splits"] = {"train_end": "2019-08-31", "val_end": "2019-09-30"}
    cfg["terrain"]["downsample_factor"] = 1
    (root / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return root / "config.yaml"


SEAS_BOXES = {  # 12 districts on a grid; Goalpara has NO station (tests the IDW fallback) and touches Dhubri
    "Dhubri": (89.8, 26.0, 90.2, 26.4), "Goalpara": (90.2, 26.0, 90.6, 26.4), "Barpeta": (90.8, 26.2, 91.2, 26.6),
    "Baksa": (91.4, 26.4, 91.8, 26.8), "Kamrup Metropolitan": (91.6, 26.0, 91.9, 26.3), "Nagaon": (92.4, 26.2, 92.8, 26.6),
    "Karimganj": (92.2, 24.4, 92.6, 24.8), "Jorhat": (94.0, 26.4, 94.4, 26.8), "Majuli": (94.1, 26.9, 94.5, 27.2),
    "Dhemaji": (94.5, 27.3, 94.9, 27.7), "Tinsukia": (95.3, 27.4, 95.7, 27.8), "Cachar": (92.6, 24.6, 93.0, 25.0),
}


def build_seasonal(root: Path, seed: int = 0, last_year: int = 2024) -> Path:
    """Mock data in the REAL shape: station CSVs 1991..2024 (two files, mixed date formats, gaps, bad rows), annual label CSVs
    (authoritative + provisional + summary), DEM and population rasters. Impact is generated from season wetness and low-lying share
    so the pipeline has something real to find, and the numbers are random: this proves plumbing, not anything about real floods."""
    rng = np.random.default_rng(seed)
    root = Path(root).resolve()
    raw = root / "data" / "raw"
    for sub in ["boundaries", "rainfall", "terrain", "population"]:
        (raw / sub).mkdir(parents=True, exist_ok=True)
    lab_dir = root / "data" / "processed" / "labels" / "annual"
    lab_dir.mkdir(parents=True, exist_ok=True)

    names = list(SEAS_BOXES)
    gdf = gpd.GeoDataFrame({"dt_code": [f"{i:03d}" for i in range(len(names))], "district": names, "st_code": "18", "year": 2020,
                            "st_nm": "Assam", "geometry": [box(*b) for b in SEAS_BOXES.values()]}, crs="EPSG:4326")
    gdf.to_file(raw / "boundaries" / "assam_districts.geojson", driver="GeoJSON")

    # ---- rasters (DEM: low in the west, so western districts are lower-lying) -------------------------------------------
    bb = [89.5, 24.0, 96.1, 28.0]
    h, w = int((bb[3] - bb[1]) / 0.01), int((bb[2] - bb[0]) / 0.01)
    yy, xx = np.mgrid[0:h, 0:w]

    def write(path, arr, nodata):
        with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(bb[0], bb[3], 0.01, 0.01), nodata=nodata) as dst:
            dst.write(arr.astype("float32"), 1)

    dem = 30 + 0.12 * xx + 4 * np.sin(yy / 30.0)
    dem[:30, :30] = -9999.0
    write(raw / "terrain" / "dem.tif", dem, -9999.0)
    write(raw / "population" / "population.tif", np.full((h, w), 50.0), -99999.0)

    # ---- stations --------------------------------------------------------------------------------------------------------
    stations = []
    for nm, (x0, y0, x1, y1) in SEAS_BOXES.items():
        if nm == "Goalpara":
            continue
        for k in range(2):
            stations.append({"Station": f"{nm} S{k + 1}", "District": nm, "Latitude": round(y0 + (y1 - y0) * (0.3 + 0.4 * k), 5),
                             "Longitude": round(x0 + (x1 - x0) * (0.3 + 0.4 * k), 5), "Agency": "AWD"})
    stations.append({"Station": "Wrong district S", "District": "Nagaon", "Latitude": 26.3, "Longitude": 91.0, "Agency": "AWD"})  # lies in Barpeta
    stations.append({"Station": "Outside S", "District": "Nagaon", "Latitude": 12.0, "Longitude": 77.0, "Agency": "AWD"})          # outside Assam
    years = list(range(1991, last_year + 1))
    wet = {y: rng.normal(0, 1) for y in years}                               # seasonal wetness of each year
    dfac = {nm: rng.normal(0, 0.25) for nm in names}
    days = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31")
    doy = days.dayofyear.to_numpy()
    seas = 3 + 14 * np.exp(-((doy - 200) ** 2) / (2 * 40 ** 2))
    ywet = np.array([wet[d.year] for d in days])
    recs = []
    for st in stations:
        base = rng.gamma(0.5, 1.0, len(days)) * seas * np.exp(0.35 * ywet + dfac.get(st["District"], 0))
        rain = np.round(base, 1)
        miss = rng.random(len(days)) < 0.08
        gap = np.zeros(len(days), bool)
        if st["Station"].endswith("S2"):
            gap[(days >= f"{rng.integers(1995, 2015)}-06-01") & (days <= f"{rng.integers(2016, 2018)}-08-31")] = rng.random() < 0.5
        keep = ~gap
        d = days[keep]
        df = pd.DataFrame({**{k: v for k, v in st.items()}, "Date": d, "Rain": rain[keep], "m": miss[keep]})
        recs.append(df)
    allr = pd.concat(recs, ignore_index=True)
    allr["Manual Daily Rainfall (mm)"] = np.where(allr["m"], "", allr["Rain"].astype(str))
    allr.loc[rng.random(len(allr)) < 0.0005, "Manual Daily Rainfall (mm)"] = "-999"            # invalid code
    f1 = allr[allr["Date"] < "2021-01-01"].copy()
    f2 = allr[allr["Date"] >= "2021-01-01"].copy()
    f1["Data Acquisition Time"] = f1["Date"].dt.strftime("%d-%m-%Y 08:30")
    f2["Data Acquisition Time"] = f2["Date"].dt.strftime("%d-%m-%Y")
    cols = ["Station", "District", "Latitude", "Longitude", "Data Acquisition Time", "Manual Daily Rainfall (mm)", "Agency"]
    f1[cols].assign(SlNo=range(len(f1))).to_csv(raw / "rainfall" / "rainfall_assam_1991_2020.csv", index=False)
    f2[cols].assign(_id=range(len(f2))).to_csv(raw / "rainfall" / "rainfall_assam_2021_2025.csv", index=False)
    dup = f2[cols].head(5)                                                                    # exact duplicates are tolerated
    dup.to_csv(raw / "rainfall" / "rainfall_assam_2021_2025.csv", mode="a", header=False, index=False, columns=cols)

    # ---- labels (impact grows with wetness and low-lying share) ----------------------------------------------------------------
    pop = 1600 * 50.0
    lowness = {nm: 1.0 - (SEAS_BOXES[nm][0] - 89.5) / 6.6 for nm in names}
    lab, prov = [], []
    for y in range(2019, 2024):
        for nm in names:
            if rng.random() < 0.25:      # not listed this year
                continue
            z = 1.2 * wet[y] + 2.0 * lowness[nm] + rng.normal(0, 0.5) - 1.0
            pct = 100 / (1 + np.exp(-2 * z)) * 0.5
            n = int(pop * pct / 100)
            lab.append({"year": y, "district": nm, "period_start": f"{y}-05-01", "period_end": f"{y}-10-31", "affected_population": n,
                        "label_granularity": "seasonal", "source_pdf": f"memo_{y}.pdf", "source_section": "district table",
                        "source_page": 3, "quality_flag": "ok"})
            prov.append({"district": nm, "affected_population": int(n * rng.choice([1.0, 1.0, 1.1])), "date": f"{y}-11-01", "year": y})
    lab.append({**lab[0], "affected_population": lab[0]["affected_population"] - 1, "source_section": "repeat"})       # duplicate district-year
    lab.append({"year": 2021, "district": "Bajali", "period_start": "2021-05-01", "period_end": "2021-10-31", "affected_population": 1200,
                "label_granularity": "seasonal", "source_pdf": "memo_2021.pdf", "source_section": "district table", "source_page": 3,
                "quality_flag": "ok"})
    lab.append({"year": 2022, "district": "Tamulpur", "period_start": "2022-05-01", "period_end": "2022-10-31", "affected_population": 900,
                "label_granularity": "seasonal", "source_pdf": "memo_2022.pdf", "source_section": "district table", "source_page": 3,
                "quality_flag": "ok"})
    lab.append({"year": 2022, "district": "Karbi Anglong West", "period_start": "2022-05-01", "period_end": "2022-10-31", "affected_population": 500,
                "label_granularity": "seasonal", "source_pdf": "memo_2022.pdf", "source_section": "district table", "source_page": 3,
                "quality_flag": "ok"})
    lab.append({"year": 2022, "district": "Dhemaji", "period_start": "2022-06-10", "period_end": "2022-06-12", "affected_population": 777,
                "label_granularity": "daily", "source_pdf": "daily.pdf", "source_section": "table", "source_page": 1, "quality_flag": "ok"})
    pd.DataFrame(lab).to_csv(lab_dir / "seasonal_flood_labels_all_years.csv", index=False)
    pd.DataFrame(prov).to_csv(lab_dir / "seasonal_flood_labels_2019_2023_provisional.csv", index=False)
    pd.DataFrame({"year": range(2019, 2024), "rows": 10, "districts": 10}).to_csv(lab_dir / "annual_dataset_summary.csv", index=False)

    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "config.yaml").read_text())
    cfg["project_root"] = str(root)
    cfg["paths"] = {k: str(root / v) for k, v in cfg["paths"].items()}
    cfg["districts"]["boundary_file"] = str(raw / "boundaries" / "assam_districts.geojson")
    cfg["labels"]["input_dir"] = str(lab_dir)
    cfg["hazard"]["min_baseline_values"] = 100
    cfg["hazard"]["baseline_years"] = [1991, 2018]      # the mock has 1991+; the real data only dense from ~2015 (see config.yaml)
    cfg["hazard"]["min_normal_years"] = 10
    cfg["compare"]["bootstrap"] = 50
    cfg["terrain"]["downsample_factor"] = 1
    (root / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return root / "config.yaml"


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "mockproj")
    print("wrote", build(out))
