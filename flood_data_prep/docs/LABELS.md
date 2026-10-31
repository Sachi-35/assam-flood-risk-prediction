> **Seasonal mode (default):** labels are one row per district-year (`labels_annual.csv`); daily rows in the file are ignored, annual
> totals are never spread over days, absent district = *unknown* (config `labels.annual.absent_district_policy`), duplicates use `max`
> (config), classes come from training-year quantiles. See `reports/label_audit.md`. The text below describes the **daily mode**.

# How the labels are built (and why)

**Source:** Assam flood memoranda → `district, date, affected_population` (+ `period_start, period_end, label_granularity, source_pdf, source_section`).

**The problem:** affected population is a *stock of impact*, not a daily hazard measurement, and your files mix granularities. Copying an annual total onto every day would fabricate daily labels and make a model look good by learning the calendar.

## Rules

| Situation | What happens |
|---|---|
| `label_granularity` ∈ daily list, no multi-day period | a **daily label** for that district and date |
| `period` rows (a total over `period_start..period_end`) | **not used** by default. `period_policy: window` gives every day of periods ≤ `max_period_days` that period's class, flagged `label_quality=period` |
| `seasonal` / annual / unrecognised granularity | written to `labels_seasonal.csv`, **never spread over days** |
| a "daily" row that carries a multi-day period | reclassified as period/seasonal |
| no `label_granularity` column | `default_granularity` (daily) is assumed, and the audit says so |
| district missing from a date that **has** a daily report | impact 0 (`absence_policy: zero_on_report_dates`) – an assumption, state it |
| district-day with **no** report | **unknown**: empty class, row excluded from training (dry-season days are *not* turned into Low) |
| name not in the boundary file | listed in `label_audit.md`, rows dropped; `Bajali` is added to its parent Barpeta; add others under `districts.aliases` / `merge_into_parent` |
| several rows for the same district-date | max (duplicates), but **sum** across a child district merged into its parent |

## Class boundaries

`threshold_method: train_quantile` (default): Low = impact ≤ `min_impact`; among *positive* impacts on **training dates only**, Moderate < p50 ≤ High < p90 ≤ Severe. Saved to `data/interim/label_thresholds.json` and applied unchanged to validation and test.

These are **relative severity bands of your dataset**, not official categories ("Severe" = the worst ~10 % of impacted district-days). That is defensible for a capstone if you say so; it is not a claim about absolute flood severity. `fixed` thresholds are available if you can cite official ones.

Metric: `% of district population affected` when a population raster exists, else absolute people (absolute counts favour big districts). `metric: auto` picks.

## When the data cannot support a daily model

`reports/label_audit.md` warns when there are no daily rows, fewer than `min_positive_train_rows` positive training days, or < 30 rows of a class in a split. Then use one of:

1. merge to **flood / no flood** (or 3 classes) as the headline result,
2. a **district-season** target from `labels_seasonal.csv` (one row per district-year; predict from season rainfall/terrain) – honest but coarse,
3. obtain daily reports (e.g. ASDMA daily flood reports; `06a_fetch_asdma_reports.py` is an optional, untested parser).

## What the label cannot tell you

Embankment breaches, reporting practice and the time lag between a report and the flood all add noise. Rain on day *t* predicting the *reported* class at *t+1* is a weak, noisy relationship; the persistence baseline in `data_quality.md` shows how much of the signal is just "floods last several days".
