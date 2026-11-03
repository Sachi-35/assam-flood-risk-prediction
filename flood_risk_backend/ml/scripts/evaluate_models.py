#!/usr/bin/env python
"""Honest grouped evaluation of baselines, Logistic Regression, Random Forest and XGBoost on the seasonal table.

Validation schemes (rows of one district are never split between train and test within a fold):
  * leave-one-year-out (LOYO)    -> "can the model forecast a new season for districts it has seen?"
  * leave-one-district-out (LODO)-> "can the model score a district it has never seen?"  (the harder, more relevant test)
Metrics are computed on the pooled out-of-fold predictions. Bootstrap intervals resample DISTRICTS (clusters).
Outputs: reports/model_comparison.md, reports/model_comparison.json, reports/oof_predictions.csv
Run:  python scripts/evaluate_models.py            (from flood_risk_backend/ml)
"""
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import ml_common as C

try:
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None

N_BOOT = 1000


def make_model(name: str, seed: int = C.SEED):
    if name == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced"))
    if name == "random_forest":
        return RandomForestClassifier(n_estimators=500, max_depth=3, min_samples_leaf=2, max_features="sqrt",
                                      class_weight="balanced_subsample", random_state=seed, n_jobs=1)
    if name == "xgboost":
        return XGBClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                             min_child_weight=1, reg_lambda=2.0, random_state=seed, n_jobs=1, verbosity=0)
    raise ValueError(name)


def fit_predict(name, Xtr, ytr, Xte, seed=C.SEED):
    """Fit on the classes present in the training fold (XGBoost needs contiguous labels); map back afterwards."""
    present = np.unique(ytr)
    if len(present) == 1:
        return np.full(len(Xte), present[0])
    remap = {c: i for i, c in enumerate(present)}
    m = make_model(name, seed)
    m.fit(Xtr, np.array([remap[v] for v in ytr]))
    return present[m.predict(Xte)]


def majority(ytr, n):
    vals, cnt = np.unique(ytr, return_counts=True)
    return np.full(n, vals[np.argmax(cnt)])


def folds(df, scheme):
    key = "year" if scheme == "LOYO" else "district_id"
    for g in sorted(df[key].unique()):
        te = df.index[df[key] == g].to_numpy()
        tr = df.index[df[key] != g].to_numpy()
        yield g, tr, te


def metrics(y, p, k):
    labs = list(range(k))
    rec = recall_score(y, p, labels=labs, average=None, zero_division=0)
    return {"accuracy": accuracy_score(y, p), "balanced_accuracy": balanced_accuracy_score(y, p),
            "macro_f1": f1_score(y, p, labels=labs, average="macro", zero_division=0),
            "macro_precision": float(np.mean([((p == c) & (y == c)).sum() / max((p == c).sum(), 1) for c in labs])),
            "macro_recall": float(rec.mean()), "per_class_recall": rec.tolist(),
            "ordinal_mae": float(np.abs(y - p).mean()),
            "confusion": confusion_matrix(y, p, labels=labs).tolist()}


def boot_ci(df, ycol, pcol, k, rng):
    groups = df.district_id.unique()
    idx = {g: np.where(df.district_id.to_numpy() == g)[0] for g in groups}
    y, p = df[ycol].to_numpy(), df[pcol].to_numpy()
    vals = []
    for _ in range(N_BOOT):
        pick = np.concatenate([idx[g] for g in rng.choice(groups, len(groups))])
        vals.append(f1_score(y[pick], p[pick], labels=list(range(k)), average="macro", zero_division=0))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def history_baseline(df, labelled_all, scheme_fold_te, tr):
    """District's modal class in the training years (only meaningful for LOYO; unseen districts fall back to majority)."""
    out = []
    te_years = set(df.loc[scheme_fold_te, "year"])
    for i in scheme_fold_te:
        d = df.at[i, "district_id"]
        h = labelled_all[(labelled_all.district_id == d) & (~labelled_all.year.isin(te_years))].risk_class
        out.append(int(round(h.mean())) if len(h) else -1)
    return np.array(out)


def main():
    C.REPORT_DIR.mkdir(exist_ok=True)
    df, log = C.build_model_table()
    labels, _, _ = C.load_inputs()
    hist = labels[(labels.label_status == "reported") & labels.year.isin(C.TRAIN_YEARS)].copy()
    hist["risk_class"] = hist.risk_class.astype(int)
    rng = np.random.default_rng(C.SEED)
    results, oof_cols = {}, {}
    targets = {"4class": (df.risk_class.to_numpy(), 4),
               "2class_high_vs_not": ((df.risk_class.to_numpy() >= 2).astype(int), 2)}
    model_names = ["logreg", "random_forest"] + (["xgboost"] if XGBClassifier else [])
    for tname, (y_all, k) in targets.items():
        df["_y"] = y_all
        for scheme in ["LOYO", "LODO"]:
            runs = {"majority": None}
            if scheme == "LOYO" and tname == "4class":
                runs["district_history"] = None
            for fs in C.FEATURE_SETS:
                for m in model_names:
                    runs[f"{m}|{fs}"] = (m, fs)
            for rname, spec in runs.items():
                pred = np.full(len(df), -1)
                for g, tr, te in folds(df, scheme):
                    ytr = df.loc[tr, "_y"].to_numpy()
                    if rname == "majority":
                        pred[te] = majority(ytr, len(te))
                    elif rname == "district_history":
                        h = history_baseline(df, hist, te, tr)
                        pred[te] = np.where(h < 0, majority(ytr, len(te)), h)
                    else:
                        m, fs = spec
                        cols = C.FEATURE_SETS[fs]
                        pred[te] = fit_predict(m, df.loc[tr, cols].to_numpy(), ytr, df.loc[te, cols].to_numpy())
                df["_p"] = pred
                res = metrics(df._y.to_numpy(), pred, k)
                res["macro_f1_ci95_district_bootstrap"] = boot_ci(df, "_y", "_p", k, rng)
                results[f"{tname}/{scheme}/{rname}"] = res
                oof_cols[f"{tname}/{scheme}/{rname}"] = pred.copy()
    oof = df[["district_id", "year", "risk_label", "risk_class"]].copy()
    for k_, v in oof_cols.items():
        oof[k_] = v
    oof.to_csv(C.REPORT_DIR / "oof_predictions.csv", index=False)

    # permutation check for the main candidate: is the leave-one-district-out macro-F1 distinguishable from chance?
    perm = {}
    df["_y"] = df.risk_class
    for fs in ["static_plus_rain", "rain_only"]:
        cols = C.FEATURE_SETS[fs]
        obs = results[f"4class/LODO/random_forest|{fs}"]["macro_f1"]
        sims = []
        for s in range(100):
            r = np.random.default_rng(1000 + s)
            yperm = df.risk_class.to_numpy().copy()
            for yr in df.year.unique():  # permute within year: keeps each season's class mix
                ix = np.where(df.year.to_numpy() == yr)[0]
                yperm[ix] = r.permutation(yperm[ix])
            pr = np.full(len(df), -1)
            for g, tr, te in folds(df, "LODO"):
                m = RandomForestClassifier(n_estimators=100, max_depth=3, min_samples_leaf=2,
                                           class_weight="balanced_subsample", random_state=s)
                m.fit(df.loc[tr, cols].to_numpy(), yperm[tr])
                pr[te] = m.predict(df.loc[te, cols].to_numpy())
            sims.append(f1_score(yperm, pr, labels=[0, 1, 2, 3], average="macro", zero_division=0))
        perm[fs] = {"observed_macro_f1": obs, "perm_mean": float(np.mean(sims)),
                    "perm_p95": float(np.percentile(sims, 95)),
                    "p_value": float((np.sum(np.array(sims) >= obs) + 1) / (len(sims) + 1))}
    out = {"n_rows": len(df), "n_districts": int(df.district_id.nunique()), "attrition": log,
           "class_counts": df.risk_label.value_counts().reindex(C.CLASSES).fillna(0).astype(int).to_dict(),
           "results": results, "permutation_test_LODO_RF_4class": perm}
    (C.REPORT_DIR / "model_comparison.json").write_text(json.dumps(out, indent=2))
    write_md(out)
    print((C.REPORT_DIR / "model_comparison.md").read_text())


def write_md(out):
    R = out["results"]
    L = ["# Model comparison (seasonal district vulnerability)\n",
         f"Rows: **{out['n_rows']}** district-seasons, **{out['n_districts']}** districts. Class counts: {out['class_counts']}.",
         f"Attrition: {out['attrition']}\n",
         "Pooled out-of-fold results. `CI` = 95% district-bootstrap interval of macro-F1. Chance level for 4 balanced classes is ~0.25.\n"]
    for t in ["4class", "2class_high_vs_not"]:
        for s in ["LODO", "LOYO"]:
            L.append(f"\n## {t} / {s}\n")
            L.append("| model | features | acc | bal.acc | macro-F1 | CI | macro-prec | macro-rec | ordinal MAE |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            for k, v in R.items():
                tt, ss, name = k.split("/")
                if tt != t or ss != s:
                    continue
                m, _, fs = name.partition("|")
                ci = v["macro_f1_ci95_district_bootstrap"]
                L.append(f"| {m} | {fs or '-'} | {v['accuracy']:.2f} | {v['balanced_accuracy']:.2f} | {v['macro_f1']:.2f} | "
                         f"{ci[0]:.2f}-{ci[1]:.2f} | {v['macro_precision']:.2f} | {v['macro_recall']:.2f} | {v['ordinal_mae']:.2f} |")
    L.append("\n## Permutation check (leave-one-district-out, 4-class, Random Forest, labels shuffled within year, 100 runs)\n")
    for fs, v in out["permutation_test_LODO_RF_4class"].items():
        L.append(f"- {fs}: observed macro-F1 {v['observed_macro_f1']:.2f}; shuffled-label mean {v['perm_mean']:.2f}, "
                 f"95th percentile {v['perm_p95']:.2f}; p = {v['p_value']:.2f}")
    (C.REPORT_DIR / "model_comparison.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
