import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/ml-experiment", tags=["ML experiment"])

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPORT_DIR = BACKEND_DIR / "ml" / "reports"
CLASSES = ["Low", "Moderate", "High", "Severe"]


@router.get("/summary")
def get_ml_experiment():
    report_path = REPORT_DIR / "model_comparison.json"
    predictions_path = REPORT_DIR / "oof_predictions.csv"

    if not report_path.exists() or not predictions_path.exists():
        raise HTTPException(status_code=503, detail="ML experiment report files are unavailable.")

    with report_path.open() as f:
        report = json.load(f)

    model_results = []
    for key, metrics in report["results"].items():
        if not key.startswith("4class/LODO/"):
            continue
        parts = key.split("/")
        model_name = parts[2]
        if "|" in model_name:
            model, features = model_name.split("|", 1)
        else:
            model, features = model_name, "baseline"

        model_results.append({
            "model": model,
            "features": features,
            "accuracy": metrics.get("accuracy"),
            "balanced_accuracy": metrics.get("balanced_accuracy"),
            "macro_f1": metrics.get("macro_f1"),
            "macro_f1_ci95": metrics.get("macro_f1_ci95_district_bootstrap"),
            "ordinal_mae": metrics.get("ordinal_mae"),
        })

    predictions = []
    with predictions_path.open(newline="") as f:
        for row in csv.DictReader(f):
            actual = int(row["risk_class"])
            lr_prediction = int(row["4class/LODO/logreg|static_plus_rain"])
            rf_prediction = int(row["4class/LODO/random_forest|static_plus_rain"])
            predictions.append({
                "district_id": row["district_id"],
                "year": int(row["year"]),
                "actual_class": CLASSES[actual],
                "logreg_prediction": CLASSES[lr_prediction],
                "random_forest_prediction": CLASSES[rf_prediction],
            })

    return {
        "status": "experimental_not_integrated",
        "n_rows": report["n_rows"],
        "n_districts": report["n_districts"],
        "attrition": report["attrition"],
        "class_counts": report["class_counts"],
        "models": model_results,
        "permutation_test": report["permutation_test_LODO_RF_4class"],
        "predictions": predictions,
        "limitations": [
            "Only 37 district-season samples from 13 districts were usable.",
            "All four-class model confidence intervals include chance-level macro-F1 of approximately 0.25.",
            "The intended Random Forest with terrain and rainfall scored macro-F1 0.19.",
            "The Random Forest permutation test did not show evidence of predictive signal.",
            "Flood labels use relative impact bands and an unverified population denominator.",
            "Rainfall coverage is unavailable for 20 of 33 districts.",
            "These are retrospective out-of-fold validation results, not current predictions.",
            "No trained model is integrated into the live assessment system.",
        ],
    }
