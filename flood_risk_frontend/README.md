# Assam Flood Risk: seasonal district-level assessment (frontend)

React + Vite + TypeScript dashboard for the `flood_risk_backend` (FastAPI). Leaflet map, Recharts charts, Vitest tests.

**Academic capstone prototype. Not an official warning service. It does not predict floods day by day.** It shows, per district:
seasonal **vulnerability**, **rain hazard** where rainfall observations exist, a rule-based **combined** category, and the **historical flood impact** by year.
Missing information is always shown as *Unknown* / *Not available*, never as zero or Low.

## Run it (macOS)

Requirements: Node 20.19+ (you have 20.20.2; check with `node -v`).

```bash
cd /Users/sachisingh/Documents/projects-workspace/flood_risk/flood_risk_frontend
npm install
cp .env.example .env        # only if your backend is not at http://127.0.0.1:8000
npm run dev                 # then open http://localhost:5173
```

Open **`http://localhost:5173`, not `http://127.0.0.1:5173`**: the backend's CORS list contains `localhost` only.

Backend (separate terminal, in `flood_risk_backend/` with its virtual environment active):

```bash
uvicorn app.main:app --reload
```

The backend address comes from `VITE_API_BASE_URL` in `.env` (restart `npm run dev` after changing it).

Checks:

```bash
npm run typecheck
npm test
npm run build
```

With an empty database the app still works: all districts appear grey (Unknown) and remain selectable. See `BACKEND_NOTES.md` for what the backend still needs.

## What each page shows

| Page | Content |
|---|---|
| Map (home) | Overview counts, map of every district the backend returns, legend, table of all districts, district panel |
| History | Flood impact by year (2019 to 2023, unknown years shown), plus the stored rainfall record with gaps for missing data |
| Rainfall scenario | Hypothetical rain total rated by the same rules. Clearly labelled, never mixed into the map |
| About & method | Methodology, data sources, limitations, model metadata from the backend |

## Structure

```
src/
  api/types.ts        types mirroring the backend schemas (+ the proposed flood-impact record)
  api/client.ts       the only module that calls fetch
  constants.ts        class colours/patterns, labels, documented data facts and year caveats
  lib/                assessment.ts (Unknown logic), geo.ts (Polygon/MultiPolygon validation), impact.ts (known / none reported / unknown),
                      summary.ts (overview counts), history.ts (null-safe series), dates.ts, scenario.ts
  hooks/              useAsync, useBoot, useAvailableDates
  components/         ChoroplethMap, DistrictPanel, FloodImpactSection, SummaryStrip, DistrictTable, Legend, charts, state views
  pages/              MapPage, HistoryPage, ScenarioPage, AboutPage
  test/               Vitest tests. fixtures.ts holds SYNTHETIC test data and is never imported by app code
```

## Endpoint mapping

| Endpoint | Used by |
|---|---|
| `GET /windows` | rainfall-window selector (may be empty; the map still works) |
| `GET /districts` | polygons, district list, terrain facts |
| `GET /assessments?window_days&date` | map colours, overview, table |
| `GET /districts/{id}/assessment` | district panel |
| `GET /districts/{id}/history` | rainfall record on the History page; also the source of available dates |
| `GET /districts/{id}/flood-impact` | **proposed**, yearly flood impact. Absent = shown as "not available from the backend" |
| `POST /assess` | hypothetical rainfall scenario |
| `GET /model/metadata` | About page |

## Data rules the UI follows

- Unknown (no assessment, null values, insufficient rainfall) is grey and hatched with a reason. It is never counted as Low in the overview.
- Hazard level `0` is a real Low; `null` is Unknown. A missing rainfall day is missing, not zero rain.
- Flood impact keeps three states apart: known impact, "no reported impact" (source-supported zero, dashed border) and unknown (grey).
- Elevation is labelled a digital surface model; population density is labelled unverified.
- `src/test/wording.test.ts` fails if UI source suggests a prediction or a look-ahead.

## Tests

`npm test` covers: geometry handling (Polygon, MultiPolygon, invalid geometry reported not dropped), flood-impact states, overview counts, null-safe history series,
Unknown rendering, a district without an assessment staying selectable, class colours, scenario validation, model-metadata handling and the wording rule.
All tests use synthetic data and a mocked API. None of them touches the real backend or the real boundary file.
