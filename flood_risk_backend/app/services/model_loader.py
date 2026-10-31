"""Loads the trained model, SHAP explainer, feature list and metadata. Absent-safe: returns None when nothing has been trained.

There is NO shipped model: run `python scripts/train_model.py` on the data-prep export first.
"""
import json
import os
from functools import lru_cache

import joblib

from app.config import settings

NOT_TRAINED_MSG = ("No trained model found. Copy the data-prep export into data/ and run `python scripts/train_model.py` "
                   "(see README).")


class ModelBundle:
    def __init__(self, model, explainer, feature_list: list[str], metadata: dict):
        self.model = model
        self.explainer = explainer
        self.feature_list = feature_list
        self.metadata = metadata
        self.model_version: str = metadata.get("model_version", "unknown")
        self.class_labels: list[str] = [str(c) for c in model.classes_]


@lru_cache(maxsize=1)
def get_model_bundle() -> ModelBundle | None:
    paths = (settings.MODEL_PATH, settings.EXPLAINER_PATH, settings.FEATURE_LIST_PATH, settings.MODEL_METADATA_PATH)
    if not all(os.path.exists(p) for p in paths):
        return None
    with open(settings.FEATURE_LIST_PATH) as f:
        feature_list = json.load(f)
    with open(settings.MODEL_METADATA_PATH) as f:
        metadata = json.load(f)
    return ModelBundle(joblib.load(settings.MODEL_PATH), joblib.load(settings.EXPLAINER_PATH), feature_list, metadata)


def read_metadata() -> dict | None:
    """Metadata only (does not need the model to load); used by /model/metadata and the history fallback."""
    if not os.path.exists(settings.MODEL_METADATA_PATH):
        return None
    with open(settings.MODEL_METADATA_PATH) as f:
        return json.load(f)
