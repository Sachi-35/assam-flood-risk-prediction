#!/usr/bin/env python
"""Step 6: build the flood-severity labels and AUDIT the label data.

project.mode = seasonal (your data): ONE label per district and year from the annual/seasonal impact totals.
                 Output data/interim/labels_annual.csv, label_thresholds.json, reports/label_audit.md
project.mode = daily: the original district-day builder (needs real daily reports), described below.

Input : labels.input_dir (default data/processed/labels/annual)/*.csv
            district, date, affected_population  [+ period_start, period_end, label_granularity, source_pdf, source_section]
        data/interim/districts.csv, data/interim/static_features.csv (pop_total, if a population raster was provided)
Output: data/interim/labels_daily.csv      one row per district-day; risk_class is EMPTY where nothing is known
        data/interim/labels_seasonal.csv   annual/seasonal totals, kept separate (never spread over days)
        data/interim/label_thresholds.json class boundaries actually used (derived from TRAINING dates only)
        reports/label_audit.md             what the label data contains, what was assumed, whether it is trainable
Read reports/label_audit.md before training anything.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config
from floodprep import annual_labels as AL
from floodprep.labels import assign_granularity, build_daily_labels, load_label_csvs
import json

log = get_logger("06_labels")


def md(df):
    try:
        return df.to_markdown()
    except ImportError:
        return "```\n" + df.to_string() + "\n```"


def main_seasonal(cfg):
    interim, reports = ensure_dir(cfg["paths"]["interim"]), ensure_dir(cfg["paths"]["reports"])
    lcfg, pc, sp, acfg = cfg["labels"], cfg["project"], cfg["splits"], cfg["labels"]["annual"]
    districts = pd.read_csv(interim / "districts.csv")
    spath = interim / "static_features.csv"
    if spath.exists():
        st = pd.read_csv(spath)
        if "pop_total" in st and st["pop_total"].notna().all():
            districts = districts.merge(st[["district_id", "pop_total"]], on="district_id", how="left")
    if "pop_total" not in districts.columns:
        log.warning("No population totals: labels use ABSOLUTE affected people (favours large districts).")

    folder = lcfg["input_dir"]
    auth, others, excluded = AL.discover_files(folder, lcfg.get("files"), lcfg.get("exclude_patterns", []))
    log.info(f"Authoritative label file(s): {[p.name for p in auth]} | other candidates (compare only): {[p.name for p in others]} | "
             f"excluded: {[p.name for p in excluded]}")
    frames, infos = [], []
    for p in auth:
        r, i = AL.load_annual_file(p, acfg["granularities"], int(acfg.get("min_period_days", 60)))
        frames.append(r); infos.append(i)
    rows = pd.concat(frames, ignore_index=True)
    years = list(range(pd.Timestamp(pc["start_date"]).year, pd.Timestamp(pc["end_date"]).year + 1))
    out_of_range = sorted(set(rows["year"]) - set(years))
    lab, info = AL.build_annual_labels(rows, districts, lcfg, cfg["districts"].get("aliases"), cfg["districts"].get("merge_into_parent"), years)
    lab, metric = AL.add_metric(lab, districts, lcfg.get("metric", "auto"))
    info["metric_used"] = metric

    train_end_year = pd.Timestamp(sp["train_end"]).year
    val_end_year = pd.Timestamp(sp["val_end"]).year
    lab["split"] = lab["year"].map(lambda y: "train" if y <= train_end_year else ("val" if y <= val_end_year else "test"))
    known = lab["metric_value"].notna()
    thr = AL.derive_thresholds(lab.loc[known & (lab["split"] == "train"), "metric_value"], acfg["quantiles"])
    lab["risk_class"] = AL.classify(lab["metric_value"], thr)
    names = lcfg["class_names"]
    lab["risk_label"] = lab["risk_class"].map(lambda c: names[int(c)] if pd.notna(c) else None)
    lab.to_csv(interim / "labels_annual.csv", index=False)
    (interim / "label_thresholds.json").write_text(json.dumps({"mode": "seasonal", "metric": metric, "thresholds": thr,
                                                              "quantiles": acfg["quantiles"], "train_years": f"<= {train_end_year}"}, indent=2))

    # ---------------------------------------------------------------- comparison with other versions
    cmp_lines = []
    for p in others:
        try:
            r2, i2 = AL.load_annual_file(p, acfg["granularities"], int(acfg.get("min_period_days", 60)))
            l2, _ = AL.build_annual_labels(r2, districts, lcfg, cfg["districts"].get("aliases"), cfg["districts"].get("merge_into_parent"), years)
            m = lab[["district_id", "year", "affected_population"]].merge(l2[["district_id", "year", "affected_population"]],
                                                                             on=["district_id", "year"], how="outer", suffixes=("_auth", "_other"))
            both = m.dropna(subset=["affected_population_auth", "affected_population_other"])
            diff = both[(both["affected_population_auth"] - both["affected_population_other"]).abs() > 0.5]
            only_auth = int((m["affected_population_auth"].notna() & m["affected_population_other"].isna()).sum())
            only_other = int((m["affected_population_auth"].isna() & m["affected_population_other"].notna()).sum())
            cmp_lines.append(f"- **{p.name}** ({i2['rows']} rows): district-years in both {len(both)}, with DIFFERENT values {len(diff)}"
                             f"{' e.g. ' + str(diff.head(3).values.tolist()) if len(diff) else ''}; "
                             f"only in the authoritative file {only_auth}; only in this file {only_other}")
        except Exception as e:  # a candidate with other columns is only reported, never an error
            cmp_lines.append(f"- **{p.name}**: could not be compared ({type(e).__name__}: {e})")

    # ---------------------------------------------------------------- audit report
    cov = lab.assign(rep=lab["metric_value"].notna().astype(int)).pivot(index="district_id", columns="year", values="rep").fillna(0).astype(int)
    per_year = lab.groupby("year").agg(districts_with_value=("metric_value", "count"),
                                       median_affected=("affected_population", "median"), max_affected=("affected_population", "max"))
    spans = rows.groupby("year").agg(period_start_min=("period_start", "min"), period_end_max=("period_end", "max")) if "period_start" in rows else None
    cls = pd.crosstab(lab["split"], lab["risk_label"]).reindex(columns=names, fill_value=0)
    cls = cls.reindex([x for x in ["train", "val", "test"] if x in cls.index])
    cls_y = pd.crosstab(lab["year"], lab["risk_label"]).reindex(columns=names, fill_value=0)
    flags = rows["quality_flag"].value_counts().to_dict() if "quality_flag" in rows else {}
    warnings = []
    if out_of_range:
        warnings.append(f"Years in the label file outside project.start_date..end_date and ignored: {out_of_range}")
    if info["unmatched"]:
        warnings.append(f"District names with NO match in the boundary file (rows dropped): {info['unmatched']}")
    if info["merged"]:
        warnings.append(f"Districts added to a parent polygon: {info['merged']}  (check parents; totals were SUMMED)")
    if info["duplicate_keys"]:
        warnings.append(f"{info['duplicate_keys']} district-years have several rows; combined by `{acfg['duplicate_policy']}`. Examples [district_id, name, year, n]: "
                        f"{info['duplicate_examples']}. If these are separate flood waves rather than repeated tables, `sum` may be right: check source_section.")
    zero = lab[(lab["label_status"] == "reported") & (lab["affected_population"] == 0)]
    if len(zero):
        warnings.append(f"{len(zero)} district-years are REPORTED with affected_population = 0 (verify against the source): "
                        f"{zero[['district_id', 'year']].head(10).values.tolist()}")
    info["name_map"].to_csv(reports / "label_name_map.csv", index=False)
    info["duplicate_detail"].to_csv(reports / "label_duplicates.csv", index=False)
    changed = info["name_map"][info["name_map"]["name_in_file"].str.lower() != info["name_map"]["boundary_district"].str.lower()]
    if len(changed):
        warnings.append("Names in the label file that were mapped to a DIFFERENT boundary name (aliases / merges; see reports/label_name_map.csv, "
                        f"verify each): {changed[['name_in_file', 'boundary_district']].values.tolist()}")
    if any(i["invalid_rows"] for i in infos):
        warnings.append(f"Rows with an unparseable year or value (dropped): {[(i['file'], i['invalid_rows']) for i in infos if i['invalid_rows']]}")
    for i in infos:
        warnings.append(f"{i['file']}: rows kept by label_granularity {i['kept_by']['label_granularity']}, by period length only "
                        f"{i['kept_by']['period_length_only']}; granularity values in the file: {i['granularity_values']}")
    if any(i["non_annual_rows"] for i in infos):
        warnings.append(f"Rows ignored because label_granularity is not annual/seasonal: {[(i['file'], i['non_annual_values']) for i in infos if i['non_annual_rows']]}")
    if not all(i["has_period"] for i in infos):
        warnings.append("No period_start/period_end in the label file: rainfall will be aggregated over season.fixed, which is an ASSUMPTION.")
    n_known = int(known.sum())
    if n_known < 100:
        warnings.append(f"Only {n_known} labelled district-years. Expect wide uncertainty; results are exploratory.")
    if info["absent_district_years"] > 0.2 * len(lab):
        warnings.append(f"{info['absent_district_years']} of {len(lab)} district-years have no record. Policy: `{acfg['absent_district_policy']}`. "
                        "'unknown' drops them (positive-biased sample); 'zero' assumes 'not listed = no reported impact'. Decide and state it; "
                        "10_compare_models can be rerun under both.")
    for sn in cls.index:
        for cn in names:
            if cls.loc[sn, cn] < 5:
                warnings.append(f"split `{sn}` has only {int(cls.loc[sn, cn])} '{cn}' district-years")
    md = lambda d: d.to_markdown() if hasattr(d, "to_markdown") else d.to_string()
    try:
        import tabulate  # noqa: F401
    except ImportError:
        md = lambda d: "```\n" + d.to_string() + "\n```"
    txt = ["# Label audit (seasonal mode)\n",
           f"Metric: **{metric}** | thresholds ({lcfg.get('annual', {}).get('quantiles')} quantiles of TRAINING years <= {train_end_year}): "
           f"{[round(t, 4) for t in thr]} | classes {names} | absent districts: **{acfg['absent_district_policy']}**\n",
           "## Warnings\n\n" + ("\n".join(f"- {w}" for w in warnings) if warnings else "None.") + "\n",
           f"## Files\n\nAuthoritative: {[p.name for p in auth]}. Excluded by pattern: {[p.name for p in excluded]}. Rows per file: "
           f"{[(i['file'], i['rows']) for i in infos]}. Rows dropped for a missing year/value: {sum(i['bad_year_or_value'] for i in infos)}.\n",
           "### Other versions compared with the authoritative file\n\n" + ("\n".join(cmp_lines) if cmp_lines else "None."),
           "\n## Quality flags in the authoritative file\n\n" + str(flags or "none / no quality_flag column") + "\n",
           "## Labelled values per year\n\n" + md(per_year) + "\n"]
    if spans is not None:
        txt.append("## Reporting periods per year (period_start / period_end as given)\n\n" + md(spans) +
                   "\n\nThe rainfall features use each row's own period. If the periods differ a lot between years, features are not "
                   "comparable across years; look here before trusting any comparison.\n")
    txt += ["## District x year coverage (1 = value present)\n\n" + md(cov.rename(index=dict(zip(districts.district_id, districts.district_name)))) + "\n",
            "## Class counts per split (district-years)\n\n" + md(cls) + "\n", "## Class counts per year\n\n" + md(cls_y) + "\n",
            "## How to read this\n\n* Labels are ANNUAL: one value per district-year; they are never spread over days.\n"
            "* Classes are relative severity bands of this dataset, not official categories.\n"
            "* Affected population measures impact, not water level.\n"]
    (reports / "label_audit.md").write_text("\n".join(txt))
    for w in warnings:
        log.warning(w)
    log.info("Class counts per split:\n" + cls.to_string())
    log.info(f"Audit -> {reports/'label_audit.md'}; labels -> {interim/'labels_annual.csv'}")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    if cfg["project"].get("mode", "seasonal") == "seasonal":
        return main_seasonal(cfg)
    interim = ensure_dir(cfg["paths"]["interim"])
    reports = ensure_dir(cfg["paths"]["reports"])
    lcfg, pc, sp = cfg["labels"], cfg["project"], cfg["splits"]
    districts = pd.read_csv(interim / "districts.csv")

    spath = interim / "static_features.csv"
    if spath.exists():
        st = pd.read_csv(spath)
        if "pop_total" in st and st["pop_total"].notna().all():
            districts = districts.merge(st[["district_id", "pop_total"]], on="district_id", how="left")
    if "pop_total" not in districts.columns:
        log.warning("No population totals -> labels use ABSOLUTE affected_population (metric 'auto'). "
                    "Absolute counts favour big districts; a % of population is fairer across districts.")

    folder = lcfg["input_dir"]
    if not Path(folder).exists():
        sys.exit(f"Label folder not found: {folder}  (labels.input_dir in config.yaml)")
    raw = load_label_csvs(folder)
    log.info(f"Read {raw.attrs['rows_read']} rows from {raw['source_file'].nunique()} file(s): {sorted(raw['source_file'].unique())}")

    labels, seasonal, info = build_daily_labels(
        raw, districts, lcfg, cfg["districts"].get("aliases"), pc["start_date"], pc["end_date"], sp["train_end"],
        merge_into_parent=cfg["districts"].get("merge_into_parent"), thresholds_path=interim / "label_thresholds.json")

    labels.to_csv(interim / "labels_daily.csv", index=False)
    seasonal.drop(columns=[c for c in ("kind",) if c in seasonal.columns]).to_csv(interim / "labels_seasonal.csv", index=False)

    # ---------------------------------------------------------------- audit report
    names = lcfg["class_names"]
    rg = assign_granularity(raw, lcfg)
    rg["year"] = rg["date"].dt.year
    gran = pd.crosstab(rg["year"], rg["kind"])
    ids2name = dict(zip(districts["district_id"], districts["district_name"]))

    L = labels.copy()
    L["split"] = np.where(L["date"] <= pd.Timestamp(sp["train_end"]), "train",
                          np.where(L["date"] <= pd.Timestamp(sp["val_end"]), "val", "test"))
    L["label"] = L["risk_label"]
    known = L[L["risk_class"].notna()]
    dist_split = pd.crosstab(known["split"], known["label"]).reindex(columns=names, fill_value=0)
    dist_split = dist_split.reindex([s for s in ["train", "val", "test"] if s in dist_split.index])
    L["year"] = L["date"].dt.year
    per_year = pd.DataFrame({
        "district_days_labelled": known.groupby(known["date"].dt.year).size(),
        "positive_(>=Moderate)": known[known["risk_class"] >= 1].groupby(known["date"].dt.year).size(),
        "dates_with_a_report": known.groupby(known["date"].dt.year)["date"].nunique()}).fillna(0).astype(int)

    warnings = []
    if info["unmatched"]:
        warnings.append(f"District names in the label files with NO match in the boundary file (rows dropped, not guessed): "
                        f"{info['unmatched']}. Add them under districts.aliases or districts.merge_into_parent.")
    if info["merged"]:
        warnings.append(f"Districts folded into a parent polygon (their numbers were ADDED to the parent): {info['merged']}.")
    unk = info["kind_counts"].get("unknown", 0)
    if unk:
        vals = sorted(rg.loc[rg["kind"] == "unknown", "label_granularity"].dropna().unique())
        warnings.append(f"{unk} rows have an unrecognised label_granularity {vals}; they were treated as seasonal (not used as daily labels). "
                        "Add the value to labels.granularity_map.")
    n_daily = info["kind_counts"].get("daily", 0)
    if n_daily == 0:
        warnings.append("NO row qualifies as a DAILY label. A daily next-day classifier cannot be trained from this data. "
                        "Options: (a) set labels.period_policy: window if your 'period' rows are real flood events of <= max_period_days; "
                        "(b) model a coarser target (district-season severity) from labels_seasonal.csv; (c) obtain daily reports.")
    train_pos = int(((known["split"] == "train") & (known["risk_class"] >= 1)).sum())
    if train_pos < lcfg.get("min_positive_train_rows", 100):
        warnings.append(f"Only {train_pos} TRAIN district-days are >= Moderate (< {lcfg.get('min_positive_train_rows', 100)}). "
                        "Expect an unstable model; consider merging classes (flood / no flood) as the main result.")
    for sname in dist_split.index:
        for cname in names:
            if dist_split.loc[sname, cname] < 30:
                warnings.append(f"split `{sname}`: only {dist_split.loc[sname, cname]} '{cname}' labelled district-days.")
    if (cfg["labels"]["absence_policy"] == "zero"):
        warnings.append("absence_policy=zero: dry-season days are labelled Low -> inflated accuracy.")

    txt = [f"# Label audit\n",
           f"Metric used: **{info['metric_used']}** | threshold method: **{info['threshold_method']}** -> thresholds "
           f"{[round(float(t), 4) for t in info['thresholds']]} (classes: {names}) | absence policy: **{lcfg['absence_policy']}** | "
           f"period policy: **{lcfg['period_policy']}**\n",
           "## Warnings\n\n" + ("\n".join(f"- {w}" for w in warnings) if warnings else "None.") + "\n",
           f"## Input\n\nFiles: {sorted(raw['source_file'].unique())}. Rows read: {raw.attrs['rows_read']}; "
           f"rows with an unparseable date/district dropped: {raw.attrs['rows_dropped_bad_date']}; "
           f"rows kept after district matching: {info['rows_after_matching']}.\n",
           "## Rows by year and granularity\n\n" + md(gran) + "\n",
           f"Daily report dates in the period: {info['daily_report_dates']}. Period rows: {info['period_rows']} "
           f"(used as labels: {info['period_rows_used']}). Seasonal/unknown rows kept separately: {len(seasonal)}.\n",
           "## Labelled district-days per year\n\n" + md(per_year) + "\n",
           "## Class counts per split (labelled district-days only)\n\n" + md(dist_split) + "\n"]
    if len(known):
        top = (L[L["risk_class"] >= 1].groupby("district_id").size().sort_values(ascending=False).head(10)
               .rename(lambda i: ids2name.get(i, i)).rename("positive_days"))
        txt.append("## Districts with most positive days\n\n" + md(top.to_frame()) + "\n")
    txt.append("## How to read this\n\n"
               "* `risk_class` is EMPTY for any district-day the sources say nothing about; those rows never reach the model.\n"
               "* Classes are relative severity bands of your own data (see config comments), derived on training dates only.\n"
               "* Affected population measures impact, not water level; embankment breaches and reporting practice add noise.\n")
    (reports / "label_audit.md").write_text("\n".join(txt))

    log.info("Class distribution (labelled district-days, all splits):\n"
             + known["risk_label"].value_counts().reindex(names).fillna(0).astype(int).to_string())
    for w in warnings:
        log.warning(w)
    log.info(f"Audit -> {reports/'label_audit.md'} ; labels -> {interim/'labels_daily.csv'}")


if __name__ == "__main__":
    main()
