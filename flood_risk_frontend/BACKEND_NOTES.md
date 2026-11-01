# Backend notes for the seasonal/annual frontend

The backend source was **not** supplied, so none of this was checked against real backend code.
The frontend still uses the API contract you reported; nothing in it was changed silently.

## 1. One backend addition is needed for the Historical Flood Impact view (proposed, optional)

The reported API has no way to return per-year flood labels (the existing `/history` returns daily rainfall windows, not annual labels).
The frontend calls this **proposed** endpoint and shows a clear "not available from the backend" state (all years grey = unknown) when it returns 404/405/501:

```
GET /districts/{id}/flood-impact   ->   200: list of records, one per district-year that has a processed label row
```

Each record (only `year` is required; every other field may be null or absent):

```json
{
  "year": 2021,
  "status": "reported",              // "reported" | "no_reported_impact" | "unknown"
  "impact_class": "moderate",        // "low" | "moderate" | "high" | "severe" | null  (only with status "reported")
  "affected_population": 12000,      // absolute count from the source, or null
  "reporting_period": "1 Jun to 30 Sep",   // free text, or null
  "caveats": ["Fourth-wave snapshot"]      // list of strings, or null/absent
}
```

Rules the frontend relies on:

- Return `"no_reported_impact"` **only** where the source supports an actual zero. Never use it for missing labels.
- For the 66 unknown district-years, either omit the year or return `"status": "unknown"`. The frontend shows both as grey "Unknown".
- Never send `0` for a missing `affected_population`; send `null`.
- Records for Bajali and Tamulpur belong to Barpeta and Baksa (as mapped during data preparation).

Sketch of the route (adapt to your SQLAlchemy models and table names, which I could not see; **untested**):

```python
# app/routers/districts.py  (sketch)
from typing import Optional
from pydantic import BaseModel

class FloodImpactOut(BaseModel):
    year: int
    status: Optional[str] = None
    impact_class: Optional[str] = None
    affected_population: Optional[float] = None
    reporting_period: Optional[str] = None
    caveats: Optional[list[str]] = None

@router.get("/districts/{district_id}/flood-impact", response_model=list[FloodImpactOut])
def flood_impact(district_id: int, db: Session = Depends(get_db)):
    # Read your processed district-year label table here. Return [] if the district has none.
    ...
```

## 2. Things the frontend assumes about existing endpoints

- `GET /districts` returns **all 33** districts with Polygon or MultiPolygon geometry in EPSG:4326 (lon/lat), including terrain fields (`null` where unknown). The overview warns if the count is not 33 and lists any geometry it cannot draw.
- `GET /assessments` returns 404 or an empty list when nothing is stored. The frontend then shows every district as Unknown (grey).
- `hazard.level`, `hazard.window_rain_mm`, `hazard.obs_fraction`, `vulnerability`, `combined.risk_class` may be `null`. `null` is always shown as Unknown / Not available, never 0 or Low.
- `window_days` and `as_of_date` are shown only as "rainfall window: last N days ending DATE". The frontend does not describe them as a prediction. If the backend's rainfall-window logic is no longer wanted at all, the cleanest change is to have `/windows` return an empty list; the map then works without any window.
- `POST /assess` is kept as a hypothetical rainfall scenario. Its `window_end_date` only selects the time of year for the baseline comparison.

## 3. What still blocks a fully populated demo (not frontend problems)

1. **Boundaries in the database.** The 33-polygon GeoJSON must be loaded by `seed_db.py` (or equivalent). Without it the map is empty.
2. **Assessments.** `train_model.py`, `seed_db.py` and `compute_assessments.py` need `season_features.csv`, `normal_season_features.csv` and `hazard_config.json`. These were not found in `flood_data_prep/`. Until they exist, vulnerability and combined values cannot be computed and the map shows all 33 districts as Unknown. That is honest but not exciting; do not create placeholder files.
3. **Rain hazard** can exist for at most the 13 districts with rainfall stations. The other 20 will always show Unknown for hazard and combined.
4. **Yearly flood labels** need the endpoint in section 1.
5. **Population density** is shown as unverified until the raster's year and units are confirmed.
