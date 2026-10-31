"""Backend half of the parity test: reproduces tests/golden_hazard.json (identical file in flood_data_prep/tests)."""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.services import hazard as H

G = json.loads((Path(__file__).parent / "golden_hazard.json").read_text())


def test_scalar_and_vectorised_match_golden():
    idx = pd.to_datetime(list(G["rain"]))
    s = pd.Series([np.nan if v is None else v for v in G["rain"].values()], index=idx)
    rain = {t.date(): v for t, v in s.items() if not np.isnan(v)}
    q = pd.DataFrame([{"doy": d, **G["quantiles"]} for d in range(1, 367)])
    for w in {c["window"] for c in G["cases"]}:
        sums = H.window_sums(s, w, G["min_obs_fraction"])
        lv = H.levels_series(sums, q, G["level_quantiles"])
        for c in (x for x in G["cases"] if x["window"] == w):
            t = pd.Timestamp(c["end"])
            tot, _ = H.window_total(rain, date.fromisoformat(c["end"]), w, G["min_obs_fraction"])
            lvl = H.level_for_total(tot, G["quantiles"], G["level_quantiles"])
            for got_tot, got_lvl in ((tot, lvl), (None if np.isnan(sums[t]) else sums[t], None if np.isnan(lv[t]) else int(lv[t]))):
                assert (c["total"] is None and got_tot is None) or abs(got_tot - c["total"]) < 1e-6
                assert got_lvl == c["level"]
