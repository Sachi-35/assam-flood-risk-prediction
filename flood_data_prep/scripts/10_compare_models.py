#!/usr/bin/env python
"""Step 10: honest offline comparison of baselines, Logistic Regression, Random Forest and XGBoost (seasonal mode).

Data   : data/processed/model_table_seasonal.csv  (one row per labelled district-year)
Schemes: * leave-one-YEAR-out : train on the other years, test on the held-out year (temporal generalisation)
         * leave-DISTRICT-out : 5 folds, all years of a district stay together (spatial generalisation; rows of one district are not independent)
Class boundaries are recomputed from the TRAINING rows of every fold (the test fold never influences how classes are defined).
Feature sets: static_only (terrain + population) | rain_only (seasonal rainfall) | static_plus_rain.
Baselines: majority class | district's mean impact in the other years | previous year's class.
Output : reports/model_comparison.md, reports/model_comparison.json, reports/oof_predictions.csv
Caveat : ~100-165 rows. Differences smaller than the bootstrap intervals are not evidence of a better model.
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import cohen_kappa_score, f1_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from floodprep import annual_labels as AL
from floodprep.climatology import SEASON_FEATURES, STATIC_FEATURES
from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("10_compare")
K = 4


def make_models(seed):
    ms = {
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced", max_iter=5000)),
        "random_forest": lambda: RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=3, class_weight="balanced_subsample",
                                                        random_state=seed, n_jobs=-1),
    }
    try:
        from xgboost import XGBClassifier
        ms["xgboost"] = "xgb"
    except ImportError:
        log.warning("xgboost not installed: skipped (pip install xgboost)")
    return ms


def fit_predict_proba(name, factory, Xtr, ytr, Xte, seed):
    """Probabilities for all K classes (0 for classes absent from training)."""
    classes = np.unique(ytr)
    if len(classes) < 2:
        p = np.zeros((len(Xte), K)); p[:, classes[0]] = 1.0
        return p
    if factory == "xgb":
        from xgboost import XGBClassifier
        enc = {c: i for i, c in enumerate(classes)}
        y = np.array([enc[c] for c in ytr])
        w = pd.Series(y).map(len(y) / (len(classes) * pd.Series(y).value_counts())).to_numpy()
        m = XGBClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=1,
                          random_state=seed, n_jobs=1, verbosity=0)
        m.fit(Xtr, y, sample_weight=w)
        pr, cls = m.predict_proba(Xte), classes
    else:
        m = factory()
        m.fit(Xtr, ytr)
        pr, cls = m.predict_proba(Xte), m.classes_
    p = np.zeros((len(Xte), K))
    for j, c in enumerate(cls):
        p[:, int(c)] = pr[:, j]
    return p


def onehot(pred):
    p = np.zeros((len(pred), K)); p[np.arange(len(pred)), pred.astype(int)] = 1.0
    return p


def metrics(y, pred, proba, metric_value):
    exp = proba @ np.arange(K)
    present = [c for c in range(K) if (y == c).any()]
    out = {"n": int(len(y)), "accuracy": float((y == pred).mean()), "within_1_class": float((np.abs(y - pred) <= 1).mean()),
           "ordinal_mae": float(np.abs(y - pred).mean()),
           "macro_f1": float(f1_score(y, pred, labels=present, average="macro", zero_division=0))}
    out["qwk"] = float(cohen_kappa_score(y, pred, weights="quadratic", labels=list(range(K)))) if len(set(y)) > 1 and len(set(pred)) > 1 else float("nan")
    out["spearman"] = float(spearmanr(exp, metric_value)[0]) if np.std(exp) > 0 else float("nan")
    hi = (y >= 2).astype(int)
    out["auc_high_or_severe"] = float(roc_auc_score(hi, exp)) if 0 < hi.sum() < len(hi) else float("nan")
    return out


def bootstrap(y, pred, proba, mv, n, seed):
    rng = np.random.default_rng(seed)
    res = {k: [] for k in ("macro_f1", "qwk", "spearman")}
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        m = metrics(y[i], pred[i], proba[i], mv[i])
        for k in res:
            res[k].append(m[k])
    return {k: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))] if np.isfinite(v).any() else [np.nan, np.nan] for k, v in res.items()}


def run_scheme(df, scheme, feature_sets, models, quantiles, seed):
    if scheme == "leave_one_year_out":
        folds = [(df.index[df.year != y], df.index[df.year == y]) for y in sorted(df.year.unique())]
    else:
        n_splits = min(5, df.district_id.nunique())
        folds = [(df.index[tr], df.index[te]) for tr, te in GroupKFold(n_splits=n_splits).split(df, groups=df["district_id"])]
    rows = []
    for fi, (tr, te) in enumerate(folds):
        d_tr, d_te = df.loc[tr], df.loc[te]
        try:
            thr = AL.derive_thresholds(d_tr["metric_value"], quantiles)
        except ValueError as e:
            log.warning(f"{scheme} fold {fi}: skipped ({e})")
            continue
        ytr = AL.classify(d_tr["metric_value"], thr).astype(int).to_numpy()
        yte = AL.classify(d_te["metric_value"], thr).astype(int).to_numpy()
        base = {"fold": fi, "scheme": scheme}
        maj = int(pd.Series(ytr).mode().iloc[0])
        preds = {("baseline", "majority_class"): onehot(np.full(len(d_te), maj))}
        if scheme == "leave_one_year_out":
            mean_m = d_tr.groupby("district_id")["metric_value"].mean()
            dm = d_te["district_id"].map(mean_m)
            cls = AL.classify(dm, thr).fillna(maj).astype(int).to_numpy()
            preds[("baseline", "district_mean_other_years")] = onehot(cls)
            prev = d_tr.set_index(["district_id", "year"])["metric_value"]
            pv = pd.Series([prev.get((a, b - 1), np.nan) for a, b in zip(d_te.district_id, d_te.year)], index=d_te.index)
            preds[("baseline", "previous_year_class")] = onehot(AL.classify(pv, thr).fillna(maj).astype(int).to_numpy())
        for fs_name, cols in feature_sets.items():
            cols = [c for c in cols if c in df.columns and df[c].notna().all()]
            if not cols:
                continue
            for mname, factory in models.items():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    preds[(f"{fs_name}", mname)] = fit_predict_proba(mname, factory, d_tr[cols].to_numpy(), ytr, d_te[cols].to_numpy(), seed)
        for (fs, mn), proba in preds.items():
            for k, idx in enumerate(d_te.index):
                rows.append({**base, "index": idx, "feature_set": fs, "model": mn, "district_id": d_te.at[idx, "district_id"],
                             "year": int(d_te.at[idx, "year"]), "metric_value": d_te.at[idx, "metric_value"], "y_true": int(yte[k]),
                             "y_pred": int(np.argmax(proba[k])), **{f"p{c}": float(proba[k, c]) for c in range(K)}})
    return pd.DataFrame(rows)


def summarise(oof, nboot, seed):
    out = []
    for (scheme, fs, mn), g in oof.groupby(["scheme", "feature_set", "model"]):
        y, pred = g["y_true"].to_numpy(), g["y_pred"].to_numpy()
        proba = g[[f"p{c}" for c in range(K)]].to_numpy()
        m = metrics(y, pred, proba, g["metric_value"].to_numpy())
        ci = bootstrap(y, pred, proba, g["metric_value"].to_numpy(), nboot, seed)
        out.append({"scheme": scheme, "feature_set": fs, "model": mn, **m,
                    **{f"{k}_lo": v[0] for k, v in ci.items()}, **{f"{k}_hi": v[1] for k, v in ci.items()}})
    return pd.DataFrame(out)


def md(df):
    try:
        return df.to_markdown(index=False, floatfmt=".3f")
    except ImportError:
        return "```\n" + df.round(3).to_string(index=False) + "\n```"


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    if cfg["project"].get("mode", "seasonal") != "seasonal":
        return log.info("project.mode is not 'seasonal': nothing to compare (this step needs annual labels).")
    seed, nboot = cfg["compare"]["random_state"], cfg["compare"]["bootstrap"]
    df = pd.read_csv(cfg["paths"]["processed"] / "model_table_seasonal.csv").reset_index(drop=True)
    q = cfg["labels"]["annual"]["quantiles"]
    static = [c for c in STATIC_FEATURES if c in df.columns and df[c].notna().all()]
    dropped = [c for c in STATIC_FEATURES if c in df.columns and c not in static]
    feature_sets = {"static_only": static, "rain_only": SEASON_FEATURES, "static_plus_rain": static + SEASON_FEATURES}
    models = make_models(seed)
    log.info(f"{len(df)} district-years, {df.district_id.nunique()} districts, years {sorted(int(y) for y in df.year.unique())}; static features used: {static}")
    if len(df) < 30 or df.year.nunique() < 3:
        sys.exit("Too few district-years / years for a meaningful comparison.")

    oofs = [run_scheme(df, s, feature_sets, models, q, seed) for s in ("leave_one_year_out", "leave_district_out")]
    oof = pd.concat(oofs, ignore_index=True)
    summ = summarise(oof, nboot, seed)
    rpt = ensure_dir(cfg["paths"]["reports"])
    oof.to_csv(rpt / "oof_predictions.csv", index=False)

    cols = ["feature_set", "model", "n", "macro_f1", "macro_f1_lo", "macro_f1_hi", "qwk", "qwk_lo", "qwk_hi", "spearman", "ordinal_mae",
            "within_1_class", "auc_high_or_severe"]
    L = ["# Model comparison (seasonal severity, district-year)\n",
         f"Rows: {len(df)} | districts: {df.district_id.nunique()} | years: {sorted(int(y) for y in df.year.unique())} | static features used: {static}"
         + (f" | dropped (incomplete): {dropped}" if dropped else ""),
         f"\nClasses: quantiles {q} of the metric computed on the TRAINING rows of each fold. Class share in the full table: "
         f"{df['risk_label'].value_counts(normalize=True).round(2).to_dict()}\n",
         "**How to read it.** Rows are pooled out-of-fold predictions. `macro_f1` is averaged over classes present in the test rows; `qwk` = quadratic weighted kappa "
         "(0 = chance, 1 = perfect, penalises large ordinal misses); `spearman` correlates the model's expected class with the true impact; "
         "`auc_high_or_severe` separates the top two classes from the rest. Intervals are 95 % bootstrap over rows (rows of one district are "
         "correlated, so they are optimistic). **A model is only better than a baseline if its interval clearly clears the baseline's.**\n"]
    best = {}
    for scheme in ("leave_one_year_out", "leave_district_out"):
        s = summ[summ.scheme == scheme].copy()
        s = s.sort_values(["feature_set", "model"])
        L.append(f"## {scheme.replace('_', ' ')}\n\n" + md(s[cols]) + "\n")
        base = s[s.feature_set == "baseline"]
        mods = s[s.feature_set != "baseline"]
        if len(mods):
            top = mods.sort_values("qwk", ascending=False).iloc[0]
            bb = base["qwk"].max() if len(base) and base["qwk"].notna().any() else 0.0   # constant predictions have QWK 0 by definition
            best[scheme] = {"feature_set": top.feature_set, "model": top.model, "qwk": float(top.qwk), "qwk_lo": float(top.qwk_lo),
                            "best_baseline_qwk": float(bb) if np.isfinite(bb) else None,
                            "clearly_better_than_baseline": bool(np.isfinite(bb) and top.qwk_lo > bb)}
    L.append("## Verdict\n")
    for k, v in best.items():
        L.append(f"- **{k}**: best by QWK = `{v['feature_set']}` / `{v['model']}` (QWK {v['qwk']:.2f}, lower bound {v['qwk_lo']:.2f}); best baseline QWK "
                 f"{v['best_baseline_qwk'] if v['best_baseline_qwk'] is None else round(v['best_baseline_qwk'], 2)}. "
                 + ("Its interval clears the best baseline." if v["clearly_better_than_baseline"] else
                    "**Its interval does NOT clear the best baseline: do not claim it beats the baselines.**"))
    sy = summ[(summ.scheme == "leave_one_year_out") & summ.feature_set.isin(["static_only", "static_plus_rain"])]
    for m in sy["model"].unique():
        a = sy[(sy.model == m) & (sy.feature_set == "static_only")]["qwk"]
        b = sy[(sy.model == m) & (sy.feature_set == "static_plus_rain")]["qwk"]
        if len(a) and len(b):
            L.append(f"- Ablation ({m}, leave-one-year-out QWK): static_only {a.iloc[0]:.2f} -> static_plus_rain {b.iloc[0]:.2f}.")
    L.append("\nCalibration: not assessed. With this few rows a reliability curve would be meaningless; probabilities are reported as UNCALIBRATED.")
    (rpt / "model_comparison.md").write_text("\n".join(L))
    (rpt / "model_comparison.json").write_text(json.dumps({"best": best, "n_rows": len(df)}, indent=2))
    log.info("\n" + "\n".join(L[-8:]))
    log.info(f"Report -> {rpt/'model_comparison.md'}")


if __name__ == "__main__":
    main()
