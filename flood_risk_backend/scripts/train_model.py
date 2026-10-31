"""Trains the VULNERABILITY model: seasonal flood-impact severity class of a district-year.

Input (from the data-prep export, copied to data/): season_features.csv (district_id, year, risk_class + rainfall features) and
districts.csv (static terrain / population features). REAL DATA ONLY: there is no synthetic fallback.

What it does:
  * leave-one-year-out cross-validation on the labelled district-years, against baselines (majority class, the district's own mean
    class in the other years). Pooled out-of-fold macro-F1, quadratic-weighted kappa, within-one-class accuracy.
  * decides `vulnerability_source`: "ml_model" only if the model's pooled QWK beats the best baseline, else "district_history"
    (the API then uses each district's historical mean class and says so).
  * refits on ALL labelled rows, writes model + SHAP explainer + feature list + metadata to models_artifacts/.
Rows are district-years: with ~33 districts x 5 years the data are small, scores are noisy and should be read as such.

Usage:  python scripts/train_model.py [--model rf|xgb]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import cohen_kappa_score, f1_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.features import CLASS_ORDER, OPTIONAL_STATIC, SEASON_FEATURES, STATIC_FEATURES  # noqa: E402
from app.services.ordinal_xgb import OrdinalXGB  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "..", "models_artifacts")
MIN_ROWS = 20


def make_model(kind):
    if kind == "xgb":
        return OrdinalXGB()
    return RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1)


def load_frame():
    for f in ("season_features.csv", "districts.csv"):
        if not os.path.exists(os.path.join(DATA_DIR, f)):
            raise SystemExit(f"data/{f} not found. Copy the files from flood_data_prep/data/backend_export/ into data/ first.")
    sf = pd.read_csv(os.path.join(DATA_DIR, "season_features.csv"))
    d = pd.read_csv(os.path.join(DATA_DIR, "districts.csv"))
    df = sf.merge(d[["id"] + [c for c in STATIC_FEATURES if c in d.columns]], left_on="district_id", right_on="id", how="left")
    feats = []
    for f in SEASON_FEATURES + STATIC_FEATURES:
        if f not in df.columns:
            raise SystemExit(f"Feature '{f}' missing from the CSVs (export schema mismatch).")
        if df[f].isna().all() or (f in OPTIONAL_STATIC and df[f].isna().any()):
            print(f"NOTE: dropping feature '{f}' (empty for some/all rows).")
            continue
        feats.append(f)
    before = len(df)
    df = df[df["risk_class"].notna()].dropna(subset=feats)
    if len(df) < before:
        print(f"NOTE: {before - len(df)} rows dropped (no label or missing feature values; never imputed).")
    return df.reset_index(drop=True), feats


def scores(y_true, y_pred):
    yi = np.array([CLASS_ORDER.index(c) for c in y_true])
    pi = np.array([CLASS_ORDER.index(c) for c in y_pred])
    present = sorted(set(yi))
    qwk = cohen_kappa_score(yi, pi, weights="quadratic", labels=list(range(4)))
    return {"macro_f1": round(float(f1_score(yi, pi, labels=present, average="macro", zero_division=0)), 4),
            "qwk": round(0.0 if np.isnan(qwk) else float(qwk), 4),
            "within_1_class": round(float((abs(yi - pi) <= 1).mean()), 4),
            "ordinal_mae": round(float(abs(yi - pi).mean()), 4)}


def loyo(df, feats, kind):
    pred = {k: [] for k in ("model", "majority", "district_mean_other_years")}
    truth = []
    for y in sorted(df["year"].unique()):
        tr, te = df[df["year"] != y], df[df["year"] == y]
        if tr["risk_class"].nunique() < 2:
            continue
        m = make_model(kind).fit(tr[feats], tr["risk_class"])
        pred["model"] += list(m.predict(te[feats]))
        pred["majority"] += [tr["risk_class"].mode().iloc[0]] * len(te)
        idx = tr["risk_class"].map(CLASS_ORDER.index)
        dmean = idx.groupby(tr["district_id"]).mean()
        gm = idx.mean()
        pred["district_mean_other_years"] += [CLASS_ORDER[int(min(3, round(dmean.get(d, gm))))] for d in te["district_id"]]
        truth += list(te["risk_class"])
    if not truth:
        raise SystemExit("Cross-validation impossible (need at least two years with at least two classes).")
    return {k: scores(truth, v) for k, v in pred.items()}, len(truth)


def main(kind):
    df, feats = load_frame()
    if len(df) < MIN_ROWS or df["risk_class"].nunique() < 2:
        raise SystemExit(f"Only {len(df)} labelled district-years / {df['risk_class'].nunique()} class(es): too little to train. "
                         "Check flood_data_prep/reports/label_audit.md.")
    print(f"features ({len(feats)}): {feats}\nrows: {len(df)} | years {[int(y) for y in sorted(df['year'].unique())]} | classes {df['risk_class'].value_counts().to_dict()}")
    cv, n_cv = loyo(df, feats, kind)
    best_base = max(cv["majority"]["qwk"], cv["district_mean_other_years"]["qwk"])
    source = "ml_model" if cv["model"]["qwk"] > best_base else "district_history"
    print("leave-one-year-out:", json.dumps(cv, indent=1))
    print(f"vulnerability_source = {source} (model QWK {cv['model']['qwk']} vs best baseline {best_base})")

    model = make_model(kind).fit(df[feats], df["risk_class"])
    seen = [str(c) for c in model.classes_]
    explainer = shap.TreeExplainer(model.model_ if kind == "xgb" else model)
    idx = df["risk_class"].map(CLASS_ORDER.index)
    version = f"{kind}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    joblib.dump(model, os.path.join(ARTIFACT_DIR, "model.joblib"))
    joblib.dump(explainer, os.path.join(ARTIFACT_DIR, "explainer.joblib"))
    json.dump(feats, open(os.path.join(ARTIFACT_DIR, "feature_list.json"), "w"), indent=2)
    thr = os.path.join(DATA_DIR, "label_thresholds.json")
    meta = {
        "model_version": version, "model_type": type(model).__name__, "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(df)), "feature_list": feats, "class_counts": {k: int(v) for k, v in df["risk_class"].value_counts().items()},
        "vulnerability_source": source,
        "cross_validation": {"scheme": "leave_one_year_out", "n_out_of_fold": n_cv, **cv,
                             "caveat": "district-years of the same district are correlated and the sample is small; treat as indicative."},
        "district_history": {str(k): round(float(v), 4) for k, v in idx.groupby(df["district_id"]).mean().items()},
        "thresholds": json.load(open(thr)).get("thresholds") if os.path.exists(thr) else None,
        "notes": (f"Predicts the seasonal flood-IMPACT class (relative bands of % population affected, training-year quantiles) of a "
                  f"district-year from seasonal rainfall, terrain and population features; refit on all labelled rows, so the scores above "
                  f"are cross-validated, not in-sample. Classes seen: {seen}. Used only as the vulnerability component, evaluated at "
                  f"'normal season' rainfall. It is not a flood forecast. Source decision: {source}. No calibration (too few rows)."),
    }
    json.dump(meta, open(os.path.join(ARTIFACT_DIR, "metadata.json"), "w"), indent=2)
    print(f"Saved {version} to {ARTIFACT_DIR}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["rf", "xgb"], default="rf")
    main(ap.parse_args().model)
