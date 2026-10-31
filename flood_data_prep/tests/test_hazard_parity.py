"""Golden-vector test: tests/golden_hazard.json is IDENTICAL in both projects (same file content, checked by sha) and each project's own
implementation must reproduce it. If you change the hazard methodology, regenerate the file and copy it to the other project."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from floodprep import climatology as C

G = json.loads((Path(__file__).parent / "golden_hazard.json").read_text())


def test_prep_matches_golden():
    idx = pd.to_datetime(list(G["rain"]))
    s = pd.Series([np.nan if v is None else v for v in G["rain"].values()], index=idx)
    q = pd.DataFrame([{"doy": d, **G["quantiles"]} for d in range(1, 367)])
    for w in {c["window"] for c in G["cases"]}:
        sums = C.window_sum(s, w, G["min_obs_fraction"])
        lv = C.hazard_levels(sums, q, G["level_quantiles"])["level"]
        for c in (x for x in G["cases"] if x["window"] == w):
            t = pd.Timestamp(c["end"])
            assert (c["total"] is None and np.isnan(sums[t])) or abs(sums[t] - c["total"]) < 1e-6
            assert (c["level"] is None and np.isnan(lv[t])) or lv[t] == c["level"]


def test_backend_copy_identical_and_matches_if_present():
    backend = Path(__file__).resolve().parents[2] / "flood_risk_backend"
    if not backend.exists():
        pytest.skip("backend project not next to this one")
    assert (backend / "tests" / "golden_hazard.json").read_bytes() == (Path(__file__).parent / "golden_hazard.json").read_bytes()
