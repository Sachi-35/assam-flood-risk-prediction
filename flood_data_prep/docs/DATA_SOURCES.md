> **Rainfall source (current): CHIRPS v3.0, not v2.0 and not the NWDP gauges.** The NWDP station CSVs cover only 13 of 33 districts by
> coordinates and ~27 % of days, with no recorded zeros, so they cannot give valid seasonal totals. Primary rainfall is now
> **CHIRPS v3.0 final daily, 0.05 deg, mm/day** (Climate Hazards Center; archive `https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/<sat|rnl>/<year>/`, one
> GeoTIFF/COG per day; documented at chc.ucsb.edu/data/chirps3 and in the Earth Engine catalogue entries UCSB-CHC/CHIRPS/V3/DAILY_SAT and DAILY_RNL, doi:10.15780/G2JQ0P).
> `scripts/02_download_rainfall.py` reads only the Assam window of each day's file. `sat` = pentad totals split into days with IMERG Late V07;
> `rnl` = split with ERA5 (same pentad totals). You choose in `rainfall.chirps_v3.product`; nothing is switched silently and CHIRPS v2 / the old ERDDAP route is gone.
> **Not verified by me:** I could not reach the CHC server from my environment, so the exact daily file names are discovered from the directory listing at run time
> (or two conventional names are tried and logged), and the download was tested only against a local mock archive with the same layout.
> Daily dates are labels from the disaggregation, not station observation windows. NWDP stations are kept as supplementary data
> (`reports/rainfall_station_report.md`, `chirps_vs_stations.md`) and are never merged into the district series.
> The Tier-1 row 2 below is the original, now superseded, shopping list.

# What data to get, and where

> **Status update (your collection):** boundaries (33 districts), NetCDF rainfall, flood-impact labels (PDF-derived CSVs),
> the Copernicus GLO-30 DEM and (possibly) WorldPop are in hand. **Gauge levels, river lines, land cover and an upstream
> catchment were not obtained**; the pipeline and backend v2 no longer require them. The tables below are the original
> shopping list, kept for reference and for anything you add later. Current layout and formats: see `README.md`;
> label handling: `docs/LABELS.md`.

Everything the pipeline needs, in the order I'd collect it. **Tier 1 gives you a real (if modest) model.
Tiers 2–3 make it better.** Drop files in the folders shown; the scripts read them from there.

> Access details change. I could confirm the CHIRPS service, the IMD `imdlib` package and the ASDMA
> report URL pattern exist (links below). Everything else is from general knowledge: **open each portal
> and check before you plan your timeline around it.**

## Tier 1: you need these

| # | Data | Why | Where | Goes in | Effort |
|---|------|-----|-------|---------|--------|
| 1 | **District boundaries** (current Assam districts) | Defines "district" for all zonal stats and the map | GADM (gadm.org, level 2), DataMeet India maps (github.com/datameet/maps), or Survey of India / state GIS | `data/raw/boundaries/assam_districts.geojson` | Easy, but **check it contains your districts** (see caveat A) |
| 2 | **Daily rainfall grid** | The main driver | **CHIRPS v2.0** 0.05°, daily, via [NOAA ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/griddap/chirps20GlobalDailyP05.html) (scripted, no login). Alternative: **IMD gridded 0.25°** via [imdlib](https://pypi.org/project/imdlib/) | `data/raw/rainfall/*.nc` (script 02) | Easy (automated) |
| 3 | **Flood labels**: observed severity per district-day | The target. Without real labels there is no real model | **ASDMA daily flood reports** (district-wise affected population), PDFs at `https://www.asdma.gov.in/pdf/flood_report/<YEAR>/Daily_Flood_Report_DD.MM.YYYY.pdf` (pattern seen for 2024; **verify your years exist**) | `data/raw/labels/*.csv` (script 06a parses PDFs) | **Hardest.** PDF parsing is brittle |
| 4 | **Population per district** | Turns "people affected" into a comparable % across districts | WorldPop 100 m raster (worldpop.org) or Census-2011 projections | `data/raw/population/population.tif` | Easy |

## Tier 2: strongly recommended

| # | Data | Why | Where | Goes in |
|---|------|-----|-------|---------|
| 5 | **River gauge water level (+ discharge)** with danger / warning levels | Brahmaputra floods follow river stage, which integrates upstream rain. The best single predictor you can add | **CWC** flood-forecast stations and **India-WRIS**. There is no clean bulk API; expect portal downloads, CWC bulletins (PDF), or a data request to CWC / Brahmaputra Board | `data/raw/gauge/*.csv` + `stations.csv` |
| 6 | **Elevation (DEM)** | Low-lying floodplain share, slope | Copernicus DEM GLO-30 (via OpenTopography / AWS open data) or SRTM 30 m; mosaic to one GeoTIFF | `data/raw/terrain/dem.tif` |
| 7 | **Land cover** | Cropland / wetland / built-up share | ESA WorldCover 10 m (esa-worldcover.org) | `data/raw/landcover/landcover.tif` |
| 8 | **River centre-lines** | River density, distance to river | HydroRIVERS (hydrosheds.org) or OSM `waterway=river` | `data/raw/rivers/rivers.geojson` |
| 9 | **Upstream catchment polygon** | Rain over Arunachal / Tibet drives Assam floods days later; district-local rain alone misses it | HydroBASINS (hydrosheds.org) – select the basins draining into Assam | `config.rainfall.upstream.geometry_file` (default is a crude rectangle) |

## Tier 3: nice to have

| Data | Why | Notes |
|------|-----|-------|
| ERA5-Land soil moisture, evaporation (Copernicus CDS, free account) | Real wetness state instead of the rainfall-based antecedent index | Not wired in; add a script that outputs `zone_id,date,<variable>` and merge in step 07 |
| Dam / barrage release records | Releases (e.g. from Ranganadi in Arunachal) are a known trigger for floods in parts of Dhemaji / Lakhimpur | Usually not public. Mention as a limitation if you can't get it |
| Sentinel-1 flood extent (Google Earth Engine) | An *objective* alternative label: % of district inundated | Needs a GEE account. Revisit is ~6–12 days, so it's not truly daily. Set `labels.metric: inundated_pct` if you build it |
| Embankment-breach records | Many Assam floods are breaches, not overtopping, so the label is partly "unpredictable from weather" | Treat as a documented source of label noise |

## Minimum viable start

Boundaries + CHIRPS + ASDMA labels + WorldPop. That runs the whole pipeline with `--no-gauge`
and gives you the first real quality report. Add gauges as soon as you can get them.

## Caveats you should know before collecting

**A. District boundaries changed.** Census-2011 files have 27 Assam districts; today there are more
(for example Majuli became a district in 2016, and several were created in 2022–23). ASDMA reports use
*current* names. A boundary file that lacks one of your districts makes script 01 stop and print the names it did find.
Use a recent file, or add aliases in `config.yaml`.

**B. Absence of a report is not "no flood".** The label builder (see `docs/LABELS.md`) treats "report exists but district
not listed" as zero impact (`labels.absence_policy`), and "no report that day" as UNKNOWN (excluded from training).
State this assumption in your report.

**C. Five seasons is thin.** Five monsoons contain few *Severe* district-days. If the quality report shows
under ~30 rows in a class for any split, either get more years or merge classes (3 classes, or flood/no-flood)
as a sensitivity analysis.

**D. Labels are a proxy.** "People affected" measures impact, not hazard: it depends on embankments,
settlement patterns and reporting practice. Thresholds in `config.yaml` are placeholders to tune and justify.

**E. Coarse rainfall vs small districts.** IMD at 0.25° (~28 km) can give one grid cell for a small district such as Majuli.
The code then uses the nearest cell and warns you. CHIRPS at 0.05° is better there.
