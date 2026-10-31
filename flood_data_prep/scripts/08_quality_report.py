#!/usr/bin/env python
"""Step 8: data-quality + leakage-safe baseline report -> reports/data_quality.md

Read this BEFORE training. It tells you whether the table is usable: missing data, class balance per split,
how well a trivial 'tomorrow = today' rule already does (your model must beat it), and which features
actually correlate with the target.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("08_quality")


def macro_f1(y, p, classes=(0, 1, 2, 3)):
    f = []
    for c in classes:
        tp, fp, fn = ((y == c) & (p == c)).sum(), ((y != c) & (p == c)).sum(), ((y == c) & (p != c)).sum()
        if tp + fp + fn == 0:
            continue  # class absent in both -> ignore
        f.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f)) if f else float("nan")


def md(df, **kw):
    return df.to_markdown(**kw) if hasattr(df, "to_markdown") and _has_tabulate() else "```\n" + df.to_string() + "\n```"


def _has_tabulate():
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


def main_seasonal(cfg):
    from scipy.stats import spearmanr

    from floodprep.climatology import SEASON_FEATURES, STATIC_FEATURES
    df = pd.read_csv(cfg["paths"]["processed"] / "model_table_seasonal.csv")
    names = cfg["labels"]["class_names"]
    out = [f"# Data quality report (seasonal mode)\n\nRows (district-years): **{len(df)}** | districts: **{df.district_id.nunique()}** | "
           f"years: {sorted(df.year.unique())}\n"]
    warnings = []
    if len(df) < 100:
        warnings.append(f"Only {len(df)} labelled district-years: all metrics will have wide intervals.")
    feats = [c for c in SEASON_FEATURES + STATIC_FEATURES if c in df.columns]
    miss = (df[feats].isna().mean() * 100).round(1).sort_values(ascending=False)
    out.append("## 1. Missing values (% of rows)\n\n" + md(miss.rename("missing_%").to_frame()) + "\n")
    for c, v in miss.items():
        if v > 0:
            warnings.append(f"`{c}` is {v:.0f}% missing (models drop or cannot use it)")
    low_cov = df[df["season_obs_fraction"] < 0.9]
    if len(low_cov):
        warnings.append(f"{len(low_cov)} district-years have 80-90% rainfall coverage in their season (totals are scaled for the gap).")
    by_split = pd.crosstab(df["split"], df["risk_label"]).reindex(columns=names, fill_value=0)
    by_split = by_split.reindex([x for x in ["train", "val", "test"] if x in by_split.index])
    out.append("## 2. Class counts per split\n\n" + md(by_split) + "\n")
    out.append("## 3. Class counts per year\n\n" + md(pd.crosstab(df["year"], df["risk_label"]).reindex(columns=names, fill_value=0)) + "\n")
    out.append("## 4. Class counts per district\n\n" + md(pd.crosstab(df["district_name"], df["risk_label"]).reindex(columns=names, fill_value=0)) + "\n")
    # association of every feature with impact: pooled and within-year (year means removed)
    rows = []
    d2 = df.copy()
    for c in feats:
        if d2[c].nunique() < 2 or d2[c].isna().all():
            continue
        ok = d2[[c, "metric_value"]].dropna()
        rho = spearmanr(ok[c], ok["metric_value"])[0] if len(ok) > 4 else np.nan
        w = d2.groupby("year")[[c, "metric_value"]].transform(lambda x: x.rank(pct=True)).dropna()
        rho_w = spearmanr(w[c], w["metric_value"])[0] if len(w) > 4 else np.nan
        rows.append({"feature": c, "spearman_pooled": round(rho, 3), "spearman_within_year": round(rho_w, 3)})
    corr = pd.DataFrame(rows).set_index("feature").sort_values("spearman_pooled", key=np.abs, ascending=False)
    out.append("## 5. Association of each feature with the impact metric (Spearman)\n\n"
               "Pooled mixes between-year and between-district differences; within-year ranks features and impact inside each year "
               "(isolates district differences). With this few rows, |rho| below about 0.2 is indistinguishable from noise.\n\n" + md(corr) + "\n")
    hz = corr.loc[[i for i in corr.index if i.startswith(("hazard_", "season_max", "season_total"))]]
    if len(hz) and hz["spearman_pooled"].abs().max() < 0.15:
        warnings.append("No rainfall/hazard feature is clearly associated with annual impact. The rule-based hazard cannot be supported by this data.")
    out.append("## 6. Reminder\n\nThe window hazard (3/7/15/30 days) is a rule-based rainfall-extremity indicator. This table is the only evidence "
               "available that extreme rainfall coincides with larger reported impact in your labels; it does not validate any short-term forecast.\n")
    out.insert(1, "## Warnings\n\n" + ("\n".join(f"- {w}" for w in warnings) if warnings else "None.") + "\n")
    rpt = ensure_dir(cfg["paths"]["reports"]) / "data_quality.md"
    rpt.write_text("\n".join(out))
    log.info(f"Report -> {rpt}")
    for w in warnings:
        log.warning(w)


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    if cfg["project"].get("mode", "seasonal") == "seasonal":
        return main_seasonal(cfg)
    df = pd.read_csv(cfg["paths"]["processed"] / "district_day_features.csv", parse_dates=["date"])
    names = cfg["labels"]["class_names"]
    out = [f"# Data quality report\n\nRows: **{len(df):,}** | districts: **{df.district_id.nunique()}** | "
           f"{df.date.min().date()} -> {df.date.max().date()} | target lead: {cfg['project']['target_lead_days']} day(s)\n"]
    warnings = []
    # (rows only exist where the next-day label is known, so class counts below are over LABELLED district-days)

    # 1. Missingness
    feat_cols = [c for c in df.columns if c not in
                 ("district_id", "district_name", "date", "split", "risk_label", "risk_class", "target_class",
                  "metric_value", "label_observed", "label_quality")]
    miss = (df[feat_cols].isna().mean() * 100).round(2).sort_values(ascending=False)
    out.append("## 1. Missing values (% of rows)\n\n" + md(miss.rename("missing_%").to_frame()) + "\n")
    for c, v in miss.items():
        if v > 20 and not c.startswith(("water_", "level_", "discharge", "gauge_")):
            warnings.append(f"`{c}` is {v:.0f}% missing")
    if "has_gauge_station" not in df.columns:
        warnings.append("No river-gauge data: the model sees rainfall and terrain only (no river-stage information).")
    elif (df["has_gauge_station"] == 0).any():
        no_g = sorted(df.loc[df.has_gauge_station == 0, "district_id"].unique())
        warnings.append(f"No gauge station for {len(no_g)} district(s): {no_g}. Gauge features are NaN there.")

    # 2. Labels
    df["label"] = df["target_class"].map(dict(enumerate(names)))
    by_split = pd.crosstab(df["split"], df["label"]).reindex(columns=names, fill_value=0)
    by_split = by_split.reindex([s for s in ["train", "val", "test"] if s in by_split.index])
    out.append("## 2. Target class counts per split\n\n" + md(by_split) + "\n")
    by_dist = pd.crosstab(df["district_id"], df["label"]).reindex(columns=names, fill_value=0)
    out.append("## 3. Target class counts per district\n\n" + md(by_dist) + "\n")
    by_year = pd.crosstab(df["date"].dt.year, df["label"]).reindex(columns=names, fill_value=0)
    out.append("## 4. Target class counts per year\n\n" + md(by_year) + "\n")
    for split in by_split.index:
        for cls in names:
            if by_split.loc[split, cls] < 30:
                warnings.append(f"split `{split}` has only {by_split.loc[split, cls]} '{cls}' rows -> metrics for that class will be very noisy")
    obs = df["label_observed"].mean() * 100
    out.append(f"All rows above have a KNOWN next-day label (rows with unknown labels are removed, see reports/label_audit.md). "
               f"Share whose own-day label was a report: **{obs:.1f}%**.\n")

    # 5. Persistence baseline
    rows = []
    for split, g in df.groupby("split"):
        g = g.dropna(subset=["risk_class"])
        if g.empty:
            continue
        y, p = g["target_class"].to_numpy(), g["risk_class"].astype(int).to_numpy()
        rows.append({"split": split, "n": len(g), "persistence_acc": round(float((y == p).mean()), 3),
                     "persistence_macroF1": round(macro_f1(y, p), 3),
                     "always_Low_acc": round(float((y == 0).mean()), 3)})
    if not rows:
        rows = [{"split": "-", "n": 0, "persistence_acc": float("nan"), "persistence_macroF1": float("nan"), "always_Low_acc": float("nan")}]
    out.append("## 5. Trivial baselines (a real model must beat 'persistence')\n\n"
               "persistence = predict tomorrow's class = today's observed class. "
               "Note: this baseline uses the *observed* label, which a live system won't have in real time, "
               "so it is an upper-ish reference, not a fair competitor.\n\n" + md(pd.DataFrame(rows).set_index("split")) + "\n")

    # 6. Feature association
    num = df[feat_cols].select_dtypes("number")
    num = num.loc[:, num.nunique() > 1]
    corr = num.corrwith(df["target_class"], method="spearman").dropna().sort_values(key=np.abs, ascending=False)
    out.append("## 6. Spearman correlation of features with target class (top 20)\n\n"
               + md(corr.head(20).round(3).rename("rho").to_frame()) + "\n")
    if "rain_3d" in corr and abs(corr["rain_3d"]) < 0.05:
        warnings.append("rain_3d is almost uncorrelated with the target. Check the rainfall extraction and the label thresholds.")

    out.insert(1, "## Warnings\n\n" + ("\n".join(f"- {w}" for w in warnings) if warnings else "None.") + "\n")
    rpt = ensure_dir(cfg["paths"]["reports"]) / "data_quality.md"
    rpt.write_text("\n".join(out))
    log.info(f"Report -> {rpt}")
    for w in warnings:
        log.warning(w)


if __name__ == "__main__":
    main()
